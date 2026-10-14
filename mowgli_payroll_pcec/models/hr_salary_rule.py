# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'hr_payroll_community.group_hr_payroll_community_manager'

# Étape C : comptes PCEC des règles de la structure source, par code
# compte (recherché dans la société de la structure, jamais inventé).
ACCOUNT_DEBIT_BY_CODE = {
    'BASIC': '652100', 'Travel': '652100', 'HRA': '652100', 'DA': '652100', 'Meal': '652100',
    'Medical': '652100', 'Other': '652100',
}
ACCOUNT_CREDIT_BY_CODE = {
    'CNAPS': '315000', 'OSTIE': '315000', 'IRSA': '315000', 'NET': '315000',
}
# GROSS et NETIMP ne reçoivent jamais de compte (lignes informatives).
NO_ACCOUNT_CODES = ('GROSS', 'NETIMP', 'CNAPS_ER', 'OSTIE_ER')
ACCOUNT_ROLES = (('debit', 'debit_account_id'), ('credit', 'credit_account_id'))

CNAPS_CODE = (
    "brut = categories.GROSS\n"
    "base = payslip.dict._mowgli_contribution_base(brut)\n"
    "result = -base * payslip.dict._mowgli_param('CNAPS_SAL')"
)

OSTIE_CODE = (
    "brut = categories.GROSS\n"
    "base = payslip.dict._mowgli_contribution_base(brut)\n"
    "result = -base * payslip.dict._mowgli_param('OSTIE_SAL')"
)

# Parts patronales (catégorie COMP, sans compte, hors bulletin imprimé).
CNAPS_ER_CODE = (
    "brut = categories.GROSS\n"
    "base = payslip.dict._mowgli_contribution_base(brut)\n"
    "result = base * payslip.dict._mowgli_param('CNAPS_ER')"
)

OSTIE_ER_CODE = (
    "brut = categories.GROSS\n"
    "base = payslip.dict._mowgli_contribution_base(brut)\n"
    "result = base * payslip.dict._mowgli_param('OSTIE_ER')"
)

EMPLOYER_CONDITION_CODE = "result = categories.GROSS > 0"
EMPLOYER_RULES = (
    ('CNAPS_ER', 'CNaPS patronal', CNAPS_ER_CODE),
    ('OSTIE_ER', 'OSTIE patronal', OSTIE_ER_CODE),
)

# Indemnités du contrat (catégorie ALW) : Travel reste dans sa propre catégorie
# (« Travel »), donc n'est jamais comptée deux fois dans categories.ALW.
GROSS_CODE = (
    "result = categories.BASIC + categories.Travel + categories.ALW"
)

# (code, nom, champ hr.contract) - séquences consécutives juste après Travel.
ALLOWANCE_RULES = (
    ('HRA', 'Indemnité de logement', 'hra'),
    ('DA', 'Indemnité de vie chère', 'da'),
    ('Meal', 'Indemnité de repas', 'meal_allowance'),
    ('Medical', 'Indemnité médicale', 'medical_allowance'),
    ('Other', 'Autre indemnité', 'other_allowance'),
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
    "    b0 = payslip.dict._mowgli_param('IRSA_B0')\n"
    "    b1 = payslip.dict._mowgli_param('IRSA_B1')\n"
    "    b2 = payslip.dict._mowgli_param('IRSA_B2')\n"
    "    b3 = payslip.dict._mowgli_param('IRSA_B3')\n"
    "    b4 = payslip.dict._mowgli_param('IRSA_B4')\n"
    "    reste = max(base_irsa - b0, 0.0)\n"
    "    irsa = 0.0\n"
    "\n"
    "    t1 = min(b1 - b0, reste)\n"
    "    irsa += t1 * payslip.dict._mowgli_param('IRSA_R1')\n"
    "    reste -= t1\n"
    "\n"
    "    t2 = min(b2 - b1, reste)\n"
    "    irsa += t2 * payslip.dict._mowgli_param('IRSA_R2')\n"
    "    reste -= t2\n"
    "\n"
    "    t3 = min(b3 - b2, reste)\n"
    "    irsa += t3 * payslip.dict._mowgli_param('IRSA_R3')\n"
    "    reste -= t3\n"
    "\n"
    "    t4 = min(b4 - b3, reste)\n"
    "    irsa += t4 * payslip.dict._mowgli_param('IRSA_R4')\n"
    "    reste -= t4\n"
    "\n"
    "    irsa += max(reste, 0.0) * payslip.dict._mowgli_param('IRSA_R5')\n"
    "\n"
    "    enfants = int(employee.children or 0)\n"
    "    irsa = max(irsa - enfants * payslip.dict._mowgli_param('IRSA_ENFANT'), 0.0)\n"
    "    irsa = max(irsa, payslip.dict._mowgli_param('IRSA_MIN'))\n"
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

        cnaps = rules_by_code.get('CNAPS')
        if cnaps:
            cnaps.write({'amount_python_compute': CNAPS_CODE})

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

        self._mowgli_setup_allowance_rules(structure, rules_by_code)
        self._mowgli_setup_employer_rules(structure, rules_by_code)
        self._mowgli_setup_rule_accounts(structure)

    def _mowgli_setup_employer_rules(self, structure, rules_by_code):
        """Ajoute (jamais ne remplace) les règles patronales CNAPS_ER et
        OSTIE_ER : catégorie COMP, sans compte, hors bulletin imprimé,
        séquences juste après OSTIE. Idempotent (recherche par code dans la
        structure, rattachement par (4, id))."""
        ostie = rules_by_code.get('OSTIE')
        if not ostie:
            return
        category = self.env['hr.salary.rule.category'].search(
            [('code', '=', 'COMP')], limit=1)
        if not category:
            category = self.env['hr.salary.rule.category'].create(
                {'name': 'Charges patronales', 'code': 'COMP'})
        for offset, (code, name, python) in enumerate(EMPLOYER_RULES, start=1):
            vals = {
                'name': name,
                'code': code,
                'category_id': category.id,
                'sequence': ostie.sequence + 10 * offset,
                'company_id': ostie.company_id.id,
                'condition_select': 'python',
                'condition_python': EMPLOYER_CONDITION_CODE,
                'amount_select': 'code',
                'amount_python_compute': python,
                'appears_on_payslip': False,
            }
            rule = rules_by_code.get(code)
            if rule:
                rule.write(vals)
            else:
                rule = self.create(vals)
                structure.write({'rule_ids': [(4, rule.id)]})
                rules_by_code[code] = rule

    def _mowgli_setup_allowance_rules(self, structure, rules_by_code):
        """Ajoute (jamais ne remplace) les règles d'indemnités du contrat à la
        structure : recherche par code dans la structure, création ou mise à
        jour idempotente, rattachement par (4, id). Société identique à celle
        de Travel. Le compte de débit est celui de BASIC, renseigné par
        société dans _mowgli_setup_rule_accounts."""
        travel = rules_by_code.get('Travel')
        if not travel:
            return
        category = self.env['hr.salary.rule.category'].search(
            [('code', '=', 'ALW')], limit=1)
        if not category:
            category = self.env['hr.salary.rule.category'].create(
                {'name': 'Indemnités', 'code': 'ALW'})
        for offset, (code, name, field) in enumerate(ALLOWANCE_RULES, start=1):
            vals = {
                'name': name,
                'code': code,
                'category_id': category.id,
                'sequence': travel.sequence + offset,
                'company_id': travel.company_id.id,
                'condition_select': 'python',
                'condition_python': 'result = bool(contract.%s)' % field,
                'amount_select': 'code',
                'amount_python_compute': 'result = contract.%s' % field,
                'appears_on_payslip': True,
            }
            rule = rules_by_code.get(code)
            if rule:
                rule.write(vals)
            else:
                rule = self.create(vals)
                structure.write({'rule_ids': [(4, rule.id)]})
                rules_by_code[code] = rule

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
    def _mowgli_align_company_accounts(self, company, apply=True):
        """Aligne sur la cible PCEC les comptes de paie de `company` pour les
        règles de la structure BASE. Compte attendu cherché par CODE dans
        cette société ; écrit seulement si le champ est vide ou diffère
        (trace avant/après dans les lignes renvoyées) ; jamais de création de
        compte, jamais de suppression (un compte présent sur un rôle sans
        cible est seulement signalé). Statuts : conforme, ecrit, a_ecrire
        (apply=False), compte_absent, inattendu."""
        structure = self.env['hr.payroll.structure'].sudo().search(
            [('code', '=', 'BASE')], limit=1)
        credit_targets = dict(ACCOUNT_CREDIT_BY_CODE, LOAN='315000')
        Account = self.env['account.account'].sudo()
        rows = []
        for rule in structure.rule_ids.sudo().sorted('sequence'):
            scoped = rule.with_company(company)
            for role, fname in ACCOUNT_ROLES:
                targets = ACCOUNT_DEBIT_BY_CODE if role == 'debit' \
                    else credit_targets
                target = targets.get(rule.code)
                current = scoped[fname]
                row = {'regle': rule.code, 'societe': company.name,
                       'role': role, 'cible': target or '',
                       'avant': current.code or '', 'apres': current.code or '',
                       'statut': 'conforme'}
                if not target:
                    if current:
                        row['statut'] = 'inattendu'
                    rows.append(row)
                    continue
                if current and current.company_id == company \
                        and current.code == target:
                    rows.append(row)
                    continue
                account = Account.search([
                    ('code', '=', target), ('company_id', '=', company.id)],
                    limit=1)
                if not account:
                    row['statut'] = 'compte_absent'
                elif apply:
                    scoped.write({fname: account.id})
                    row.update(apres=account.code, statut='ecrit')
                else:
                    row.update(apres=account.code, statut='a_ecrire')
                rows.append(row)
        return rows

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
