# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class MicrofinanceCaisseFicheJournee(models.Model):
    _name = 'microfinance.caisse.fiche.journee'
    _description = 'Fiche journalière de caisse'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, journal_id'

    journal_id = fields.Many2one(
        'account.journal', string='Journal de caisse', required=True, tracking=True,
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
        help="Limité aux journaux de type 'Espèces' : la fiche journalière/clôture du jour est "
             "un rituel de caisse physique (à la LPF), pas un rapprochement bancaire.",
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    state = fields.Selection([
        ('open', 'Ouverte'),
        ('closed', 'Clôturée'),
    ], string='État', default='open', required=True, tracking=True)
    reopen_reason = fields.Char(
        string='Motif de réouverture',
        help="À renseigner avant de cliquer sur « Rouvrir la journée » : consigné dans le suivi "
             "de la fiche (qui, quand, pourquoi), puis effacé après la réouverture.",
    )

    # Instantané figé, pas des champs `compute=` : calculés depuis account.move.line (aucun
    # montant recopié/dupliqué à la saisie) mais écrits une fois pour toutes par
    # _refresh_amounts(), pas réévalués automatiquement à chaque lecture. Tant que la fiche est
    # 'open', action_refresh() permet de les remettre à jour à la demande ; une fois 'closed',
    # plus aucune méthode de ce modèle ne les modifie (action_close_day, Lot 2, appellera
    # _refresh_amounts() une dernière fois juste avant de verrouiller l'état) : le solde figé
    # reste fiable même si des écritures (irrégulières) apparaissaient après coup sur le journal.
    opening_balance = fields.Monetary(
        string="Solde d'ouverture", readonly=True, copy=False,
        help="Solde de clôture de la dernière fiche clôturée précédente pour ce journal, ou "
             "solde comptable du compte du journal juste avant cette date si aucune fiche "
             "précédente n'a été clôturée. Figé au dernier rafraîchissement (création ou "
             "action_refresh()), pas recalculé à la volée.",
    )
    total_debit = fields.Monetary(string='Total débits du jour', readonly=True, copy=False)
    total_credit = fields.Monetary(string='Total crédits du jour', readonly=True, copy=False)
    closing_balance = fields.Monetary(
        string='Solde de clôture calculé', readonly=True, copy=False,
        help='opening_balance + total_debit - total_credit au moment du dernier '
             'rafraîchissement.',
    )
    is_stale = fields.Boolean(
        compute='_compute_is_stale', string='Solde à rafraîchir',
        help="Non stocké, recalculé à l'affichage : indique que le solde de clôture figé ne "
             "correspond plus au solde comptable réel (nouvelles écritures depuis le dernier "
             "rafraîchissement). Toujours faux une fois la fiche clôturée : action_close_day() "
             "rafraîchit et vérifie la cohérence avant de verrouiller l'état.",
    )

    _sql_constraints = [
        ('journal_date_unique', 'unique(journal_id, date)',
         'Une seule fiche journalière par journal et par jour.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._refresh_amounts()
        return records

    def action_refresh(self):
        for fiche in self:
            if fiche.state == 'closed':
                raise UserError(_(
                    "Cette fiche est clôturée : ses montants sont figés, ils ne peuvent plus "
                    "être rafraîchis. Utilisez la réouverture si une correction est nécessaire."
                ))
        self._refresh_amounts()

    def _get_account_balance_before(self, account, date):
        self.ensure_one()
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('date', '<', date),
            ('parent_state', '=', 'posted'),
        ])
        return sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

    def _refresh_amounts(self):
        """Calcule et écrit (une seule fois, pas de réévaluation automatique) l'instantané de la
        fiche depuis account.move.line. Le solde d'ouverture s'enchaîne sur la dernière fiche
        CLÔTURÉE (pas la plus récente tout court) pour ce journal ; à défaut, repli sur le solde
        comptable réel avant la date, qui reflète toujours la réalité même si des jours
        intermédiaires n'ont jamais été clôturés — la question de savoir si un jour non clôturé
        doit bloquer la clôture du suivant reste un point de conception distinct (Lot 2)."""
        for fiche in self:
            journal = fiche.journal_id
            account = journal.default_account_id
            if not journal or not account or not fiche.date:
                fiche.write({'opening_balance': 0.0, 'total_debit': 0.0, 'total_credit': 0.0, 'closing_balance': 0.0})
                continue
            previous_fiche = self.search([
                ('journal_id', '=', journal.id),
                ('date', '<', fiche.date),
                ('state', '=', 'closed'),
            ], order='date desc', limit=1)
            if previous_fiche:
                opening_balance = previous_fiche.closing_balance
            else:
                opening_balance = fiche._get_account_balance_before(account, fiche.date)
            lines = self.env['account.move.line'].search([
                ('account_id', '=', account.id),
                ('date', '=', fiche.date),
                ('parent_state', '=', 'posted'),
            ])
            total_debit = sum(lines.mapped('debit'))
            total_credit = sum(lines.mapped('credit'))
            fiche.write({
                'opening_balance': opening_balance,
                'total_debit': total_debit,
                'total_credit': total_credit,
                'closing_balance': opening_balance + total_debit - total_credit,
            })

    def _get_movement_lines(self):
        """Lignes détaillées du jour pour le rapport imprimable (Lot 5) : mêmes critères que
        _refresh_amounts (compte du journal, date exacte, écritures comptabilisées), pas de
        nouvelle requête ad hoc — ordonnées par écriture puis par id pour un ordre stable."""
        self.ensure_one()
        account = self.journal_id.default_account_id
        if not account:
            return self.env['account.move.line']
        return self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('date', '=', self.date),
            ('parent_state', '=', 'posted'),
        ], order='move_id, id')

    def _get_account_balance_as_of(self, account, date):
        self.ensure_one()
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('date', '<=', date),
            ('parent_state', '=', 'posted'),
        ])
        return sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

    def _compute_is_stale(self):
        for fiche in self:
            account = fiche.journal_id.default_account_id
            if fiche.state != 'open' or not account:
                fiche.is_stale = False
                continue
            live_balance = fiche._get_account_balance_as_of(account, fiche.date)
            fiche.is_stale = abs(live_balance - fiche.closing_balance) > 0.01

    def action_close_day(self):
        """Séquentialité stricte façon LPF : le jour précédent (même journal), s'il existe une
        fiche pour ce jour, doit déjà être clôturé — sinon blocage. S'il n'existe AUCUNE fiche
        pour le jour précédent (jamais créée), rien ne bloque : cette absence n'est pas traitée
        comme un jour non clôturé, cohérent avec le repli déjà testé au Lot 1 (le solde
        d'ouverture reflète toujours la réalité comptable, avec ou sans fiche intermédiaire)."""
        for fiche in self:
            if fiche.state == 'closed':
                continue
            previous_open_fiche = self.search([
                ('journal_id', '=', fiche.journal_id.id),
                ('date', '<', fiche.date),
                ('state', '=', 'open'),
            ], limit=1)
            if previous_open_fiche:
                raise UserError(_(
                    "Impossible de clôturer le %(date)s : la fiche du %(prev_date)s (même "
                    "journal) n'est pas encore clôturée. Les journées doivent être clôturées "
                    "dans l'ordre chronologique."
                ) % {'date': fiche.date, 'prev_date': previous_open_fiche.date})
            fiche._refresh_amounts()
            account = fiche.journal_id.default_account_id
            real_balance = fiche._get_account_balance_as_of(account, fiche.date) if account else fiche.closing_balance
            if abs(real_balance - fiche.closing_balance) > 0.01:
                raise UserError(_(
                    'Écart détecté : le solde de clôture calculé (%(calc).2f) ne correspond pas '
                    'au solde comptable réel du journal à cette date (%(real).2f). Clôture '
                    'refusée tant que cet écart persiste.'
                ) % {'calc': fiche.closing_balance, 'real': real_balance})
            fiche.write({'state': 'closed'})
            fiche.message_post(body=_('Journée clôturée par %s.') % self.env.user.name)

    @api.model
    def action_quick_close_today(self):
        """Action rapide depuis la vue liste (menu ⚙ Actions, sans sélection de ligne) :
        clôture la journée du jour pour l'agence courante (self.env.company), à condition qu'il
        n'existe qu'UN SEUL journal de caisse ('cash') pour cette société — sinon, ambiguïté sur
        « le » journal courant (aucun lien utilisateur → journal n'existe dans ce projet),
        renvoyée explicitement à l'utilisateur plutôt que devinée."""
        today = fields.Date.context_today(self)
        journals = self.env['account.journal'].search([
            ('type', '=', 'cash'), ('company_id', '=', self.env.company.id),
        ])
        if len(journals) != 1:
            raise UserError(_(
                "Plusieurs journaux de caisse (ou aucun) existent pour l'agence %(company)s : "
                "ouvrez la fiche du journal concerné individuellement plutôt que d'utiliser la "
                "clôture rapide."
            ) % {'company': self.env.company.name})
        journal = journals
        fiche = self.search([('journal_id', '=', journal.id), ('date', '=', today)], limit=1)
        if not fiche:
            fiche = self.create({'journal_id': journal.id, 'date': today})
        fiche.action_close_day()
        return True

    def action_reopen_day(self):
        if not self.env.user.has_group('microfinance_loan_management.group_microfinance_manager'):
            raise AccessError(_("Seul un manager peut rouvrir une journée de caisse clôturée."))
        for fiche in self:
            if fiche.state != 'closed':
                continue
            if not fiche.reopen_reason:
                raise UserError(_('Le motif de réouverture est requis avant de rouvrir cette fiche.'))
            fiche.message_post(body=_(
                'Journée rouverte par %(user)s. Motif : %(reason)s'
            ) % {'user': self.env.user.name, 'reason': fiche.reopen_reason})
            fiche.write({'state': 'open', 'reopen_reason': False})


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        FicheJournee = self.env['microfinance.caisse.fiche.journee']
        for move in self:
            if not move.journal_id or not move.date:
                continue
            closed_fiche = FicheJournee.search([
                ('journal_id', '=', move.journal_id.id),
                ('date', '=', move.date),
                ('state', '=', 'closed'),
            ], limit=1)
            if closed_fiche:
                raise UserError(_(
                    "Impossible de comptabiliser : la journée de caisse du %(date)s est "
                    "clôturée pour le journal « %(journal)s ». Un manager doit rouvrir la fiche "
                    "journalière (motif requis) pour autoriser cette écriture."
                ) % {'date': move.date, 'journal': move.journal_id.name})
        return super().action_post()
