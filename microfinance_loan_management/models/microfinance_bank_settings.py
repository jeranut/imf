# -*- coding: utf-8 -*-
"""Réglages du relevé bancaire papier : tolérance d'arrondi par société, comptes d'attente d'un journal, et champs
de pointage d'une ligne comptable déjà postée sur le compte de banque (sans créer d'écriture)."""
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    mf_bank_tolerance = fields.Monetary(
        string="Tolérance de rapprochement bancaire", currency_field='currency_id', default=0.0,
        help="Écart maximal accepté entre un virement du relevé et la ligne en attente qu'il solde (arrondi de "
             "virement). 0 = désactivée : un écart laisse un lettrage partiel. Activée, l'écart est soldé sur le "
             "compte de produit ou de charge du journal.")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mf_bank_tolerance = fields.Monetary(
        related='company_id.mf_bank_tolerance', readonly=False, currency_field='currency_id',
        string="Tolérance de rapprochement bancaire")


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    mf_pending_account_ids = fields.Many2many(
        'account.account', 'microfinance_journal_pending_account_rel', 'journal_id', 'account_id',
        string="Comptes d'attente supplémentaires", check_company=True,
        domain="[('company_id', '=', company_id), ('reconcile', '=', True)]",
        help="Comptes lettrables dont les lignes non lettrées peuvent être rapprochées avec une ligne de relevé de "
             "ce journal, en plus des comptes de paiement en suspens de ses modes de paiement (ex. chèques émis en "
             "attente).")

    def _mf_pending_accounts(self):
        """Comptes dont les lignes non lettrées sont candidates au rapprochement avec ce journal : comptes en
        suspens de ses modes de paiement (repli sur ceux de la société) et comptes supplémentaires réglés."""
        self.ensure_one()
        accounts = (self.inbound_payment_method_line_ids | self.outbound_payment_method_line_ids).payment_account_id
        company = self.company_id
        accounts |= company.account_journal_payment_debit_account_id | company.account_journal_payment_credit_account_id
        return (accounts | self.mf_pending_account_ids).filtered(lambda a: a.reconcile)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    mf_pointed_entry_id = fields.Many2one(
        'microfinance.bank.statement.entry', string='Pointée par la ligne de relevé', copy=False, readonly=True,
        index='btree_not_null', ondelete='set null',
        help="Ligne déjà postée directement sur le compte de banque et marquée comme vue sur le relevé, sans "
             "création d'écriture (évite de la compter deux fois).")
    mf_pointed_date = fields.Datetime(string='Date du pointage', copy=False, readonly=True)
    mf_pointed_user_id = fields.Many2one('res.users', string='Pointée par', copy=False, readonly=True)
