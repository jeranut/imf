# -*- coding: utf-8 -*-
import logging

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

DEFAULT_HOLDER_ACCOUNT_PREFIX = 'CE'


class MicrofinanceSavingsHolderAccount(models.Model):
    """Compte épargne d'un client dans une agence : regroupe ses produits d'épargne souscrits
    (microfinance.savings.account). Couplé au compte crédit (microfinance.loan.account) du même
    client et de la même agence : même N, créés ensemble, nom dérivé du nom du compte crédit."""
    _name = 'microfinance.savings.holder.account'
    _description = 'Compte épargne'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'company_id, name'

    name = fields.Char(string='Numéro de compte', required=True, readonly=True, copy=False, index=True)
    legacy_number = fields.Char(
        string='Ancien numéro', readonly=True, copy=False, index=True,
        help="Numéro de l'ancien conteneur épargne (ex. AD/I/000002), conservé pour retrouver les "
             "documents et écritures antérieurs à la scission compte / produit.")
    partner_id = fields.Many2one('res.partner', string='Titulaire', required=True, readonly=True, index=True)
    company_id = fields.Many2one('res.company', string='Agence', required=True, readonly=True, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    loan_account_id = fields.Many2one(
        'microfinance.loan.account', string='Compte crédit', readonly=True, index=True,
        help="Compte crédit du même client dans la même agence : source du N de ce compte.")
    product_ids = fields.One2many('microfinance.savings.account', 'account_id', string="Produits d'épargne")
    product_count = fields.Integer(string='Nombre de produits', compute='_compute_totals', store=True)
    active_product_count = fields.Integer(string='Produits actifs', compute='_compute_totals', store=True)
    balance_total = fields.Monetary(
        string='Solde total', compute='_compute_totals', store=True,
        help="Somme des soldes des produits non clôturés de ce compte.")
    state = fields.Selection([
        ('open', 'Ouvert'),
        ('active', 'Actif'),
        ('dormant', 'Dormant'),
        ('closed', 'Clôturé'),
    ], string='État', compute='_compute_totals', store=True, index=True, tracking=True,
        help="Calculé à partir des produits : Actif dès qu'un produit est actif ; Dormant si un "
             "produit est dormant et aucun actif ; Clôturé si tous les produits sont clôturés ; "
             "Ouvert sinon (y compris sans produit). Jamais saisi.")
    next_rank = fields.Integer(
        string='Prochain rang', default=1, readonly=True, copy=False,
        help="Rang du prochain produit souscrit. Ne décroît jamais : un rang n'est jamais réutilisé.")

    _sql_constraints = [
        ('partner_company_unique', 'unique(partner_id, company_id)',
         "Un client ne peut avoir qu'un seul compte épargne par agence."),
        ('name_unique', 'unique(name)', "Ce numéro de compte épargne existe déjà."),
    ]

    @api.depends('product_ids.balance', 'product_ids.state')
    def _compute_totals(self):
        for account in self:
            products = account.product_ids
            open_products = products.filtered(lambda p: p.state != 'closed')
            states = set(products.mapped('state'))
            account.product_count = len(products)
            account.active_product_count = len(products.filtered(lambda p: p.state == 'active'))
            account.balance_total = sum(open_products.mapped('balance'))
            if 'active' in states:
                account.state = 'active'
            elif 'dormant' in states:
                account.state = 'dormant'
            elif products and states == {'closed'}:
                account.state = 'closed'
            else:
                account.state = 'open'

    @api.constrains('partner_id', 'company_id', 'loan_account_id')
    def _check_coherence(self):
        for account in self:
            partner_company = account.partner_id.company_id
            if partner_company and partner_company != account.company_id:
                raise ValidationError(_(
                    "Le compte épargne %(name)s doit appartenir à l'agence du titulaire (%(company)s)."
                ) % {'name': account.name, 'company': partner_company.display_name})
            loan_account = account.loan_account_id
            if loan_account and (loan_account.partner_id != account.partner_id
                                 or loan_account.company_id != account.company_id):
                raise ValidationError(_(
                    "Le compte épargne %(name)s et le compte crédit %(loan)s doivent avoir le même "
                    "titulaire et la même agence."
                ) % {'name': account.name, 'loan': loan_account.name})

    @api.model
    def _get_name_prefix(self, company):
        return (company.savings_holder_account_prefix or DEFAULT_HOLDER_ACCOUNT_PREFIX).strip('/ ')

    @api.model
    def _name_from_loan_account(self, loan_account):
        return '%s/%s' % (self._get_name_prefix(loan_account.company_id), loan_account.name)

    @api.model
    def _get_or_create_for(self, partner, company):
        """Compte épargne de (partner, company), créé avec son compte crédit s'il manque (même
        transaction, même N). Idempotent, sûr en concurrence (contraintes uniques + savepoint)."""
        partner.ensure_one()
        Holder = self.sudo()
        domain = [('partner_id', '=', partner.id), ('company_id', '=', company.id)]
        existing = Holder.search(domain, limit=1)
        if existing:
            return self.browse(existing.id)
        LoanAccount = self.env['microfinance.loan.account'].sudo()
        loan_account = LoanAccount.search(domain, limit=1) or LoanAccount.create(
            {'partner_id': partner.id, 'company_id': company.id})
        try:
            with self.env.cr.savepoint():
                holder = Holder.create({
                    'partner_id': partner.id,
                    'company_id': company.id,
                    'loan_account_id': loan_account.id,
                    'name': self._name_from_loan_account(loan_account),
                })
        except psycopg2.IntegrityError:
            existing = Holder.search(domain, limit=1)
            if not existing:
                raise
            holder = existing
        return self.browse(holder.id)

    def _reserve_rank(self):
        """Rang du prochain produit, sous verrou de ligne : deux souscriptions simultanées sur le
        même compte s'attendent, aucun rang ne sort deux fois."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT next_rank FROM microfinance_savings_holder_account WHERE id = %s FOR UPDATE", [self.id])
        rank = self.env.cr.fetchone()[0] or 1
        self.env.cr.execute(
            "UPDATE microfinance_savings_holder_account SET next_rank = %s WHERE id = %s", [rank + 1, self.id])
        self.invalidate_recordset(['next_rank'])
        return rank

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Produits d'épargne"),
            'res_model': 'microfinance.savings.account',
            'view_mode': 'tree,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_partner_id': self.partner_id.id, 'default_company_id': self.company_id.id},
        }

    # --- Contrôle d'intégrité compte crédit <-> compte épargne ---
    @api.model
    def get_credit_savings_sync_issues(self):
        """Écarts de synchronisation, sans rien corriger : compte crédit sans compte épargne,
        compte épargne sans compte crédit, N différents. Toutes agences visibles en sudo."""
        Holder = self.sudo().with_context(active_test=False)
        LoanAccount = self.env['microfinance.loan.account'].sudo()
        holders = {(h.partner_id.id, h.company_id.id): h for h in Holder.search([])}
        issues = []
        for loan_account in LoanAccount.search([]):
            key = (loan_account.partner_id.id, loan_account.company_id.id)
            holder = holders.pop(key, None)
            if not holder:
                issues.append(self._sync_issue('missing_savings', loan_account.partner_id, loan_account.company_id,
                                               loan_account.name, False))
            elif holder.name != self._name_from_loan_account(loan_account):
                issues.append(self._sync_issue('number_mismatch', holder.partner_id, holder.company_id,
                                               loan_account.name, holder.name))
        for holder in holders.values():
            issues.append(self._sync_issue('missing_credit', holder.partner_id, holder.company_id, False, holder.name))
        return issues

    @api.model
    def _sync_issue(self, kind, partner, company, loan_name, holder_name):
        labels = {
            'missing_savings': _('Compte crédit sans compte épargne'),
            'missing_credit': _('Compte épargne sans compte crédit'),
            'number_mismatch': _('Numéros différents'),
        }
        return {
            'kind': kind, 'label': labels[kind], 'partner_id': partner.id, 'partner_name': partner.display_name,
            'company_id': company.id, 'company_name': company.display_name,
            'loan_account_name': loan_name or '', 'holder_account_name': holder_name or '',
        }

    @api.model
    def cron_check_credit_savings_sync(self):
        issues = self.get_credit_savings_sync_issues()
        for issue in issues:
            _logger.warning("Synchro compte crédit / épargne : %(label)s — %(partner_name)s (%(company_name)s) "
                            "crédit=%(loan_account_name)s épargne=%(holder_account_name)s", issue)
        _logger.info("Synchro compte crédit / épargne : %s écart(s) détecté(s), aucun corrigé.", len(issues))
        return len(issues)

    def action_open_sync_check(self):
        return self.env['microfinance.savings.sync.issue'].action_refresh()

    def unlink(self):
        if self.mapped('product_ids'):
            raise UserError(_("Un compte épargne qui porte des produits ne peut pas être supprimé."))
        return super().unlink()


class MicrofinanceSavingsSyncIssue(models.TransientModel):
    _name = 'microfinance.savings.sync.issue'
    _description = 'Écart de synchronisation compte crédit / compte épargne'
    _order = 'company_id, partner_id'

    kind = fields.Selection([
        ('missing_savings', 'Compte crédit sans compte épargne'),
        ('missing_credit', 'Compte épargne sans compte crédit'),
        ('number_mismatch', 'Numéros différents'),
    ], string='Écart', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Client', readonly=True)
    company_id = fields.Many2one('res.company', string='Agence', readonly=True)
    loan_account_name = fields.Char(string='Compte crédit', readonly=True)
    holder_account_name = fields.Char(string='Compte épargne', readonly=True)

    @api.model
    def action_refresh(self):
        self.search([('create_uid', '=', self.env.uid)]).unlink()
        issues = self.env['microfinance.savings.holder.account'].get_credit_savings_sync_issues()
        records = self.create([{
            'kind': issue['kind'], 'partner_id': issue['partner_id'], 'company_id': issue['company_id'],
            'loan_account_name': issue['loan_account_name'], 'holder_account_name': issue['holder_account_name'],
        } for issue in issues])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contrôle de synchronisation crédit / épargne'),
            'res_model': self._name,
            'view_mode': 'tree',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }
