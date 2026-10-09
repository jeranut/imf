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

# Bilan : le résultat de l'exercice appartient aux capitaux propres. Un parent « sum » additionne les soldes bruts de ses
# enfants : déplacer la ligne d'un parent à l'autre (même signe -1) retire son montant du PASSIF et l'ajoute aux CAPITAUX
# PROPRES, sans le compter deux fois.
RESULT_LINE_XMLID = 'account_financial_report_profitloss_toreport0'
EQUITY_SECTION_XMLID = 'account_financial_report_equitysection0'
RESULT_LINE_SEQUENCE = 3       # après « Capital et réserves » (1) et « Résultat non affecté » (2)
# Libellés en double dans le Bilan (le contrôleur tiers traduit « Liability » en PASSIF et « Current Assets » en
# « Actifs circulants » pour les lignes parentes comme pour les sous-lignes) : seules les sous-lignes sont renommées.
BALANCE_SHEET_RENAMES = {
    'account_financial_report_liability0': 'Dettes',
    'account_financial_report_asset_current0': 'Autres actifs circulants',
}
NET_PROFIT_XMLID = 'financial_report_net_profit'
NET_PROFIT_NAME = 'Résultat net'
REPORT_LANGS = ('en_US', 'fr_FR', 'fr_BE')


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

    @api.model
    def _mf_apply_result_under_equity(self, dry_run=False):
        """Idempotent : « Résultat de l'exercice » devient une ligne des CAPITAUX PROPRES (et non du PASSIF). Lignes
        retrouvées par xmlid. Retourne [(xmlid, ancien parent, nouveau parent)] si la ligne est déplacée."""
        result = self.env.ref(KIT + RESULT_LINE_XMLID, raise_if_not_found=False)
        equity = self.env.ref(KIT + EQUITY_SECTION_XMLID, raise_if_not_found=False)
        if not result or not equity or result.parent_id == equity:
            return []
        changed = [(RESULT_LINE_XMLID, result.parent_id.id, equity.id)]
        if not dry_run:
            result.write({'parent_id': equity.id, 'sequence': RESULT_LINE_SEQUENCE})
        return changed

    def _mf_set_name(self, name, langs=REPORT_LANGS):
        """Écrit le libellé dans chaque langue où il diffère. Retourne True si une langue a changé."""
        changed = False
        for lang in langs:
            if lang != 'en_US' and not self.env['res.lang']._lang_get(lang):
                continue
            if self.with_context(lang=lang).name != name:
                self.with_context(lang=lang).name = name
                changed = True
        return changed

    @api.model
    def _mf_apply_balance_sheet_names(self, dry_run=False):
        """Idempotent : renomme les sous-lignes « PASSIF » en « Dettes » et « Actifs circulants » en « Autres actifs
        circulants ». Lignes retrouvées par xmlid ; les lignes parentes ne sont pas touchées. Retourne les xmlid
        renommés (ou à renommer)."""
        changed = []
        for xmlid, name in BALANCE_SHEET_RENAMES.items():
            report = self.env.ref(KIT + xmlid, raise_if_not_found=False)
            if not report:
                continue
            if any(report.with_context(lang=lang).name != name for lang in REPORT_LANGS
                   if lang == 'en_US' or self.env['res.lang']._lang_get(lang)):
                changed.append(xmlid)
                if not dry_run:
                    report._mf_set_name(name)
        return changed

    @api.model
    def _mf_apply_net_profit_line(self, dry_run=False):
        """Idempotent : ligne « Résultat net » (produits − charges, positive pour un bénéfice) du Compte de résultat.
        Valeur du rapport racine (account_financial_report_profitandloss0) ; placée sous CHARGE, dont le calcul est
        par type de compte et ignore ses enfants : le total des charges, des produits et du résultat ne change pas, et
        la ligne n'est pas un enfant de la racine (pas de récursion). Retrouvée par xmlid. Retourne True si créée."""
        xmlid = 'microfinance_loan_management.' + NET_PROFIT_XMLID
        existing = self.env.ref(xmlid, raise_if_not_found=False)
        root = self.env.ref(KIT + 'account_financial_report_profitandloss0', raise_if_not_found=False)
        expense = self.env.ref(KIT + 'account_financial_report_expense0', raise_if_not_found=False)
        if existing or not root or not expense:
            return False
        if not dry_run:
            line = self.create({
                'name': NET_PROFIT_NAME, 'parent_id': expense.id, 'sequence': 3, 'type': 'account_report',
                'account_report_id': root.id, 'sign': '-1', 'display_detail': 'no_detail'})
            line._mf_set_name(NET_PROFIT_NAME)
            self.env['ir.model.data'].create({
                'module': 'microfinance_loan_management', 'name': NET_PROFIT_XMLID, 'model': self._name,
                'res_id': line.id, 'noupdate': True})
        return True


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
