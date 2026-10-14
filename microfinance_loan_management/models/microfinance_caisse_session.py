# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class MicrofinanceCaisseSession(models.Model):
    _name = 'microfinance.caisse.session'
    _description = 'Session de caisse (guichet)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, journal_id'

    # Related exposé séparément (plutôt que company_id.cash_journal_id inline dans le domain
    # ci-dessous) : le domain d'une vue est évalué côté client sur le evalContext de
    # l'enregistrement, où un Many2one ne porte que son id, pas ses propres sous-champs -
    # 'company_id.cash_journal_id' y échouerait silencieusement (attribut introuvable sur un
    # entier). Un champ related à plat sur ce modèle, lui, est bien chargé dans ce contexte.
    company_cash_journal_id = fields.Many2one(
        related='company_id.cash_journal_id', string='Journal de caisse autorisé (agence)',
    )
    journal_id = fields.Many2one(
        'account.journal', string='Journal de caisse', required=True, tracking=True,
        domain="[('id', '=', company_cash_journal_id)]",
        default=lambda self: self.env.company.cash_journal_id,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    cashier_id = fields.Many2one(
        'res.users', string='Caissier', required=True, tracking=True,
        default=lambda self: self.env.user,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('open', 'Ouverte'),
        ('closed', 'Clôturée'),
    ], string='État', default='draft', required=True, tracking=True)
    reopen_reason = fields.Char(
        string='Motif de réouverture',
        help="À renseigner avant de cliquer sur « Rouvrir la session » : consigné dans le "
             "suivi de la session (qui, quand, pourquoi), puis effacé après la réouverture.",
    )

    # La session ne porte aucun solde propre : elle alimente microfinance.caisse.fiche.journee
    # (1 session = 1 fiche, cf. décisions actées) et se contente de relayer ses montants, plutôt
    # que de dupliquer la logique de calcul déjà en place sur la fiche (_refresh_amounts).
    fiche_journee_id = fields.Many2one(
        'microfinance.caisse.fiche.journee', string='Fiche journalière', readonly=True, copy=False,
    )
    opening_balance = fields.Monetary(related='fiche_journee_id.opening_balance', readonly=True, string="Solde d'ouverture")
    total_debit = fields.Monetary(related='fiche_journee_id.total_debit', readonly=True, string='Total débits du jour')
    total_credit = fields.Monetary(related='fiche_journee_id.total_credit', readonly=True, string='Total crédits du jour')
    closing_balance = fields.Monetary(related='fiche_journee_id.closing_balance', readonly=True, string='Solde de clôture calculé')
    theoretical_balance = fields.Monetary(
        compute='_compute_theoretical_balance', string='Solde théorique de la session',
        help="opening_balance + mouvements réellement enregistrés pendant CETTE session "
             "(microfinance.caisse.mouvement, retracés jusqu'à leur écriture comptable sur le "
             "compte du journal de caisse), pas le solde du journal comptable de la journée "
             "entière (fiche_journee). Non stocké : recalculé à chaque lecture, jamais périmé.",
    )

    _sql_constraints = [
        ('journal_date_unique', 'unique(journal_id, date)',
         'Une seule session de caisse par journal et par jour.'),
    ]

    @api.onchange('company_id')
    def _onchange_company_id_journal(self):
        for session in self:
            session.journal_id = session.company_id.cash_journal_id

    @api.constrains('journal_id', 'company_id')
    def _check_journal_matches_company_cash_journal(self):
        # Le domain du champ (ci-dessus) ne bloque que la saisie UI, pas un create()/write()
        # par RPC ou API : cette contrainte serveur est la seule barrière réelle empêchant
        # d'ouvrir une session sur un journal autre que le journal de caisse guichet configuré
        # pour l'agence (company_id.cash_journal_id).
        for session in self:
            if session.journal_id and session.journal_id != session.company_id.cash_journal_id:
                raise ValidationError(_(
                    "Le journal « %(journal)s » n'est pas le journal de caisse guichet configuré "
                    "pour l'agence %(company)s. Configurez-le dans Paramètres > Sociétés, "
                    "ou choisissez le journal attendu."
                ) % {'journal': session.journal_id.name, 'company': session.company_id.name})

    def _get_session_moves(self):
        """Écritures comptables réellement générées par LES mouvements de cette session
        (microfinance.caisse.mouvement, ajouté par _inherit dans microfinance_savings_management
        - modèle non référencé statiquement ici pour ne pas créer de dépendance manifeste
        inversée, cf. AUDIT_session_zigzag). Chaque mouvement est retracé jusqu'à l'écriture
        qu'il a réellement posée (transaction épargne, remboursement, décaissement, frais) :
        pas de nouvelle écriture recréée ici, on relit ce qui a déjà été comptabilisé.

        Les mouvements 'frais_dossier' sont retournés séparément (fee_moves) : leur écriture
        est postée sur product_id.fee_journal_id, un journal/compte configuré par produit et
        par agence (pas le journal de caisse de la session), qui ne coïncide avec aucun compte
        caisse aujourd'hui mais n'a aucune garantie structurelle de le rester (cf.
        AUDIT_solde_caisse_frais_dossier) - _compute_theoretical_balance ne peut donc pas se
        fier au filtre account_id pour ce type, et doit les compter par mouvement.amount.

        Les mouvements 'depot_epargne'/'retrait_epargne' sont retournés séparément de la même
        façon (savings_moves) : leur écriture est postée sur product_id.deposit_journal_id/
        withdrawal_journal_id (compte du PRODUIT d'épargne), jamais sur le compte de la session
        caisse guichet - confirmé sur plusieurs agences (cf. AUDIT_solde_caisse_epargne_
        20260927.md) : aucun dépôt/retrait épargne n'a jamais incrémenté le solde théorique par
        le filtre account_id. Même traitement que frais_dossier : comptées à part par
        mouvement.amount, jamais via account.move.line, exclues du bucket générique `moves`
        pour ne jamais risquer un double comptage si le journal produit venait à coïncider par
        hasard avec le journal caisse sur une agence."""
        self.ensure_one()
        moves = self.env['account.move']
        fee_moves = self.env['account.move']
        savings_moves = self.env['account.move']
        if 'mouvement_ids' not in self._fields:
            return moves, fee_moves, savings_moves
        for mouvement in self.mouvement_ids:
            if mouvement.type in ('depot_epargne', 'retrait_epargne'):
                move = mouvement.savings_transaction_id.move_id
                if move:
                    savings_moves |= move
                continue
            elif mouvement.type == 'remboursement_credit':
                move = mouvement.payment_id.move_id
            elif mouvement.type == 'decaissement_credit':
                move = mouvement.loan_id.disbursement_move_id
            elif mouvement.type == 'frais_dossier':
                move = mouvement.fee_move_id
                if move:
                    fee_moves |= move
                continue
            else:
                move = self.env['account.move']
            if move:
                moves |= move
        return moves, fee_moves, savings_moves

    @api.depends('opening_balance', 'journal_id.default_account_id', 'state')
    def _compute_theoretical_balance(self):
        for session in self:
            account = session.journal_id.default_account_id
            if session.state == 'draft' or not account:
                session.theoretical_balance = session.opening_balance
                continue
            moves, fee_moves, savings_moves = session._get_session_moves()
            # Un décaissement réglé par chèque/virement (journal 'bank') poste sur le compte de
            # ce journal, pas sur le compte caisse (account) : filtrer sur account_id exclut
            # naturellement ces mouvements du solde ESPÈCES théorique, sans avoir à retracer le
            # moyen de paiement choisi au guichet (cf. register_operation, Sous-lot D). Les
            # écritures de frais_dossier (fee_moves) et de dépôt/retrait épargne (savings_moves)
            # sont explicitement exclues de ce filtre, même si leur compte venait à coïncider
            # avec account : elles sont comptées à part ci-dessous (net_fees / net_savings),
            # jamais via account.move.line, pour éviter tout double comptage en cas de
            # coïncidence de compte.
            lines = moves.line_ids.filtered(
                lambda l: l.account_id == account and l.move_id not in fee_moves and l.move_id not in savings_moves)
            net_cash = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))
            # Espèces sans équivalent sur le compte de la session (remboursement ou décaissement
            # espèces posté sur le compte d'un AUTRE journal de caisse, p. ex. journal du produit
            # distinct du journal de la session) : comptées par mouvement.amount, et seulement
            # celles-là - un mouvement dont l'écriture touche le compte de la session reste lu
            # dans le grand livre ci-dessus, donc jamais compté deux fois. Chèque/virement : jamais
            # des espèces, ni ici ni via le grand livre.
            for mouvement in session.mouvement_ids.filtered(
                    lambda m: m.type in ('remboursement_credit', 'decaissement_credit')):
                # Mouvement sans pièce rattachée (données historiques) : rien ne prouve le moyen de
                # paiement, il n'est donc pas compté (comportement inchangé).
                source = mouvement.payment_id if mouvement.type == 'remboursement_credit' else mouvement.loan_id
                if not source:
                    continue
                move = (mouvement.payment_id.move_id if mouvement.type == 'remboursement_credit'
                        else mouvement.loan_id.disbursement_move_id)
                if move and move.line_ids.filtered(lambda l: l.account_id == account):
                    continue
                if mouvement.type == 'decaissement_credit':
                    if mouvement.loan_id.disbursement_payment_method not in (False, 'cash'):
                        continue
                    net_cash -= mouvement.amount
                else:
                    net_cash += mouvement.amount
            fee_mouvements = session.mouvement_ids.filtered(lambda m: m.type == 'frais_dossier')
            net_fees = sum(fee_mouvements.mapped('amount'))
            # Signe : un dépôt épargne fait rentrer de l'argent en caisse (comme un
            # remboursement crédit) -> positif ; un retrait épargne en fait sortir -> négatif.
            deposit_mouvements = session.mouvement_ids.filtered(lambda m: m.type == 'depot_epargne')
            withdrawal_mouvements = session.mouvement_ids.filtered(lambda m: m.type == 'retrait_epargne')
            net_savings = sum(deposit_mouvements.mapped('amount')) - sum(withdrawal_mouvements.mapped('amount'))
            session.theoretical_balance = session.opening_balance + net_cash + net_fees + net_savings

    def _check_cashier_has_no_other_open_session(self, cashier_id, exclude_session_id=False):
        """Un même caissier ne peut pas avoir deux sessions 'open' en parallèle (même sur des
        journaux ou des dates différents) : c'est ce qui a permis le bug AUDIT_anomalies_
        ampitatafika_ambanidia_20260921.md §2 (Ambanidia) - une session laissée ouverte au-delà
        d'un jour, plus une seconde ouverte ensuite sur le même journal, ont fait basculer
        silencieusement le guichet OWL d'une session à l'autre (limit 1, order date desc) sans
        que le caissier s'en aperçoive, vidant le ticket affiché. Appelée uniquement ici
        (action_open_session, point de passage unique : le wizard d'ouverture termine toujours
        par session.action_open_session()) plutôt que dupliquée côté wizard, pour ne pas risquer
        de bloquer à tort la réouverture idempotente de la session du jour déjà 'open'."""
        domain = [('cashier_id', '=', cashier_id), ('state', '=', 'open')]
        if exclude_session_id:
            domain.append(('id', '!=', exclude_session_id))
        # sudo() ciblé sur cette seule recherche : une règle multi-agences ne doit pas masquer
        # la session ouverte du même caissier dans une autre agence (aucune donnée exposée,
        # seuls le journal et la date de la session bloquante figurent dans le message).
        other = self.sudo().search(domain, limit=1)
        if other:
            raise UserError(_(
                "%(cashier)s a déjà une session de caisse ouverte (%(journal)s, %(date)s) : "
                "clôturez-la avant d'en ouvrir une nouvelle."
            ) % {
                'cashier': other.cashier_id.name,
                'journal': other.journal_id.name,
                'date': other.date,
            })

    @api.constrains('state', 'cashier_id')
    def _check_one_open_session_per_cashier(self):
        """Filet serveur du verrou « une seule session ouverte par caissier » : action_open_session()
        ne couvre pas un create()/write() direct avec state='open' (RPC, import, réouverture
        manager). Ne joue que sur la session qui devient/est 'open' ; un autre caissier n'est
        jamais concerné (le contrôle est par caissier, pas par journal)."""
        for session in self.filtered(lambda s: s.state == 'open'):
            session._check_cashier_has_no_other_open_session(
                session.cashier_id.id, exclude_session_id=session.id)

    def action_open_session(self):
        for session in self:
            if session.state == 'open':
                continue
            if session.state == 'closed':
                raise UserError(_('Cette session est déjà clôturée.'))
            session._check_cashier_has_no_other_open_session(
                session.cashier_id.id, exclude_session_id=session.id)
            fiche = self.env['microfinance.caisse.fiche.journee'].search([
                ('journal_id', '=', session.journal_id.id),
                ('date', '=', session.date),
            ], limit=1)
            if fiche and fiche.state == 'closed':
                raise UserError(_(
                    "La fiche journalière du %(date)s pour le journal « %(journal)s » est déjà "
                    "clôturée. Un manager doit la rouvrir (motif requis) avant d'ouvrir une "
                    "nouvelle session sur ce journal pour ce jour."
                ) % {'date': session.date, 'journal': session.journal_id.name})
            if not fiche:
                fiche = self.env['microfinance.caisse.fiche.journee'].create({
                    'journal_id': session.journal_id.id,
                    'date': session.date,
                    'company_id': session.company_id.id,
                })
            session.write({'fiche_journee_id': fiche.id, 'state': 'open'})
            session.message_post(body=_('Session ouverte par %s.') % session.cashier_id.name)

    def action_open_close_wizard(self):
        """Ouvre l'assistant de clôture avec comptage de billetage (sous-lot B). Seul point
        d'entrée UI de la clôture : appelé depuis le bouton "Fermer la caisse" de l'en-tête du
        guichet, via orm.call + doAction() sur le dict brut renvoyé ici (pas de bouton
        type="object" côté vue, qui passerait par l'enrichissement serveur de
        ir.actions.act_window.read()). 'views' doit donc être fourni explicitement : 'view_mode'
        seul suffit pour une action ENREGISTRÉE en base (lue via read()), pas pour un dict
        construit à la main et transmis brut au client OWL - _preprocessAction() plante sinon
        sur action.views.map() (cf. AUDIT_session_close_action_views). action_close_session
        reste appelée, inchangée, par le wizard (et par les tests)."""
        self.ensure_one()
        if self.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Clôturer la session'),
            'res_model': 'microfinance.caisse.close.session.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_close_session(self):
        for session in self:
            if session.state != 'open':
                raise UserError(_('Seule une session ouverte peut être clôturée.'))
            # Verrou pessimiste ligne (FOR UPDATE) posé AVANT la relecture de state : sérialise
            # deux clôtures concurrentes de la même session (bouton fiche via le wizard de
            # comptage + éventuel appel guichet), sur le modèle exact de action_charge_fee /
            # action_process_disbursement (docs_dev/guichet_caisse/AUDIT_session_billetage.md
            # §4). La transaction perdante attend le commit de la gagnante sur ce SELECT, puis
            # invalide son cache et retombe sur la garde ci-dessous — au lieu de rejouer
            # action_close_day() et de réécrire state='closed'. Verrou relâché au commit/rollback.
            session.env.cr.execute(
                "SELECT id FROM microfinance_caisse_session WHERE id = %s FOR UPDATE", (session.id,))
            session.invalidate_recordset(['state'])
            if session.state != 'open':
                raise UserError(_('Seule une session ouverte peut être clôturée.'))
            # Ne redéclenche aucun contrôle ici : action_close_day() porte déjà la
            # séquentialité chronologique et la vérification d'écart de solde. Une erreur levée
            # ici doit remonter telle quelle à l'utilisateur, sans quoi state='closed' n'est
            # jamais écrit — la session reste 'open' tant que la fiche n'est pas réellement
            # clôturée.
            session.fiche_journee_id.action_close_day()
            session.write({'state': 'closed'})
            session.message_post(body=_('Session clôturée par %s.') % self.env.user.name)

    def action_reopen_session(self):
        """Même garde-fou que fiche_journee.action_reopen_day() : réservé aux managers, motif
        obligatoire (champ reopen_reason renseigné avant l'appel). Rouvre aussi la fiche
        journalière liée si elle est encore clôturée, avec le même motif, pour que les deux
        états restent synchronisés — sans quoi action_open_session() (qui refuse d'ouvrir une
        session sur une fiche clôturée) resterait bloquée juste après cette réouverture."""
        if not self.env.user.has_group('microfinance_loan_management.group_microfinance_manager'):
            raise AccessError(_('Seul un manager peut rouvrir une session de caisse clôturée.'))
        for session in self:
            if session.state != 'closed':
                continue
            if not (session.reopen_reason or '').strip():
                raise UserError(_(
                    'Le motif de réouverture est requis avant de rouvrir cette session.'))
            if session.fiche_journee_id and session.fiche_journee_id.state == 'closed':
                session.fiche_journee_id.write({'reopen_reason': session.reopen_reason})
                session.fiche_journee_id.action_reopen_day()
            session.message_post(body=_(
                'Session rouverte par %(user)s. Motif : %(reason)s'
            ) % {'user': self.env.user.name, 'reason': session.reopen_reason})
            session.write({'state': 'open', 'reopen_reason': False})
