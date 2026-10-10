# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class MicrofinanceFondContribution(models.Model):
    _name = 'microfinance.fond.contribution'
    _description = 'Contribution bailleur sur fonds de crédit'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'microfinance.fond.parent.mixin']
    _order = 'date desc, id desc'

    fond_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit', required=True, tracking=True,
        ondelete='restrict',
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    type_mouvement = fields.Selection([
        ('depot', 'Dépôt'),
        ('retrait', 'Retrait'),
    ], string='Type de mouvement', required=True, tracking=True)
    amount = fields.Monetary(string='Montant', required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Devise', related='fond_id.currency_id', store=True, readonly=True,
    )
    mode_paiement = fields.Selection([
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
    ], string='Mode de paiement', required=True, tracking=True,
        help="Un fonds ne se reçoit (et ne se rembourse) que par la banque : virement ou chèque.")
    reference_paiement = fields.Char(
        string='Référence du virement / n° de chèque', tracking=True, copy=False,
        help="Reprise dans le libellé de l'écriture : sert au rapprochement avec la ligne du relevé "
             "bancaire. Obligatoire pour un fonds d'exploitation.")
    journal_id = fields.Many2one(
        'account.journal', string='Journal de fonds', compute='_compute_journal_id', store=True,
        readonly=True, check_company=False,
        help="Déduit du fonds (fond_id.fund_journal_id) : journal de fonds de la banque du fonds, dans "
             "la société du fonds. Jamais saisi.",
    )
    fond_bank_id = fields.Many2one(related='fond_id.bank_id', string='Banque du fonds', readonly=True)
    fond_origine = fields.Selection(
        related='fond_id.origine', string='Origine du fonds', readonly=False,
        help="Privé (compte 240xxx) ou public (compte 250xxx). Modifiable tant qu'aucune contribution du fonds "
             "n'est validée ; le compte dédié du fonds suit automatiquement.")
    fond_account_id = fields.Many2one(related='fond_id.account_id', string='Compte du fonds', readonly=True)
    fond_has_posted_contribution = fields.Boolean(related='fond_id.has_posted_contribution')
    description = fields.Char(string='Description / Référence bailleur')
    move_id = fields.Many2one(
        'account.move', string='Écriture comptable', readonly=True, copy=False,
        help="Généré par action_post() uniquement si fond_id.passer_gl est actif. Si passer_gl "
             "est désactivé (cas mutualiste), la contribution passe quand même en état 'posted' "
             "mais ce champ reste vide : seul l'historique du mouvement est conservé.",
    )
    company_id = fields.Many2one(
        'res.company', string='Société du fonds', related='fond_id.company_id', store=True, readonly=True,
        help="Vide si le fonds est « Multi-agences » (scope='multi_company') : ne pas confondre "
             "avec saisie_company_id, qui trace toujours la société ayant réellement effectué le "
             "mouvement.",
    )
    saisie_company_id = fields.Many2one(
        'res.company', string='Agence de saisie', required=True, default=lambda self: self.env.company,
        copy=False,
        help="Société ayant réellement effectué le mouvement, toujours renseignée (y compris pour "
             "un fonds « Agence unique », où elle sera alors identique à company_id). Figée après "
             "création.",
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('posted', 'Validé'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', required=True, tracking=True, copy=False)

    def _check_parent_only_shared(self):
        """Contributions d'un fonds partagé : saisies depuis la société mère uniquement. Les
        contributions des fonds legacy (agence unique) restent saisies par leur agence."""
        if any(contrib.fond_id.scope == 'multi_company' for contrib in self):
            self._check_parent_only()

    @api.model_create_multi
    def create(self, vals_list):
        fonds = self.env['microfinance.fond.credit'].browse([v['fond_id'] for v in vals_list if v.get('fond_id')])
        if any(fond.scope == 'multi_company' for fond in fonds):
            self._check_parent_only()
        for vals in vals_list:
            # Odoo ignorerait silencieusement la valeur d'un champ calculé en lecture seule à la création ;
            # on refuse explicitement un journal différent de celui du fonds.
            if vals.get('journal_id') and vals.get('fond_id'):
                expected = self.env['microfinance.fond.credit'].browse(vals['fond_id']).fund_journal_id
                if vals['journal_id'] != expected.id:
                    raise ValidationError(_(
                        "Le journal d'une contribution est imposé par le fonds (%s) ; il ne peut pas être choisi."
                    ) % (expected.display_name or _('aucun')))
        return super().create(vals_list)

    def unlink(self):
        self._check_parent_only_shared()
        return super().unlink()

    def write(self, vals):
        self._check_parent_only_shared()
        if self.ids and 'saisie_company_id' in vals:
            for contrib in self:
                if vals['saisie_company_id'] != contrib.saisie_company_id.id:
                    raise UserError(_(
                        "L'agence de saisie ne peut pas être modifiée après la création de la contribution."
                    ))
        return super().write(vals)

    @api.depends('fond_id.fund_journal_id')
    def _compute_journal_id(self):
        for contrib in self:
            contrib.journal_id = contrib.fond_id.fund_journal_id

    @api.constrains('journal_id', 'fond_id')
    def _check_journal_is_fund_journal(self):
        for contrib in self:
            expected = contrib.fond_id.fund_journal_id
            if contrib.journal_id and contrib.journal_id != expected:
                raise ValidationError(_(
                    "Le journal d'une contribution est imposé par le fonds (%(attendu)s) ; il ne peut pas être "
                    "remplacé par « %(journal)s »."
                ) % {'attendu': expected.display_name or _('aucun'), 'journal': contrib.journal_id.display_name})

    @api.constrains('amount')
    def _check_amount(self):
        for contrib in self:
            if contrib.amount <= 0:
                raise ValidationError(_('Le montant de la contribution doit être strictement positif.'))

    def _contribution_company(self):
        """Société de l'écriture : toujours celle du fonds (la société mère pour un fonds multi-agences),
        quelle que soit l'agence de saisie, qui reste tracée dans saisie_company_id."""
        self.ensure_one()
        return self.fond_id._fund_company()

    def _check_ready_to_post(self):
        self.ensure_one()
        fond = self.fond_id
        if self.amount <= 0:
            raise UserError(_('Le montant de la contribution doit être strictement positif.'))
        if not fond.passer_gl:
            return
        if not fond.bank_id:
            raise UserError(_(
                'Le fonds « %s » n\'a pas de banque : renseignez la banque du fonds avant de valider une contribution.'
            ) % fond.name)
        company = self._contribution_company()
        if not company:
            raise UserError(_('Société du fonds « %s » introuvable : désignez la société mère dans les paramètres.') % fond.name)
        journal = fond.fund_journal_id
        if not journal:
            raise UserError(_(
                'Aucun journal de fonds pour la banque « %(banque)s » dans la société « %(societe)s ».'
            ) % {'banque': fond.bank_id.name, 'societe': company.name})
        if self.journal_id != journal:
            raise UserError(_(
                'Le journal de la contribution (%(actuel)s) ne correspond pas au journal de fonds de la banque (%(attendu)s).'
            ) % {'actuel': self.journal_id.display_name or _('aucun'), 'attendu': journal.display_name})
        if journal.company_id != company:
            raise UserError(_('Le journal de fonds doit appartenir à la société du fonds (%s).') % company.name)
        direction = 'inbound' if self.type_mouvement == 'depot' else 'outbound'  # retrait et remboursement : sortant
        if not self.env['microfinance.fond.partage']._payment_account(journal, direction):
            raise UserError(_(
                "Le journal de fonds « %(journal)s » n'a pas de compte de paiement en suspens (%(sens)s)."
            ) % {'journal': journal.display_name, 'sens': _('entrant') if direction == 'inbound' else _('sortant')})
        counterpart = self._get_counterpart_account()
        if counterpart.company_id != company:
            raise UserError(_('Le compte du fonds « %s » doit appartenir à la société du fonds (%s).') % (fond.name, company.name))

    def _get_counterpart_account(self):
        """Compte de contrepartie de la contribution : compte dédié du fonds (dette envers le bailleur). Les
        fonds d'exploitation de nature subvention le remplacent par le compte de produit de la société."""
        self.ensure_one()
        fond = self.fond_id
        if not fond.account_id:
            raise UserError(_(
                'Le fonds "%s" n\'a pas de compte dédié : renseignez son origine (privé ou public) puis '
                'enregistrez-le pour créer son compte avant de valider une contribution.'
            ) % fond.name)
        return fond.account_id

    def _movement_label(self):
        self.ensure_one()
        code = self.fond_id.code
        label = _('Dépôt bailleur %s') % code if self.type_mouvement == 'depot' else _('Retrait bailleur %s') % code
        return ' - '.join(filter(None, [label, self.reference_paiement]))

    def _prepare_contribution_move(self):
        """Un dépôt bailleur débite le compte de paiement en suspens entrant du journal de fonds (139100) et
        crédite le compte dédié du fonds ; un retrait fait l'inverse avec le compte sortant (139500). La
        banque elle-même n'est touchée qu'au rapprochement du relevé, qui solde le compte en suspens."""
        self.ensure_one()
        fond = self.fond_id
        journal = self.journal_id
        Partage = self.env['microfinance.fond.partage']
        label = self._movement_label()
        counterpart = self._get_counterpart_account()
        if self.type_mouvement == 'depot':
            suspense = Partage._payment_account(journal, 'inbound')
            line_ids = [
                (0, 0, {'name': label, 'account_id': suspense.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': counterpart.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        else:
            suspense = Partage._payment_account(journal, 'outbound')
            line_ids = [
                (0, 0, {'name': label, 'account_id': counterpart.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': suspense.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        return {
            'date': self.date,
            'journal_id': journal.id,
            'ref': _('%(label)s (%(desc)s)') % {'label': label, 'desc': self.description or fond.code},
            'microfinance_fond_contribution_id': self.id,
            'line_ids': line_ids,
        }

    def _bank_received_amount(self):
        """Montant de la contribution dont la ligne en suspens est lettrée avec une ligne de relevé bancaire.
        Dépôt : ligne débitrice 139100 lettrée avec un relevé ; retrait (ou remboursement) : ligne créditrice 139500.
        Un lettrage avec une autre pièce (extourne) n'est jamais un relevé : il ne compte pas."""
        self.ensure_one()
        lines = self.move_id.sudo().line_ids
        if self.type_mouvement == 'depot':
            suspense = lines.filtered(lambda l: l.debit > 0)[:1]
            banked = sum(partial.amount for partial in suspense.matched_credit_ids
                         if partial.credit_move_id.move_id.statement_line_id)
        else:
            suspense = lines.filtered(lambda l: l.credit > 0)[:1]
            banked = sum(partial.amount for partial in suspense.matched_debit_ids
                         if partial.debit_move_id.move_id.statement_line_id)
        return min(banked, self.amount)

    def action_post(self):
        self._check_parent_only_shared()
        for contrib in self:
            if contrib.state == 'posted':
                raise UserError(_('Cette contribution est déjà validée.'))
            contrib._check_ready_to_post()
            if contrib.fond_id.passer_gl:
                company = contrib._contribution_company()
                Move = self.env['account.move'].sudo().with_company(company).with_context(allowed_company_ids=[company.id])
                move = Move.create(contrib._prepare_contribution_move())
                move.action_post()
                contrib.move_id = move.id
            contrib.state = 'posted'
        return True

    def action_cancel(self):
        """Annule une contribution validée : extourne de sa pièce (si elle existe) puis état « annulé ». Les
        contributions annulées ne comptent plus dans le solde du fonds. Refusée si la pièce est déjà
        rapprochée avec un relevé, ou si le fonds est déjà partagé au-delà de ce qui resterait."""
        self._check_parent_only_shared()
        for contrib in self:
            if contrib.state != 'posted':
                raise UserError(_('Seule une contribution validée peut être annulée.'))
            fond = contrib.fond_id
            if contrib.type_mouvement == 'depot' and \
                    float_compare(fond.reste_partageable, contrib.amount, precision_rounding=contrib.currency_id.rounding) < 0:
                raise UserError(_(
                    "Annulation impossible : le fonds « %s » est déjà partagé ou utilisé au-delà du solde restant. "
                    "Annulez d'abord les partages."
                ) % fond.name)
            move = contrib.move_id.sudo()
            if move:
                if move.line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids):
                    raise UserError(_(
                        "Annulation impossible : l'écriture de cette contribution est déjà rapprochée avec un relevé."))
                move.with_company(move.company_id).with_context(allowed_company_ids=[move.company_id.id])._reverse_moves([{
                    'date': fields.Date.context_today(self),
                    'ref': _('Extourne %s') % (move.ref or move.name),
                    'microfinance_fond_contribution_id': contrib.id,
                }], cancel=True)
            contrib.state = 'cancelled'
            contrib.message_post(body=_('Contribution annulée (écriture extournée).'))
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'

    microfinance_fond_contribution_id = fields.Many2one(
        'microfinance.fond.contribution', string='Contribution bailleur', index=True, copy=False,
    )
