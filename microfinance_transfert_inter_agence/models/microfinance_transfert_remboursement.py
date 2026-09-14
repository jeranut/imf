# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MicrofinanceTransfertRemboursement(models.Model):
    """Un remboursement de crédit encaissé par une agence AUTRE que l'agence
    propriétaire du crédit.

    Cycle de vie et comptabilisation (les 4 écritures réutilisent toutes des
    primitives existantes — cf. docs_dev/guichet_caisse/AUDIT_transfert_inter_agence.md
    et le plan de mise en œuvre, sous-lot C) :

      1. action_encaisser()            — agence SOURCE, session ouverte.
         Écriture : Dr caisse source / Cr 302000 source (montant = amount).
         => l'argent compte IMMÉDIATEMENT dans le solde caisse source.
         Trace : microfinance.caisse.mouvement type 'transfert_sortant'.
         État : 'en_attente' (pas encore loti).

      2. microfinance.transfert.lot.action_valider() — remise au coursier.
         Écriture (au niveau du lot) : Dr 302000 source / Cr caisse source.
         => solde le transit source, l'argent physique quitte le coffre.
         État : 'en_attente' -> 'en_transit'.

      3. + 4. action_valider_destination(session_destination_id) — agence DESTINATION.
         3. Dr caisse destination / Cr 302000 destination
            => l'argent physique arrive dans le coffre destination.
         4. microfinance.loan.payment normal (cascade _allocate_to_installments
            INCHANGÉE), mais journal = TRANSIT destination : sa ligne de caisse
            débite 302000 destination, qui se solde ainsi contre l'étape 3.
            Résultat net = un remboursement ordinaire encaissé sur la caisse
            destination.
         Trace : microfinance.caisse.mouvement type 'transfert_entrant'.
         État : 'en_transit' -> 'valide' (payment_id renseigné).

    Le sudo des étapes comptabilisantes (le caissier n'a ni create sur
    account.move ni write sur microfinance.loan.installment) est circonscrit aux
    helpers _post_transfer_move / action_valider_destination de CE module — le
    _run_posting_sudo de microfinance.caisse.mouvement n'est pas élargi.

    Modèle volontairement visible par DEUX agences (source ET destination) — voir
    security/microfinance_transfert_rules.xml et l'audit §2.3.
    """
    _name = 'microfinance.transfert.remboursement'
    _description = "Transfert de remboursement crédit inter-agences"
    _order = 'id desc'
    _rec_name = 'transfer_code'

    # Point d'extension épargne (décision actée). Aujourd'hui une seule valeur.
    # Le jour où le dépôt / retrait d'épargne inter-agence sera implémenté :
    # ajouter la ou les valeurs ici ET un champ savings_account_id
    # (M2o microfinance.savings.account) EXCLUSIF de loan_id — même patron
    # optionnel-exclusif que microfinance.caisse.mouvement (loan_id /
    # savings_account_id). Ne PAS ajouter savings_account_id maintenant.
    operation_type = fields.Selection(
        [('remboursement_credit', 'Remboursement crédit')],
        string="Type d'opération", required=True, default='remboursement_credit',
    )

    transfer_code = fields.Char(
        string='Code de transfert', required=True, readonly=True, copy=False, index=True,
        default='Nouveau',
        help="Généré une seule fois à la création "
             "(res.company._build_microfinance_transfer_code), jamais régénéré. Format : "
             "T/<n° compte client>/<préfixe source>/<ordre source>/<jj>/<mm>/<aa>/"
             "<préfixe destination>/<ordre destination>.",
    )

    loan_id = fields.Many2one(
        'microfinance.loan', string='Crédit', required=True, ondelete='restrict', index=True,
        help="Crédit remboursé — appartient à l'agence destination.",
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client', related='loan_id.partner_id', store=True, readonly=True,
    )
    amount = fields.Monetary(string='Montant remis', required=True)
    currency_id = fields.Many2one(related='session_id.currency_id', readonly=True)

    session_id = fields.Many2one(
        'microfinance.caisse.session', string='Session (source)', required=True,
        ondelete='restrict', index=True,
        help="Session de caisse de l'agence SOURCE ayant encaissé le remboursement.",
    )
    source_company_id = fields.Many2one(
        'res.company', string='Agence source (encaisse)',
        related='session_id.company_id', store=True, readonly=True, index=True,
    )
    destination_company_id = fields.Many2one(
        'res.company', string='Agence destination (propriétaire du crédit)',
        related='loan_id.company_id', store=True, readonly=True, index=True,
    )
    date_encaissement = fields.Datetime(
        string="Date d'encaissement", required=True, default=fields.Datetime.now, readonly=True,
    )

    state = fields.Selection(
        [
            ('en_attente', 'En attente'),
            ('en_transit', 'En transit'),
            ('valide', 'Validé'),
            ('annule', 'Annulé'),
        ],
        string='État', required=True, default='en_attente', copy=False, index=True,
    )

    lot_id = fields.Many2one(
        'microfinance.transfert.lot', string='Lot de rapatriement',
        ondelete='set null', copy=False, index=True,
    )

    # --- Traçabilité comptable (renseignés par les action_* ci-dessous) ---
    caisse_account_id = fields.Many2one(
        'account.account', string='Compte caisse source', readonly=True, copy=False,
        help="Compte de caisse débité à l'encaissement (étape 1) — soldé à l'identique "
             "au moment de la remise du lot (étape 2).",
    )
    encaissement_move_id = fields.Many2one(
        'account.move', string="Écriture d'encaissement (étape 1)", readonly=True, copy=False,
    )
    reception_move_id = fields.Many2one(
        'account.move', string='Écriture de réception (étape 3)', readonly=True, copy=False,
    )
    session_destination_id = fields.Many2one(
        'microfinance.caisse.session', string='Session destination (validation)',
        readonly=True, copy=False,
    )
    payment_id = fields.Many2one(
        'microfinance.loan.payment', string='Remboursement comptabilisé (étape 4)',
        readonly=True, copy=False,
    )
    caisse_mouvement_source_id = fields.Many2one(
        'microfinance.caisse.mouvement', string='Ligne de caisse source',
        readonly=True, copy=False,
    )
    caisse_mouvement_dest_id = fields.Many2one(
        'microfinance.caisse.mouvement', string='Ligne de caisse destination',
        readonly=True, copy=False,
    )
    cashier_source_id = fields.Many2one(
        'res.users', string='Caissier source', readonly=True, copy=False,
        default=lambda self: self.env.user,
    )
    cashier_destination_id = fields.Many2one(
        'res.users', string='Caissier destination', readonly=True, copy=False,
    )

    _sql_constraints = [
        ('transfer_code_unique', 'unique(transfer_code)',
         "Le code de transfert doit être unique."),
    ]

    # ------------------------------------------------------------------
    # Création : génération du code de transfert (sous-lot A)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (vals.get('transfer_code', 'Nouveau') in ('Nouveau', False)
                    and vals.get('session_id') and vals.get('loan_id')):
                session = self.env['microfinance.caisse.session'].browse(vals['session_id'])
                # sudo : le crédit appartient à l'agence destination, invisible au
                # caissier source qui crée le transfert.
                loan = self.env['microfinance.loan'].sudo().browse(vals['loan_id'])
                date = fields.Datetime.to_datetime(vals.get('date_encaissement')) \
                    or fields.Datetime.now()
                # session.company_id = agence source ; loan.company_id = agence destination.
                vals['transfer_code'] = session.company_id._build_microfinance_transfer_code(
                    loan.company_id, loan.partner_id.microfinance_account_number, date=date,
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Helpers comptables (sudo ciblé, propre à ce module)
    # ------------------------------------------------------------------
    @api.model
    def _get_company_transit_journal(self, company):
        journal = self.env['account.journal'].sudo().search(
            [('code', '=', 'TRANSIT'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(_(
                "L'agence « %s » n'a pas de journal « Transit inter-agences » (code TRANSIT). "
                "Mettez à jour le module microfinance_transfert_inter_agence."
            ) % company.display_name)
        return journal

    def _post_transfer_move(self, journal, ref, line_specs):
        """Crée + poste EN SUDO un account.move de liaison à 2 lignes.

        `line_specs` : liste de (name, account, debit, credit). Le caissier n'a
        pas create sur account.move : le sudo est strictement circonscrit à cet
        appel (équivalent, pour ce module, de
        microfinance.caisse.mouvement._run_posting_sudo, volontairement séparé).
        """
        self.ensure_one()
        move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': ref,
            'line_ids': [
                (0, 0, {
                    'name': name, 'account_id': acc.id,
                    'partner_id': self.partner_id.id,
                    'debit': debit, 'credit': credit,
                })
                for (name, acc, debit, credit) in line_specs
            ],
        })
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Étape 1 — encaissement à l'agence source
    # ------------------------------------------------------------------
    def action_encaisser(self):
        self.ensure_one()
        if self.state != 'en_attente':
            raise UserError(_("Seul un transfert « En attente » peut être encaissé."))
        if self.encaissement_move_id:
            raise UserError(_("Ce transfert a déjà été encaissé (écriture %s).")
                            % self.encaissement_move_id.name)
        session = self.session_id
        if session.state != 'open':
            raise UserError(_("La session de caisse source n'est pas ouverte."))
        if session.company_id != self.source_company_id:
            raise UserError(_("Incohérence : la session n'appartient pas à l'agence source."))
        caisse_account = session.journal_id.default_account_id
        if not caisse_account:
            raise UserError(_(
                "Le journal de la session source (%s) n'a pas de compte par défaut : "
                "impossible de mouvementer la caisse."
            ) % session.journal_id.display_name)
        transit_journal = self._get_company_transit_journal(self.source_company_id)
        transit_account = transit_journal.default_account_id
        if not transit_account:
            raise UserError(_(
                "Le journal TRANSIT de l'agence source n'a pas de compte par défaut (302000)."))

        move = self._post_transfer_move(
            transit_journal, self.transfer_code,
            [
                # L'argent entre physiquement dans le coffre source.
                (_("Encaissement transfert %s") % self.transfer_code,
                 caisse_account, self.amount, 0.0),
                # Contrepartie : compte de liaison inter-agences (soldé à l'étape 2).
                (_("Transit transfert %s") % self.transfer_code,
                 transit_account, 0.0, self.amount),
            ],
        )
        mouvement = self.env['microfinance.caisse.mouvement'].sudo().create({
            'session_id': session.id,
            'type': 'transfert_sortant',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'loan_id': self.loan_id.id,
            'transfert_remboursement_id': self.id,
        })
        self.write({
            'encaissement_move_id': move.id,
            'caisse_account_id': caisse_account.id,
            'caisse_mouvement_source_id': mouvement.id,
            'cashier_source_id': self.env.user.id,
        })
        return True

    # ------------------------------------------------------------------
    # Étapes 3 + 4 — réception et validation à l'agence destination
    # ------------------------------------------------------------------
    def action_valider_destination(self, session_destination_id):
        self.ensure_one()
        if self.state != 'en_transit':
            raise UserError(_("Seul un transfert « En transit » peut être validé à destination."))
        session = self.env['microfinance.caisse.session'].browse(session_destination_id)
        if not session.exists() or session.state != 'open':
            raise UserError(_("Aucune session de caisse ouverte à l'agence destination."))
        if session.company_id != self.destination_company_id:
            raise UserError(_(
                "La session de validation n'appartient pas à l'agence destination du transfert."))
        caisse_account = session.journal_id.default_account_id
        if not caisse_account:
            raise UserError(_("Le journal de la session destination n'a pas de compte par défaut."))
        transit_journal = self._get_company_transit_journal(self.destination_company_id)
        transit_account = transit_journal.default_account_id
        if not transit_account:
            raise UserError(_(
                "Le journal TRANSIT de l'agence destination n'a pas de compte par défaut (302000)."))

        # Étape 3 — l'argent physique arrive dans le coffre destination.
        reception_move = self._post_transfer_move(
            transit_journal, self.transfer_code,
            [
                (_("Réception transfert %s") % self.transfer_code,
                 caisse_account, self.amount, 0.0),
                (_("Transit transfert %s") % self.transfer_code,
                 transit_account, 0.0, self.amount),
            ],
        )

        # Étape 4 — remboursement comptabilisé « normalement », journal = TRANSIT
        # destination : _prepare_payment_move débite alors 302000 destination, qui
        # se solde contre l'étape 3. Cascade _allocate_to_installments inchangée.
        #
        # NB (décision Micka — cf. DECISIONS_transfert_inter_agence.md §4) :
        # microfinance.loan.payment.journal_id porte un domaine de VUE
        # [('type','in',('bank','cash'))] mais AUCUNE @api.constrains serveur.
        # L'affectation programmatique du journal TRANSIT (type 'general') passe
        # donc — c'est volontaire. Si un correctif futur ajoute une contrainte de
        # type sur ce champ, cette étape 4 cassera : le traiter consciemment ici.
        payment = self.env['microfinance.loan.payment'].sudo().create({
            'loan_id': self.loan_id.id,
            'amount': self.amount,
            'journal_id': transit_journal.id,
            'payment_date': fields.Date.context_today(self),
        })
        payment.action_post()

        mouvement = self.env['microfinance.caisse.mouvement'].sudo().create({
            'session_id': session.id,
            'type': 'transfert_entrant',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'loan_id': self.loan_id.id,
            'transfert_remboursement_id': self.id,
        })
        self.write({
            'state': 'valide',
            'session_destination_id': session.id,
            'reception_move_id': reception_move.id,
            'payment_id': payment.id,
            'caisse_mouvement_dest_id': mouvement.id,
            'cashier_destination_id': self.env.user.id,
        })
        return True

    # ==================================================================
    # Points d'entrée guichet (sous-lot D). Appelés par le composant OWL du
    # guichet et par l'assistant de confirmation. register_operation
    # (microfinance.caisse.mouvement) reste volontairement mono-agence : ces
    # méthodes-ci sont le chemin distinct du flux inter-agences.
    # ==================================================================
    @api.model
    def get_other_agency_client_loans(self, partner_id):
        """Crédits actionnables (actifs/en défaut, décaissés) d'un client d'une autre
        agence — sudo ciblé, retour minimal, pour alimenter le choix du crédit au
        guichet source avant ouverture de l'assistant de confirmation."""
        partner = self.env['res.partner'].sudo().browse(partner_id)
        loans = partner.microfinance_loan_ids.filtered(
            lambda l: l.state in ('active', 'defaulted') and l.disbursement_date)
        return [{
            'id': loan.id,
            'name': loan.name,
            'product': loan.product_id.name,
            'balance_total': loan.balance_total,
            'company_name': loan.company_id.name,
        } for loan in loans]

    @api.model
    def get_transfert_confirm_action(self, session_id, loan_id, amount):
        """Ouvre l'assistant de confirmation (récapitulatif avant encaissement). Les
        gardes détaillées sont dans register_transfert ; ici, juste de quoi refuser
        proprement AVANT d'ouvrir l'assistant."""
        session = self.env['microfinance.caisse.session'].browse(session_id)
        if not session.exists() or session.state != 'open':
            raise UserError(_("Aucune session de caisse ouverte."))
        loan = self.env['microfinance.loan'].sudo().browse(loan_id)
        if not loan.exists():
            raise UserError(_("Crédit introuvable."))
        if loan.company_id == session.company_id:
            raise UserError(_(
                "Ce crédit appartient à l'agence de la session : utilisez le remboursement "
                "crédit habituel, pas un transfert inter-agences."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfert de remboursement inter-agences'),
            'res_model': 'microfinance.transfert.confirm.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {
                'default_session_id': session_id,
                'default_loan_id': loan_id,
                'default_amount': amount,
                'default_partner_name': loan.partner_id.display_name,
                'default_partner_agency': loan.company_id.name,
                'default_loan_name': loan.name,
                'default_loan_balance': loan.balance_total,
            },
        }

    @api.model
    def register_transfert(self, session_id, loan_id, amount):
        """Chemin d'entrée SOURCE : crée le transfert et l'encaisse (étape 1).

        Ne passe PAS par microfinance.caisse.mouvement.register_operation, dont les
        gardes company_id == session.company_id restent volontairement mono-agence.
        """
        session = self.env['microfinance.caisse.session'].browse(session_id)
        if not session.exists() or session.state != 'open':
            raise UserError(_("Aucune session de caisse ouverte."))
        loan = self.env['microfinance.loan'].sudo().browse(loan_id)
        if not loan.exists():
            raise UserError(_("Crédit introuvable."))
        if loan.company_id == session.company_id:
            raise UserError(_(
                "Ce crédit appartient à l'agence de la session : utilisez le remboursement "
                "crédit habituel, pas un transfert inter-agences."))
        if loan.state not in ('active', 'defaulted') or not loan.disbursement_date:
            raise UserError(_("Ce crédit n'est pas dans un état permettant un remboursement."))
        if not amount or amount <= 0:
            raise UserError(_("Le montant remis doit être strictement positif."))
        # Garde surpaiement PRÉVENTIVE (cf. DECISIONS_transfert_inter_agence.md §3) : le
        # solde du crédit peut encore évoluer d'ici la validation destination si un autre
        # remboursement intervient entre-temps sur ce même crédit.
        if amount > loan.balance_total + 0.01:
            raise UserError(_(
                "Surpaiement interdit. Solde restant du crédit : %.2f") % loan.balance_total)

        transfert = self.create({
            'loan_id': loan.id,
            'session_id': session.id,
            'amount': amount,
        })
        transfert.action_encaisser()
        return {'transfert_id': transfert.id, 'transfer_code': transfert.transfer_code}

    # --- Onglet « Transfert » du guichet -------------------------------
    def _guichet_row(self):
        """Ligne formatée d'un transfert pour les listes du guichet (colonnes
        demandées : n° compte crédit, n° dossier, client, date, agence, montant).

        Lecture EN SUDO. Un transfert est, par nature, à cheval sur deux agences :
        selon la vue qui appelle,
          - vue SOURCE : partner_id (société = agence destination) et
            destination_company_id sont HORS du périmètre multi-société du caissier
            source ; sans sudo, self.partner_id.display_name lève AccessError
            (base.res_partner_rule) ;
          - vue DESTINATION : source_company_id est l'agence d'en face.
        Le sudo est circonscrit à ce formateur en lecture seule ; il n'expose que
        les colonnes de la liste, sur des enregistrements DÉJÀ filtrés par
        source_company_id / destination_company_id dans la méthode appelante
        (get_transfert_source_data / _destination_data) — aucun élargissement de
        périmètre. Même principe que search_other_agency_clients et _post_transfer_move.
        """
        self.ensure_one()
        rec = self.sudo()
        loan = rec.loan_id
        return {
            'id': rec.id,
            'transfer_code': rec.transfer_code,
            'loan_account': loan.loan_account_id.name or '',
            'loan_name': loan.name,
            'partner': rec.partner_id.display_name,
            'date': rec.date_encaissement,
            'source': rec.source_company_id.name,
            'destination': rec.destination_company_id.name,
            'amount': rec.amount,
            'lot_id': rec.lot_id.id,
            'lot_reference': rec.lot_id.reference,
        }

    @api.model
    def get_transfert_source_data(self, session_id):
        """Vue SOURCE de l'onglet « Transfert » : transferts encaissés mais pas encore
        lotis, + lots en brouillon de l'agence courante."""
        session = self.env['microfinance.caisse.session'].browse(session_id)
        company = session.company_id
        pending = self.search([
            ('source_company_id', '=', company.id),
            ('state', '=', 'en_attente'),
            ('lot_id', '=', False),
        ])
        lots = self.env['microfinance.transfert.lot'].search([
            ('source_company_id', '=', company.id), ('state', '=', 'brouillon'),
        ])
        # sudo : destination_company_id de chaque lot est l'agence d'en face, hors
        # périmètre du caissier source (cf. _guichet_row). Lots déjà filtrés sur
        # source_company_id ci-dessus — pas d'élargissement.
        return {
            'pending': [t._guichet_row() for t in pending],
            'draft_lots': [{
                'id': lot.id,
                'reference': lot.reference,
                'destination': lot.destination_company_id.name,
                'coursier': lot.coursier_id.display_name or '',
                'count': len(lot.transfert_ids),
                'total': lot.montant_total,
                'transfer_codes': lot.transfert_ids.mapped('transfer_code'),
            } for lot in lots.sudo()],
        }

    @api.model
    def get_transfert_destination_data(self, session_id):
        """Vue DESTINATION de l'onglet « Transfert » : transferts en transit dont
        l'agence courante est la destination — à valider à l'arrivée du coursier."""
        session = self.env['microfinance.caisse.session'].browse(session_id)
        company = session.company_id
        incoming = self.search([
            ('destination_company_id', '=', company.id),
            ('state', '=', 'en_transit'),
        ])
        return {'incoming': [t._guichet_row() for t in incoming]}

    @api.model
    def action_create_lot(self, session_id, transfert_ids, coursier_id):
        """Crée un lot de rapatriement à partir de transferts encaissés non lotis, tous
        de la même agence destination. Le lot reste en brouillon (sa validation =
        remise au coursier, étape 2)."""
        session = self.env['microfinance.caisse.session'].browse(session_id)
        transferts = self.browse(transfert_ids).exists()
        if not transferts:
            raise UserError(_("Sélectionnez au moins un transfert."))
        if any(t.source_company_id != session.company_id for t in transferts):
            raise UserError(_(
                "Tous les transferts d'un lot doivent avoir été encaissés par l'agence courante."))
        if any(t.state != 'en_attente' or t.lot_id for t in transferts):
            raise UserError(_(
                "Certains transferts sont déjà lotis ou ne sont plus « En attente »."))
        destinations = transferts.mapped('destination_company_id')
        if len(destinations) != 1:
            # sudo : les agences destination sont hors périmètre du caissier source.
            raise UserError(_(
                "Un lot ne regroupe que des transferts vers une même agence destination "
                "(destinations sélectionnées : %s).") % ', '.join(destinations.sudo().mapped('name')))
        if not coursier_id:
            raise UserError(_("Sélectionnez le coursier."))
        lot = self.env['microfinance.transfert.lot'].create({
            'source_company_id': session.company_id.id,
            'destination_company_id': destinations.id,
            'coursier_id': coursier_id,
        })
        transferts.write({'lot_id': lot.id})
        return {'lot_id': lot.id, 'reference': lot.reference}

    @api.model
    def validate_lot(self, lot_id):
        """Remise du lot au coursier (étape 2). Renvoie l'action d'impression du ticket."""
        lot = self.env['microfinance.transfert.lot'].browse(lot_id)
        lot.action_valider()
        return lot.action_print_ticket()

    @api.model
    def validate_transfert_destination(self, transfert_id, session_id):
        """Validation à l'arrivée du coursier (étapes 3 + 4)."""
        transfert = self.browse(transfert_id)
        transfert.action_valider_destination(session_id)
        return {
            'transfer_code': transfert.transfer_code,
            'payment': transfert.payment_id.name or '',
        }
