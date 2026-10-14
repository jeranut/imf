# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

CHARGE_ACCOUNT_PARAM = 'mowgli_payroll_contributions.charge_account_code'
DEFAULT_CHARGE_ACCOUNT = '652500'
CREDIT_ACCOUNT = '315000'
JOURNAL_CODE = 'CSOC'
JOURNAL_NAME = 'Charges sociales'
CHARGE_ACCOUNT_NAME = 'Cotisations aux organismes sociaux'


class MowgliPayrollContribution(models.Model):
    _name = 'mowgli.payroll.contribution'
    _description = "Registre des cotisations et impôts de paie"
    _order = 'date desc, organisme, rule_code, id'

    payslip_id = fields.Many2one(
        'hr.payslip', string="Bulletin", required=True, index=True,
        ondelete='cascade', readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', string="Société", required=True, index=True,
        readonly=True)
    currency_id = fields.Many2one(
        related='company_id.currency_id', string="Devise")
    date = fields.Date(string="Date", required=True, readonly=True)
    mois = fields.Char(string="Mois", compute='_compute_mois', store=True,
                       index=True)
    organisme = fields.Selection(
        [('cnaps', "CNaPS"), ('ostie', "OSTIE"), ('irsa', "IRSA")],
        string="Organisme", required=True, readonly=True)
    nature = fields.Selection(
        [('salarie', "Salarié"), ('patronal', "Patronal"),
         ('impot', "Impôt retenu")],
        string="Nature", required=True, readonly=True)
    rule_code = fields.Char(string="Code de règle", required=True, readonly=True)
    base = fields.Monetary(string="Base", readonly=True)
    taux = fields.Float(string="Taux", digits=(16, 6), readonly=True)
    montant = fields.Monetary(string="Montant", readonly=True)
    state = fields.Selection(
        [('a_verser', "À verser"), ('declare', "Déclaré"), ('verse', "Versé")],
        string="État", default='a_verser', required=True, index=True)
    declaration_ref = fields.Char(string="Référence de déclaration")
    payment_date = fields.Date(string="Date de versement")
    move_id = fields.Many2one(
        'account.move', string="Écriture CSOC", readonly=True,
        help="Écriture du journal Charges sociales (part patronale).")

    _sql_constraints = [
        ('payslip_rule_unique', 'unique(payslip_id, rule_code)',
         "Une seule ligne de registre par bulletin et par règle."),
    ]

    @api.depends('date')
    def _compute_mois(self):
        for line in self:
            line.mois = line.date.strftime('%Y-%m') if line.date else False

    # ------------------------------------------------------------------
    # Mise en place : compte 652500 (seulement s'il manque) et journal CSOC
    # ------------------------------------------------------------------
    @api.model
    def _charge_account_code(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            CHARGE_ACCOUNT_PARAM, DEFAULT_CHARGE_ACCOUNT) or DEFAULT_CHARGE_ACCOUNT

    @api.model
    def _ensure_charge_account(self, company):
        """Compte de charge patronale de `company` : créé SEULEMENT s'il
        manque (copie du compte de référence d'une autre société, sinon
        compte minimal). Un compte existant n'est jamais modifié.
        Renvoie (compte, créé?)."""
        code = self._charge_account_code()
        Account = self.env['account.account'].sudo()
        account = Account.search(
            [('code', '=', code), ('company_id', '=', company.id)], limit=1)
        if account:
            return account, False
        reference = company._mowgli_reference_account(code)
        if reference:
            account = company._mowgli_create_account_from(reference)
        else:
            account = Account.with_company(company).create({
                'code': code, 'name': CHARGE_ACCOUNT_NAME,
                'account_type': 'expense', 'reconcile': False,
                'company_id': company.id})
        return account, True

    @api.model
    def _get_or_create_journal(self, company):
        """Journal général « Charges sociales » (CSOC), créé seulement s'il
        manque (même patron que le journal RSAL) : jamais d'écrasement."""
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search(
            [('code', '=', JOURNAL_CODE), ('company_id', '=', company.id)],
            limit=1)
        if journal:
            return journal
        return Journal.create({
            'name': JOURNAL_NAME, 'code': JOURNAL_CODE, 'type': 'general',
            'company_id': company.id})

    @api.model
    def _setup_all(self):
        """Appelé à chaque installation/mise à jour (idempotent) : pour chaque
        société ACTIVE avec plan comptable, compte de charge patronale et
        journal CSOC s'ils manquent. Renvoie les sociétés où le compte a été
        créé."""
        created = []
        for company in self.env['res.company'].sudo().search(
                [('chart_template', '!=', False)]):
            account, was_created = self._ensure_charge_account(company)
            if was_created:
                created.append(company.name)
                _logger.info("mowgli_payroll_contributions: compte %s créé "
                             "pour %s.", account.code, company.name)
            self._get_or_create_journal(company)
        if created:
            _logger.info("mowgli_payroll_contributions: compte de charge "
                         "créé pour : %s", ', '.join(created))
        return created
