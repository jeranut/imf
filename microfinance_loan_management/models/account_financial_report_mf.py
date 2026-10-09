# -*- coding: utf-8 -*-
"""Bilan et Compte de résultat (base_accounting_kit) : passif et capitaux propres affichés en positif, lignes de
charges retrouvées par identifiant et non par leur nom traduit. Le module tiers n'est pas modifié."""
from odoo import api, models

KIT = 'base_accounting_kit.'
# Lignes du Bilan affichées en positif : PASSIF, ses sous-lignes, CAPITAUX PROPRES et ses sous-lignes. Un parent de type
# « sum » additionne les soldes BRUTS de ses enfants puis applique son propre signe : pas de double inversion.
LIABILITY_SIGN_XMLIDS = [
    'account_financial_report_liabilitysum0', 'account_financial_report_liability0',
    'account_financial_report_profitloss_toreport0', 'account_financial_report_liability_payable0',
    'account_financial_report_liability_current0', 'account_financial_report_liability_credit_card0',
    'account_financial_report_liability_non_current0', 'account_financial_report_equitysection0',
    'account_financial_report_equity0', 'account_financial_report_equity_unaffected0',
]
# Compte de résultat : les produits (crédit, solde brut négatif) s'affichent en positif avec le signe -1, comme la ligne
# PRODUIT (account_financial_report_income0, déjà à -1) ; les charges (débit, solde brut positif) avec le signe +1. Les
# parents « sum » additionnent les soldes bruts, le signe d'une ligne n'agit que sur son propre affichage : le résultat net
# (account_financial_report_profitandloss0 = −(produits + charges bruts)) ne change pas.
PROFIT_LOSS_SIGNS = {
    'financial_report_gross_profit': '-1',                         # Marge brute
    'account_financial_report_other_income0': '-1',               # Autres produits
    'account_financial_report_operating_income0': '-1',           # Produits d'exploitation
    'account_financial_report_expense0': '1',                     # CHARGE
    'financial_report_cost_of_revenue': '1',
    'account_financial_report_expense_regular0': '1',
    'account_financial_report_expense_depreciation0': '1',
}
# Types de comptes sommés par ligne (identifiant de la ligne), quand ils dépassent le type de la ligne.
EXPENSE_TYPES = ['expense', 'expense_depreciation', 'expense_direct_cost']
ACCOUNT_TYPES_BY_XMLID = {
    'account_financial_report_expense_regular0': EXPENSE_TYPES,           # Charges d'exploitation (comme avant)
    'account_financial_report_expense0': ['expense', 'expense_depreciation'],  # total des charges du résultat
}


class AccountFinancialReport(models.Model):
    _inherit = 'account.financial.report'

    @api.model
    def _mf_apply_liability_signs(self, dry_run=False):
        """Idempotent : met sign = -1 sur les lignes du passif et des capitaux propres. Lignes retrouvées par xmlid.
        Retourne les identifiants modifiés (ou à modifier en dry_run)."""
        changed = []
        for xmlid in LIABILITY_SIGN_XMLIDS:
            report = self.env.ref(KIT + xmlid, raise_if_not_found=False)
            if report and report.sign != '-1':
                changed.append(report.id)
                if not dry_run:
                    report.sign = '-1'
        return changed

    @api.model
    def _mf_apply_profit_loss_signs(self, dry_run=False):
        """Idempotent : produits positifs (-1) et charges positives (+1) dans le Compte de résultat. Lignes retrouvées
        par xmlid, jamais par nom traduit. Retourne [(xmlid, ancien, nouveau)] des lignes modifiées (ou à modifier)."""
        changed = []
        for xmlid, sign in PROFIT_LOSS_SIGNS.items():
            report = self.env.ref(KIT + xmlid, raise_if_not_found=False)
            if report and report.sign != sign:
                changed.append((xmlid, report.sign, sign))
                if not dry_run:
                    report.sign = sign
        return changed


class FinancialReport(models.TransientModel):
    _inherit = 'financial.report'

    def _mf_types_by_report(self):
        mapping = {}
        for xmlid, types in ACCOUNT_TYPES_BY_XMLID.items():
            report = self.env.ref(KIT + xmlid, raise_if_not_found=False)
            if report:
                mapping[report.id] = types
        return mapping

    def _compute_report_balance(self, reports):
        """Même calcul que le module tiers, sauf pour les lignes par type de compte : les types sommés viennent de
        l'identifiant de la ligne, jamais de son nom (traduit)."""
        typed = reports.filtered(lambda r: r.type == 'account_type')
        res = super()._compute_report_balance(reports - typed) if reports - typed else {}
        by_report = self._mf_types_by_report()
        fields_ = ['credit', 'debit', 'balance']
        for report in typed:
            if report.id in res:
                continue
            types = by_report.get(report.id) or [report.account_type_ids]
            accounts = self.env['account.account'].search([('account_type', 'in', types)])
            res[report.id] = dict((fn, 0.0) for fn in fields_)
            res[report.id]['account'] = self._compute_account_balance(accounts)
            for value in res[report.id]['account'].values():
                for fn in fields_:
                    res[report.id][fn] += value.get(fn)
        return res
