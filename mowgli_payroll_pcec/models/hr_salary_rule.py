# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Étape C : comptes PCEC des règles de la structure source, par code
# compte (recherché dans la société de la structure, jamais inventé).
ACCOUNT_DEBIT_BY_CODE = {'BASIC': '652100'}
ACCOUNT_CREDIT_BY_CODE = {
    'CNAPS': '315000', 'OSTIE': '315000', 'IRSA': '315000', 'NET': '315000',
}
# GROSS et NETIMP ne reçoivent jamais de compte (lignes informatives).
NO_ACCOUNT_CODES = ('GROSS', 'NETIMP')

OSTIE_CODE = (
    "# OSTIE salarié - 1 % du brut (cf. CNAPS)\n"
    "brut = categories.GROSS\n"
    "result = -brut * 0.01 if brut > 0 else 0.0"
)

GROSS_CODE = (
    "result = categories.BASIC + categories.Travel"
)

NET_CODE = (
    "result = categories.GROSS + categories.DED"
)

NETIMP_CODE = (
    "brut = categories.GROSS\n"
    "cnaps = -CNAPS\n"
    "ostie = -OSTIE\n"
    "result = max(brut - cnaps - ostie, 0.0)"
)

IRSA_CODE = (
    "base_irsa = NETIMP\n"
    "\n"
    "if base_irsa <= 0:\n"
    "    result = 0.0\n"
    "else:\n"
    "    reste = max(base_irsa - 350000, 0.0)\n"
    "    irsa = 0.0\n"
    "\n"
    "    t1 = min(50000, reste)        # 350 001 - 400 000 -> 5 %\n"
    "    irsa += t1 * 0.05\n"
    "    reste -= t1\n"
    "\n"
    "    t2 = min(100000, reste)       # 400 001 - 500 000 -> 10 %\n"
    "    irsa += t2 * 0.10\n"
    "    reste -= t2\n"
    "\n"
    "    t3 = min(100000, reste)       # 500 001 - 600 000 -> 15 %\n"
    "    irsa += t3 * 0.15\n"
    "    reste -= t3\n"
    "\n"
    "    if reste > 0:                 # > 600 000 -> 20 %\n"
    "        irsa += reste * 0.20\n"
    "\n"
    "    enfants = int(employee.children or 0)\n"
    "    irsa = max(irsa - enfants * 2000, 0.0)\n"
    "    irsa = max(irsa, 3000.0)\n"
    "\n"
    "    result = -irsa"
)


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    mowgli_source_id = fields.Many2one(
        'hr.salary.rule', string='Règle source (synchro agences)',
        index=True, copy=False, readonly=True,
        help="Règle maître dont cette règle est la copie, pour une agence "
             "cible. Permet à la synchronisation de retrouver la copie "
             "sans doublon même si le code a changé.")

    @api.model
    def _mowgli_setup_payroll_rules(self):
        """Mise à jour idempotente de la structure BASE : recherche par
        (code, structure) avant création/écriture, car les règles existantes
        créées depuis l'interface n'ont pas d'external id.

        Corrige OSTIE (signe/taux), GROSS et NET (indemnité de transport
        ignorée par bug de casse et de catégorie), le company_id de
        CNAPS/OSTIE/IRSA, ajoute la catégorie et la règle NETIMP, et met à
        jour IRSA pour lire la base imposable NETIMP.

        Note : le moteur de calcul de hr_payroll_community expose le
        montant déjà calculé d'une règle précédente comme variable simple
        portant le code de la règle (ex. CNAPS, OSTIE, NETIMP) dans le
        contexte d'évaluation - PAS comme rules.<CODE>.total (hr.salary.rule
        n'a pas de champ 'total', seul hr.payslip.line en a un).
        """
        structure = self.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if not structure:
            return

        company_id = structure.company_id.id
        rules_by_code = {rule.code: rule for rule in structure.rule_ids}

        for code in ('CNAPS', 'OSTIE', 'IRSA'):
            rule = rules_by_code.get(code)
            if rule and rule.company_id.id != company_id:
                rule.write({'company_id': company_id})

        ostie = rules_by_code.get('OSTIE')
        if ostie:
            ostie.write({'amount_python_compute': OSTIE_CODE})

        gross = rules_by_code.get('GROSS')
        if gross:
            gross.write({'amount_python_compute': GROSS_CODE})

        net = rules_by_code.get('NET')
        if net:
            net.write({'amount_python_compute': NET_CODE})

        category = self.env['hr.salary.rule.category'].search(
            [('code', '=', 'NETIMP')], limit=1)
        if not category:
            category = self.env['hr.salary.rule.category'].create({
                'name': 'Net imposable',
                'code': 'NETIMP',
            })

        netimp_vals = {
            'name': 'Net imposable',
            'code': 'NETIMP',
            'category_id': category.id,
            'sequence': 700,
            'condition_select': 'none',
            'amount_select': 'code',
            'appears_on_payslip': True,
            'company_id': company_id,
            'amount_python_compute': NETIMP_CODE,
        }
        netimp = rules_by_code.get('NETIMP')
        if netimp:
            netimp.write(netimp_vals)
        else:
            netimp = self.create(netimp_vals)
            structure.write({'rule_ids': [(4, netimp.id)]})

        irsa = rules_by_code.get('IRSA')
        if irsa:
            irsa.write({'amount_python_compute': IRSA_CODE})

        self._mowgli_setup_rule_accounts(structure, company_id)

    def _mowgli_setup_rule_accounts(self, structure, company_id):
        """Étape C : configure les comptes débit/crédit des règles de la
        structure source, par recherche de compte (code, company_id) -
        jamais par id statique. Ne configure que les règles dont le compte
        cible existe réellement ; signale (log) et laisse vide sinon.
        GROSS et NETIMP ne reçoivent jamais de compte."""
        Account = self.env['account.account']
        rules_by_code = {rule.code: rule for rule in structure.rule_ids}

        for code in NO_ACCOUNT_CODES:
            rule = rules_by_code.get(code)
            if rule and (rule.debit_account_id or rule.credit_account_id):
                rule.write({
                    'debit_account_id': False, 'credit_account_id': False})

        for code, account_code in ACCOUNT_DEBIT_BY_CODE.items():
            rule = rules_by_code.get(code)
            if not rule:
                continue
            account = Account.search(
                [('code', '=', account_code), ('company_id', '=', company_id)],
                limit=1)
            if account:
                if rule.debit_account_id != account:
                    rule.write({'debit_account_id': account.id})
            else:
                _logger.warning(
                    "mowgli_payroll_pcec: compte %s introuvable pour la "
                    "société %s, débit de la règle %s laissé vide.",
                    account_code, company_id, code)

        for code, account_code in ACCOUNT_CREDIT_BY_CODE.items():
            rule = rules_by_code.get(code)
            if not rule:
                continue
            account = Account.search(
                [('code', '=', account_code), ('company_id', '=', company_id)],
                limit=1)
            if account:
                if rule.credit_account_id != account:
                    rule.write({'credit_account_id': account.id})
            else:
                _logger.warning(
                    "mowgli_payroll_pcec: compte %s introuvable pour la "
                    "société %s, crédit de la règle %s laissé vide.",
                    account_code, company_id, code)
