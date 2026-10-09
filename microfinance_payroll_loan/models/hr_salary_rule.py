# -*- coding: utf-8 -*-
from odoo import api, models

# Catégorie DED ("Retenue") : même catégorie que CNAPS/OSTIE/IRSA, pour que le montant
# entre dans categories.DED (donc dans NET = GROSS + categories.DED) sans jamais entrer
# dans NETIMP (déjà calculée par la règle NETIMP, qui s'exécute avant IRSA) ni dans IRSA
# elle-même (IRSA lit NETIMP, pas categories.DED).
#
# payslip.dict : la classe Payslips de hr_payroll_community._get_payslip_lines() enveloppe
# le recordset hr.payslip réel dans l'attribut `dict` (BrowsableObject.__init__(employee_id,
# dict, env)) — accessible tel quel (recherche d'attribut Python normale, pas interceptée par
# le __getattr__ de BrowsableObject qui ne sert qu'aux noms absents de l'objet). C'est le seul
# moyen d'atteindre le bulletin réel (date_to, company_id) depuis le code python d'une règle,
# sans modifier hr_payroll_community.
LOAN_CODE = (
    "due = payslip.dict._get_microfinance_loan_due_amount()\n"
    "net_avant_pret = GROSS + CNAPS + OSTIE + IRSA\n"
    "retenue = min(due, max(net_avant_pret, 0.0))\n"
    "result = -retenue if retenue > 0.01 else 0.0"
)

# Visibilité paie (D) : condition_select='python' plutôt que 'none', pour qu'AUCUNE ligne LOAN
# ne soit créée quand rien n'est dû (ex. employé sans prêt) — jusqu'ici 'none' forçait une ligne
# à 0,00 sur tout bulletin, même sans prêt (audit 2026-10-05). NET (= GROSS + categories.DED,
# hr_payroll_community/models/hr_payslip.py) et la synchro
# (hr_payslip.py:_microfinance_apply_salary_deduction, `abs(loan_line.total) if loan_line else
# 0.0`) sont tous les deux déjà sûrs vis-à-vis d'une ligne ABSENTE : une ligne manquante
# contribue 0 à categories.DED (recordset vide, pas de ligne à sommer) exactement comme une
# ligne à 0,00 l'aurait fait, et la synchro gère déjà explicitement `if loan_line else 0.0`.
LOAN_CONDITION_CODE = (
    "result = payslip.dict._get_microfinance_loan_due_amount() > 0.01"
)


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    @api.model
    def _microfinance_payroll_setup_loan_rule(self):
        """Crée (ou met à jour) la règle LOAN « Remboursement prêt » sur la structure BASE,
        même patron idempotent que mowgli_payroll_pcec._mowgli_setup_payroll_rules (recherche
        par code avant create/write, jamais de doublon). Ne touche à aucun fichier de
        mowgli_payroll_pcec : règle entièrement possédée par ce module.

        Séquence : à mi-chemin entre IRSA et NET (valeurs réelles observées sur la structure
        BASE : IRSA=800, NET=900 sur cette instance — pas les 130/200 d'un gabarit générique),
        recalculée dynamiquement pour rester correcte si ces séquences changent.

        Règle PARTAGÉE (company_id vide). Ne crée ni ne renomme aucun compte : le 315000 de
        chaque société ayant un plan est résolu par code et renseigné PAR SOCIÉTÉ, sans jamais
        écraser une valeur déjà saisie (mowgli_payroll_pcec._mowgli_setup_rule_accounts)."""
        if self._mowgli_migration_pending():
            return
        structure = self.env['hr.payroll.structure'].search([('code', '=', 'BASE')], limit=1)
        if not structure:
            return
        rules_by_code = {rule.code: rule for rule in structure.rule_ids}
        irsa = rules_by_code.get('IRSA')
        net = rules_by_code.get('NET')
        if not irsa or not net:
            # _mowgli_setup_payroll_rules n'a pas encore tourné (ordre de dépendance des
            # modules) : rien à faire, sera repris au prochain démarrage/mise à jour.
            return
        category = self.env['hr.salary.rule.category'].search([('code', '=', 'DED')], limit=1)
        sequence = (irsa.sequence + net.sequence) // 2

        # Règle PARTAGÉE : company_id jamais écrit. Le compte de crédit (315000)
        # est renseigné PAR SOCIÉTÉ, sans jamais écraser une valeur saisie.
        vals = {
            'name': 'Remboursement prêt',
            'code': 'LOAN',
            'sequence': sequence,
            'category_id': category.id,
            'condition_select': 'python',
            'condition_python': LOAN_CONDITION_CODE,
            'amount_select': 'code',
            'amount_python_compute': LOAN_CODE,
            'appears_on_payslip': True,
        }
        loan_rule = rules_by_code.get('LOAN')
        if loan_rule:
            loan_rule.write(vals)
        else:
            loan_rule = self.create(vals)
            structure.write({'rule_ids': [(4, loan_rule.id)]})
        self._mowgli_setup_rule_accounts(
            structure, debit_by_code={}, credit_by_code={'LOAN': '315000'})
