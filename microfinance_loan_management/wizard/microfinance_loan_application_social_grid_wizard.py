# -*- coding: utf-8 -*-
from odoo import api, fields, models

_EXCLUDED_FIELDS = ('id', 'application_id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid')


class MicrofinanceLoanApplicationSocialGridWizard(models.TransientModel):
    """Wizard popup — Section VI (partie scalaire) : grille de catégorisation sociale.

    Ne couvre que les scores bruts saisis par l'enquêteur, pas field_visit_ids (VAD/VAV,
    wizard séparé, Lot 3) ni les champs calculés (consumption_units, housing_score,
    total_points, social_level_id) : ces derniers sont recalculés automatiquement par les
    @api.depends du modèle réel dès que action_validate écrit via write(), aucun recalcul
    manuel nécessaire ici."""
    _name = 'microfinance.loan.application.social.grid.wizard'
    _description = 'Modifier la grille de catégorisation sociale'

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)

    household_size = fields.Integer(string='Taille du ménage')
    members_over_14 = fields.Integer(string='Nb de membres > 14 ans')
    members_under_14 = fields.Integer(string='Nb de membres < 14 ans')

    assets_score = fields.Integer(string='Actifs / Patrimoine (1-4)')
    assets_exact_amount = fields.Monetary(string='Actifs : montant exact')
    activity_score = fields.Integer(string='Activité (1-4)')
    income_score = fields.Integer(string='Revenus - bénéfice net du ménage (1-4)')
    income_net_benefit_amount = fields.Monetary(string='Revenus : montant BN')
    food_score = fields.Integer(string='Alimentation (1-4)')
    health_score = fields.Integer(string='Santé (1-4)')
    housing_state_score = fields.Integer(string='Habitat : état du toit (0-2)')
    housing_surface_score = fields.Integer(string='Habitat : surface par membre (0-2)')
    education_borrower_score = fields.Integer(string="Niveau d'éducation du candidat (0-4)")
    education_children_score = fields.Integer(string='Éducation des enfants (1-4)')

    savings_amount = fields.Monetary(string='Épargne (montant)')
    savings_score = fields.Integer(string='Épargne (1-4, optionnel)')
    administrative_score = fields.Integer(string='Administratif (1-4, optionnel)')
    surveyor_impression_score = fields.Integer(string="Impression personnelle de l'enquêteur")

    surveyor_level_impression = fields.Text(string="Impression personnelle sur le niveau du ménage")
    is_eligible = fields.Selection([
        ('yes', 'Oui'), ('no', 'Non'), ('tbd', 'À déterminer'),
    ], string='Le ménage peut-il recevoir un prêt CEFOR ?')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application:
            for field_name in fields_list:
                if field_name in application._fields and field_name not in _EXCLUDED_FIELDS:
                    res[field_name] = application[field_name]
        return res

    def action_validate(self):
        self.ensure_one()
        vals = {f: self[f] for f in self._fields if f not in _EXCLUDED_FIELDS and f != 'currency_id'}
        self.application_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}
