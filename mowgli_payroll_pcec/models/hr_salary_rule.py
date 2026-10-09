# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'

# Étape C : comptes PCEC des règles de la structure source, par code
# compte (recherché dans la société de la structure, jamais inventé).
ACCOUNT_DEBIT_BY_CODE = {'BASIC': '652100'}
ACCOUNT_CREDIT_BY_CODE = {
    'CNAPS': '315000', 'OSTIE': '315000', 'IRSA': '315000', 'NET': '315000',
}
# GROSS et NETIMP ne reçoivent jamais de compte (lignes informatives).
NO_ACCOUNT_CODES = ('GROSS', 'NETIMP')
ACCOUNT_ROLES = (('debit', 'debit_account_id'), ('credit', 'credit_account_id'))

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

    # Règle PARTAGÉE entre agences : company_id vide, seuls les comptes
    # débit/crédit varient par société (company_dependent).
    company_id = fields.Many2one(
        'res.company', string='Société', default=False,
        help="Laisser vide : la règle est partagée par toutes les agences.")
    debit_account_id = fields.Many2one(
        'account.account', string='Compte à débiter', company_dependent=True,
        domain="[('company_id', '=', current_company_id)]",
        help="Compte débité pour la société active (une valeur par société).")
    credit_account_id = fields.Many2one(
        'account.account', string='Compte à créditer', company_dependent=True,
        domain="[('company_id', '=', current_company_id)]",
        help="Compte crédité pour la société active (une valeur par société).")
    mowgli_source_id = fields.Many2one(
        'hr.salary.rule', string='Règle source (OBSOLÈTE)',
        index=True, copy=False, readonly=True,
        help="OBSOLÈTE : ancienne copie de règles par agence, plus utilisée.")
    mowgli_accounts_by_company = fields.Html(
        string="Comptes par société", compute='_compute_mowgli_accounts',
        sanitize=False)

    @api.constrains('debit_account_id', 'credit_account_id')
    def _check_mowgli_account_company(self):
        company = self.env.company
        for rule in self:
            for __, fname in ACCOUNT_ROLES:
                account = rule[fname].sudo()
                if account and account.company_id != company:
                    raise ValidationError(_(
                        "Le compte %(account)s appartient à %(owner)s : la "
                        "règle %(rule)s ne peut utiliser, pour %(company)s, "
                        "qu'un compte de cette société.") % {
                            'account': account.display_name,
                            'owner': account.company_id.name,
                            'rule': rule.code, 'company': company.name})

    # ------------------------------------------------------------------
    # Résolution des comptes par société
    # ------------------------------------------------------------------
    @api.model
    def _mowgli_payroll_account_codes(self):
        """Liste blanche : codes référencés par les règles de la structure
        BASE (pour la société modèle) + constantes de configuration."""
        codes = set(ACCOUNT_DEBIT_BY_CODE.values())
        codes |= set(ACCOUNT_CREDIT_BY_CODE.values())
        codes |= set(self.env['ir.config_parameter'].sudo().get_param(
            'mowgli_payroll_pcec.extra_account_codes', '').split(',')) - {''}
        model = self.env['res.company']._mowgli_model_company()
        structure = self.env['hr.payroll.structure'].sudo().search(
            [('code', '=', 'BASE')], limit=1)
        if model and structure:
            for rule in structure.rule_ids.sudo().with_company(model):
                for __, fname in ACCOUNT_ROLES:
                    if rule[fname]:
                        codes.add(rule[fname].code)
        return codes

    def _mowgli_model_code(self, fname):
        """Code de compte que cette règle utilise (valeur de la société
        modèle), ou False si la règle n'a pas de compte pour ce rôle."""
        self.ensure_one()
        model = self.env['res.company']._mowgli_model_company()
        if not model:
            return False
        return self.sudo().with_company(model)[fname].code or False

    def _mowgli_valid_account(self, fname, company):
        """Valeur par société valide (du bon propriétaire) ou vide."""
        self.ensure_one()
        account = self.sudo().with_company(company)[fname].exists()
        if account and account.company_id != company:
            return account.browse()
        return account

    def _mowgli_account_for_company(self, fname, company):
        """Compte de la règle pour `company` (celle de la fiche). Si la
        valeur manque, la résout par code (création en filet si le code a
        été supprimé) et la mémorise ; UserError pour une société sans plan.
        Renvoie un recordset vide si la règle n'a pas de compte."""
        self.ensure_one()
        account = self._mowgli_valid_account(fname, company)
        if account:
            return account
        code = self._mowgli_model_code(fname)
        if not code:
            return account
        account = company._mowgli_get_or_create_account(code)
        self.sudo().with_company(company).write({fname: account.id})
        return account

    @api.model
    def _mowgli_complete_company_accounts(self, rules, companies, apply):
        """Renseigne (apply=True) ou simule les valeurs par société des
        `rules` pour `companies`. Ne remplace jamais une valeur valide.
        Renvoie une liste de lignes (dict) pour le rapport/CSV."""
        rows = []
        Company = self.env['res.company']
        for company in companies:
            for rule in rules:
                for role, fname in ACCOUNT_ROLES:
                    code = rule._mowgli_model_code(fname)
                    if not code:
                        continue
                    row = {'regle': rule.code, 'role': role,
                           'societe': company.name, 'code': code,
                           'compte_id': '', 'statut': ''}
                    current = rule._mowgli_valid_account(fname, company)
                    if current:
                        row.update(compte_id=current.id,
                                   statut='deja_renseigne')
                    elif not company.chart_template:
                        row['statut'] = 'sans_plan_a_installer'
                    else:
                        found = company._mowgli_find_account(code)
                        if found:
                            row.update(compte_id=found.id, statut='resolu')
                            if apply:
                                rule.sudo().with_company(company).write(
                                    {fname: found.id})
                        elif not Company._mowgli_reference_account(code):
                            row['statut'] = 'code_inconnu'
                        elif apply:
                            try:
                                created = company._mowgli_get_or_create_account(code)
                            except UserError as exc:
                                row['statut'] = 'refuse: %s' % exc.args[0]
                            else:
                                rule.sudo().with_company(company).write(
                                    {fname: created.id})
                                row.update(compte_id=created.id,
                                           statut='cree')
                        else:
                            row['statut'] = 'a_creer'
                    rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # Tableau « Comptes par société » (formulaire)
    # ------------------------------------------------------------------
    @api.depends_context('uid')
    def _compute_mowgli_accounts(self):
        companies = self.env.user.company_ids
        for rule in self:
            if not rule.id:
                rule.mowgli_accounts_by_company = False
                continue
            lines = []
            for company in companies:
                cells = []
                for __, fname in ACCOUNT_ROLES:
                    cells.append(rule._mowgli_account_badge(fname, company))
                lines.append(Markup(
                    "<tr><td>%s</td><td>%s</td><td>%s</td></tr>") % (
                        company.name, cells[0], cells[1]))
            rule.mowgli_accounts_by_company = Markup(
                '<table class="table table-sm"><thead><tr><th>Société</th>'
                '<th>Compte à débiter</th><th>Compte à créditer</th></tr>'
                '</thead><tbody>%s</tbody></table>') % Markup('').join(lines)

    def _mowgli_account_badge(self, fname, company):
        self.ensure_one()
        if not self._mowgli_model_code(fname):
            return Markup('<span class="text-muted">—</span>')
        if not company.chart_template:
            return Markup(
                '<span class="badge text-bg-warning">société sans plan '
                'comptable</span>')
        account = self._mowgli_valid_account(fname, company)
        if not account:
            return Markup('<span class="badge text-bg-danger">manquant</span>')
        text = escape(account.display_name)
        if account.mowgli_auto_created:
            return Markup(
                '%s <span class="badge text-bg-info">créé '
                'automatiquement</span>') % text
        return text

    def action_mowgli_complete_accounts(self):
        """Bouton (Paie / Manager) : renseigne les comptes manquants de
        cette règle pour toutes les sociétés accessibles."""
        if not self.env.user.has_group(MANAGER_GROUP):
            raise UserError(_("Réservé au groupe Paie / Manager."))
        self._mowgli_complete_company_accounts(
            self, self.env.user.company_ids, apply=True)
        return True

    # ------------------------------------------------------------------
    # Mise en place des règles (à chaque -u, idempotente)
    # ------------------------------------------------------------------
    @api.model
    def _mowgli_migration_pending(self):
        """Vrai tant que la migration « paie multi-sociétés » n'a pas été
        appliquée pour de bon (colonnes historiques encore remplies) : les
        fonctions de mise en place ne font alors rien (dry-run honnête)."""
        cr = self.env.cr
        cr.execute("""SELECT column_name FROM information_schema.columns
                      WHERE table_name = 'hr_salary_rule'
                        AND column_name IN ('debit_account_id',
                                            'credit_account_id')""")
        columns = [row[0] for row in cr.fetchall()]
        for column in columns:
            cr.execute(
                'SELECT 1 FROM hr_salary_rule WHERE "%s" IS NOT NULL LIMIT 1'
                % column)
            if cr.fetchone():
                return True
        return False

    @api.model
    def _mowgli_companies_with_chart(self):
        return self.env['res.company'].sudo().search(
            [('chart_template', '!=', False)])

    @api.model
    def _mowgli_setup_payroll_rules(self):
        """Mise à jour idempotente de la structure BASE : recherche par
        (code, structure) avant création/écriture. La structure et ses
        règles restent PARTAGÉES (company_id jamais écrit) ; seuls les
        comptes sont renseignés par société (cf. _mowgli_setup_rule_accounts).

        Note : le moteur de calcul de hr_payroll_community expose le
        montant déjà calculé d'une règle précédente comme variable simple
        portant le code de la règle (ex. CNAPS, OSTIE, NETIMP) dans le
        contexte d'évaluation - PAS comme rules.<CODE>.total."""
        if self._mowgli_migration_pending():
            _logger.info("mowgli_payroll_pcec: migration paie multi-sociétés "
                         "en attente, mise en place des règles ignorée.")
            return
        structure = self.env['hr.payroll.structure'].search(
            [('code', '=', 'BASE')], limit=1)
        if not structure:
            return

        rules_by_code = {rule.code: rule for rule in structure.rule_ids}

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

        self._mowgli_setup_rule_accounts(structure)

    def _mowgli_setup_rule_accounts(self, structure, debit_by_code=None,
                                    credit_by_code=None):
        """Renseigne, pour CHAQUE société ayant un plan comptable, les
        comptes débit/crédit des règles de la structure, en résolvant le
        code dans cette société (jamais par id). N'écrase jamais une valeur
        valide ; idempotent. Société sans plan : ignorée (le hook
        d'installation du plan les renseignera). GROSS et NETIMP ne
        reçoivent jamais de compte."""
        debit_by_code = ACCOUNT_DEBIT_BY_CODE if debit_by_code is None \
            else debit_by_code
        credit_by_code = ACCOUNT_CREDIT_BY_CODE if credit_by_code is None \
            else credit_by_code
        rules_by_code = {rule.code: rule for rule in structure.rule_ids}
        Account = self.env['account.account'].sudo()
        for company in self._mowgli_companies_with_chart():
            for mapping, fname in ((debit_by_code, 'debit_account_id'),
                                   (credit_by_code, 'credit_account_id')):
                for code, account_code in mapping.items():
                    rule = rules_by_code.get(code)
                    if not rule or code in NO_ACCOUNT_CODES:
                        continue
                    if rule._mowgli_valid_account(fname, company):
                        continue
                    account = Account.search([
                        ('code', '=', account_code),
                        ('company_id', '=', company.id)], limit=1)
                    if account:
                        rule.sudo().with_company(company).write(
                            {fname: account.id})
                    else:
                        _logger.warning(
                            "mowgli_payroll_pcec: compte %s introuvable pour "
                            "la société %s, %s de la règle %s laissé vide.",
                            account_code, company.name, fname, code)

    @api.model
    def _mowgli_complete_new_company(self, company):
        """Appelé après l'installation d'un plan comptable sur `company` :
        renseigne les comptes de paie de toutes les règles de la structure
        BASE pour cette société (résolution par code)."""
        structure = self.env['hr.payroll.structure'].sudo().search(
            [('code', '=', 'BASE')], limit=1)
        if not structure or not company.chart_template:
            return []
        return self._mowgli_complete_company_accounts(
            structure.rule_ids.sudo(), company, apply=True)
