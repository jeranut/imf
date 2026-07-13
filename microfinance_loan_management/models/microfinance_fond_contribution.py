# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceFondContribution(models.Model):
    _name = 'microfinance.fond.contribution'
    _description = 'Contribution bailleur sur fonds de crédit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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
        ('especes', 'Espèces'),
        ('cheque', 'Chèque'),
        ('virement', 'Virement'),
    ], string='Mode de paiement', required=True, tracking=True)
    journal_id = fields.Many2one(
        'account.journal', string='Journal bancaire',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', saisie_company_id)]",
        help="Requis si le mode de paiement est chèque ou virement. Filtré sur l'agence de "
             "saisie (saisie_company_id), pas sur company_id : pour un fonds « Multi-agences », "
             "company_id est vide alors que saisie_company_id est toujours renseigné.",
    )
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
    ], string='État', default='draft', required=True, tracking=True, copy=False)

    def write(self, vals):
        if self.ids and 'saisie_company_id' in vals:
            for contrib in self:
                if vals['saisie_company_id'] != contrib.saisie_company_id.id:
                    raise UserError(_(
                        "L'agence de saisie ne peut pas être modifiée après la création de la contribution."
                    ))
        return super().write(vals)

    @api.constrains('mode_paiement', 'journal_id')
    def _check_journal_required(self):
        for contrib in self:
            if contrib.mode_paiement in ('cheque', 'virement') and not contrib.journal_id:
                raise ValidationError(_(
                    'Le journal bancaire est requis pour un mode de paiement par chèque ou virement.'
                ))

    @api.constrains('amount')
    def _check_amount(self):
        for contrib in self:
            if contrib.amount <= 0:
                raise ValidationError(_('Le montant de la contribution doit être strictement positif.'))

    def _prepare_contribution_move(self):
        """Squelette identique à MicrofinanceLoan._prepare_disbursement_move() : un dict prêt
        pour account.move.create(), 2 lignes équilibrées. Un dépôt bailleur crédite le compte GL
        du fonds (fond_id.account_id) et débite le compte banque/caisse (journal_id.default_account_id) ;
        un retrait fait l'inverse."""
        self.ensure_one()
        fond = self.fond_id
        journal = self.journal_id
        if not journal or not journal.default_account_id:
            raise UserError(_(
                'Configurez le journal bancaire/caisse de la contribution (et son compte par défaut) '
                'avant de la valider.'
            ))
        if not fond.account_id:
            raise UserError(_('Configurez le compte comptable bailleur du fonds "%s".') % fond.name)
        label = _('Dépôt bailleur %s') % fond.name if self.type_mouvement == 'depot' else _('Retrait bailleur %s') % fond.name
        if self.type_mouvement == 'depot':
            line_ids = [
                (0, 0, {'name': label, 'account_id': journal.default_account_id.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': fond.account_id.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        else:
            line_ids = [
                (0, 0, {'name': label, 'account_id': fond.account_id.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': journal.default_account_id.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        return {
            'date': self.date,
            'journal_id': journal.id,
            'ref': _('%(label)s (%(desc)s)') % {'label': label, 'desc': self.description or fond.code},
            'microfinance_fond_contribution_id': self.id,
            'line_ids': line_ids,
        }

    def action_post(self):
        for contrib in self:
            if contrib.state == 'posted':
                raise UserError(_('Cette contribution est déjà validée.'))
            if contrib.fond_id.passer_gl:
                move = self.env['account.move'].create(contrib._prepare_contribution_move())
                move.action_post()
                contrib.move_id = move.id
            contrib.state = 'posted'
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'

    microfinance_fond_contribution_id = fields.Many2one(
        'microfinance.fond.contribution', string='Contribution bailleur', index=True, copy=False,
    )
