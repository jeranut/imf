# -*- coding: utf-8 -*-
"""Mixin de test : les paramètres de cotisation n'ont aucune valeur avant le
2026-10-01 (le SME n'est semé qu'à cette date). Les tests dont les bulletins
sont datés avant ajoutent ici une ligne de test, créée dans la transaction du
test uniquement (jamais semée en base)."""


class MowgliSmeTestMixin:

    def _mowgli_add_test_sme(self, value=250000.0, date_from='2026-01-01'):
        Param = self.env['mowgli.payroll.param'].sudo()
        line = Param.search([('code', '=', 'SME'), ('date_from', '=', date_from),
                             ('company_id', '=', False)], limit=1)
        if line:
            line.value = value
        else:
            Param.create({'code': 'SME', 'value': value, 'date_from': date_from,
                          'note': "Ligne de test"})

    def _mowgli_legacy_accounts(self, company):
        """Dispositions comptables historiques (tout le crédit sur 315000, aucun
        compte sur les parts patronales) pour les tests écrits avant la
        configuration par société de mowgli_payroll_accounts : ils restent ainsi
        indépendants des comptes réellement configurés dans la base."""
        credit = self.env['account.account'].sudo().search(
            [('code', '=', '315000'), ('company_id', '=', company.id)], limit=1)
        structure = self.env['hr.payroll.structure'].sudo().search(
            [('code', '=', 'BASE')], limit=1)
        for rule in structure.rule_ids.sudo().with_company(company):
            if rule.code in ('CNAPS', 'OSTIE', 'IRSA', 'NET') and credit:
                rule.write({'credit_account_id': credit.id})
            elif rule.code in ('CNAPS_ER', 'OSTIE_ER'):
                rule.write({'debit_account_id': False, 'credit_account_id': False})
