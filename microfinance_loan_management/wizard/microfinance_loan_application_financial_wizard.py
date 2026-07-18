# -*- coding: utf-8 -*-
from odoo import api, fields, models

_EXCLUDED_FIELDS = (
    'id', 'application_id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid',
    'income_line_ids', 'currency_id',
)


class MicrofinanceLoanApplicationFinancialWizardLine(models.TransientModel):
    """Ligne revenus/dépenses (wizard) — mirroir de
    microfinance.loan.application.income.line. Un seul modèle de ligne pour les deux
    scénarios (actuel/prévisionnel) : la vue affiche deux sous-listes filtrées par
    scenario, comme field_visit_ids sur le formulaire principal (VAD/VAV)."""
    _name = 'microfinance.loan.application.financial.wizard.line'
    _description = 'Ligne revenus/dépenses (wizard)'

    wizard_id = fields.Many2one(
        'microfinance.loan.application.financial.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id', readonly=True)
    category = fields.Selection([
        ('family_income', 'Revenu familial'),
        ('activity_expense', "Dépense d'activité"),
        ('family_expense', 'Dépense familiale'),
    ], string='Catégorie', required=True)
    scenario = fields.Selection([
        ('current', 'Actuel'),
        ('forecast', 'Prévisionnel'),
    ], string='Scénario', required=True, default='current')
    name = fields.Char(string='Libellé', required=True)
    monthly_amount = fields.Monetary(string='Montant mensuel', required=True)


class MicrofinanceLoanApplicationFinancialWizard(models.TransientModel):
    """Wizard popup — Section V : Analyse financière et capacité de remboursement.

    Ne couvre que les champs saisis (lignes revenus/dépenses, marges de sécurité, plan
    de financement détaillé, suivi de capital) — pas les totaux/capacités calculés
    (total_family_income_*, repayment_capacity_*, funding_plan_*_total), recalculés
    automatiquement par les @api.depends du modèle réel à la validation."""
    _name = 'microfinance.loan.application.financial.wizard'
    _description = "Modifier l'analyse financière"

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)

    income_line_ids = fields.One2many(
        'microfinance.loan.application.financial.wizard.line', 'wizard_id', string='Revenus / dépenses')

    safety_margin_current = fields.Float(string='Majoration dépenses actuelles (%)')
    safety_margin_forecast = fields.Float(string='Majoration dépenses prévisionnelles (%)')
    income_growth_before = fields.Monetary(string='Revenu avant')
    income_growth_after = fields.Monetary(string='Revenu actuel')
    financial_analysis_comment = fields.Text(string="Commentaire d'analyse financière")

    funding_plan_raw_materials_current = fields.Monetary(string='Matières premières (actuel)')
    funding_plan_merchandise_current = fields.Monetary(string='Marchandises (actuel)')
    funding_plan_available_cash_current = fields.Monetary(string='Argent disponible (actuel)')
    funding_plan_equipment_forecast = fields.Monetary(string='Matériel-Mobilier-Équipement (prévisionnel)')
    funding_plan_raw_materials_forecast = fields.Monetary(string='Matières premières (prévisionnel)')
    funding_plan_merchandise_forecast = fields.Monetary(string='Marchandises (prévisionnel)')

    capital_increase = fields.Boolean(string='Augmentation du capital (ou stock)')
    capital_before_previous_loan = fields.Monetary(string='Capital avant le prêt précédent')
    capital_currently_observed = fields.Monetary(string='Dûment constaté actuellement')
    capital_currently_confirmed = fields.Monetary(string='Constaté actuellement')
    previous_loan_fund_usage = fields.Text(string='Utilisation du dernier crédit (suivi de fonds)')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if not application:
            return res
        for field_name in fields_list:
            if field_name in application._fields and field_name not in _EXCLUDED_FIELDS:
                res[field_name] = application[field_name]
        if 'income_line_ids' in fields_list:
            res['income_line_ids'] = [(0, 0, {
                'category': line.category,
                'scenario': line.scenario,
                'name': line.name,
                'monthly_amount': line.monthly_amount,
            }) for line in application.income_line_ids]
        return res

    def action_validate(self):
        self.ensure_one()
        vals = {f: self[f] for f in self._fields if f not in _EXCLUDED_FIELDS}
        self.application_id.write(vals)
        self.application_id.income_line_ids.unlink()
        self.application_id.write({
            'income_line_ids': [(0, 0, {
                'category': line.category,
                'scenario': line.scenario,
                'name': line.name,
                'monthly_amount': line.monthly_amount,
            }) for line in self.income_line_ids],
        })
        return {'type': 'ir.actions.act_window_close'}
