# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanApplicationFieldVisitWizardLine(models.TransientModel):
    """Ligne visite terrain (wizard) — mirroir de
    microfinance.loan.application.field.visit.

    counter_visit_of_id pointe vers une AUTRE ligne de CE wizard (pas vers un
    enregistrement réel) : lors du préremplissage (default_get), la référence réelle
    d'origine est mémorisée dans les champs cachés source_field_visit_id /
    source_counter_visit_of_id, puis résolue entre lignes-wizard sœurs par
    _resolve_source_counter_visit_links() une fois toutes les lignes effectivement
    créées (impossible de le faire en une seule passe : au moment du default_get,
    aucune des nouvelles lignes n'a encore d'id réel à référencer)."""
    _name = 'microfinance.loan.application.field.visit.wizard.line'
    _description = 'Visite terrain (wizard)'

    wizard_id = fields.Many2one(
        'microfinance.loan.application.field.visit.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id', readonly=True)

    visit_type = fields.Selection([
        ('home', 'Visite à domicile (VAD)'),
        ('sales_point', 'Visite au lieu de vente (VAV)'),
    ], string='Type de visite', required=True)
    is_counter_visit = fields.Boolean(string='Contre-visite')
    counter_visit_of_id = fields.Many2one(
        'microfinance.loan.application.field.visit.wizard.line', string='Contre-visite de',
        domain="[('wizard_id', '=', wizard_id), ('visit_type', '=', visit_type), ('is_counter_visit', '=', False)]",
    )
    agent_id = fields.Many2one('res.users', string='Effectué par', required=True)
    visit_date = fields.Date(string='Date', required=True, default=fields.Date.context_today)

    constats = fields.Text(string='Constats')
    neighborhood_reputation = fields.Text(string='Réputation dans le quartier (recoupement moral)')

    project_exists = fields.Boolean(string='Existence du projet (lieu de vente)')
    potential_clients_level = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Élevée'),
    ], string='Existence des clients potentiels')
    stock_value = fields.Monetary(string='Valeur du stock')
    competition_level = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Élevée'),
    ], string='Concurrence')
    product_presentation = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Bonne'),
    ], string='Présentation des produits')
    commercial_attitude = fields.Selection([
        ('bad', 'Mauvaise'), ('medium', 'Moyenne'), ('good', 'Bonne'),
    ], string='Attitude commerciale')

    # Champs techniques cachés, jamais affichés en vue : uniquement utilisés pour
    # reconstituer les liens counter_visit_of_id après création (cf. docstring modèle).
    source_field_visit_id = fields.Integer(string='(technique) Visite réelle d\'origine')
    source_counter_visit_of_id = fields.Integer(string='(technique) Référence réelle d\'origine')

    def _resolve_source_counter_visit_links(self):
        """Reconstitue counter_visit_of_id entre lignes-wizard sœurs à partir des id réels
        mémorisés au default_get (source_field_visit_id / source_counter_visit_of_id) —
        n'a d'effet qu'à l'ouverture du wizard sur un dossier ayant déjà des visites ;
        sans effet sur des lignes ajoutées à la main par l'utilisateur (source_field_visit_id
        vide dans ce cas, la sélection manuelle de counter_visit_of_id fonctionne alors
        normalement via le widget Many2one)."""
        by_source = {line.source_field_visit_id: line for line in self if line.source_field_visit_id}
        for line in self:
            if line.source_counter_visit_of_id and line.source_counter_visit_of_id in by_source:
                line.counter_visit_of_id = by_source[line.source_counter_visit_of_id].id

    def _to_field_visit_vals(self, application_id):
        self.ensure_one()
        return {
            'application_id': application_id,
            'visit_type': self.visit_type,
            'is_counter_visit': self.is_counter_visit,
            'agent_id': self.agent_id.id,
            'visit_date': self.visit_date,
            'constats': self.constats,
            'neighborhood_reputation': self.neighborhood_reputation,
            'project_exists': self.project_exists,
            'potential_clients_level': self.potential_clients_level,
            'stock_value': self.stock_value,
            'competition_level': self.competition_level,
            'product_presentation': self.product_presentation,
            'commercial_attitude': self.commercial_attitude,
        }


class MicrofinanceLoanApplicationFieldVisitWizard(models.TransientModel):
    """Wizard popup — Section VI : visites terrain (VAD/VAV/contre-visites).

    Remplacement complet des lignes à la validation (décision explicite : perte de
    l'historique create_date/write_date de chaque visite individuelle acceptée)."""
    _name = 'microfinance.loan.application.field.visit.wizard'
    _description = 'Modifier les visites terrain'

    application_id = fields.Many2one('microfinance.loan.application', required=True)
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)
    line_ids = fields.One2many(
        'microfinance.loan.application.field.visit.wizard.line', 'wizard_id', string='Visites')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application and 'line_ids' in fields_list:
            res['line_ids'] = [(0, 0, {
                'visit_type': visit.visit_type,
                'is_counter_visit': visit.is_counter_visit,
                'agent_id': visit.agent_id.id,
                'visit_date': visit.visit_date,
                'constats': visit.constats,
                'neighborhood_reputation': visit.neighborhood_reputation,
                'project_exists': visit.project_exists,
                'potential_clients_level': visit.potential_clients_level,
                'stock_value': visit.stock_value,
                'competition_level': visit.competition_level,
                'product_presentation': visit.product_presentation,
                'commercial_attitude': visit.commercial_attitude,
                'source_field_visit_id': visit.id,
                'source_counter_visit_of_id': visit.counter_visit_of_id.id or 0,
            }) for visit in application.field_visit_ids]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        wizards.line_ids._resolve_source_counter_visit_links()
        return wizards

    def action_validate(self):
        self.ensure_one()
        self.application_id.field_visit_ids.unlink()
        Visit = self.env['microfinance.loan.application.field.visit']
        # Deux passes, comme pour le préremplissage : les visites initiales doivent
        # exister (avec un id réel) avant que les contre-visites ne puissent les
        # référencer via counter_visit_of_id.
        initial_lines = self.line_ids.filtered(lambda l: not l.is_counter_visit)
        counter_lines = self.line_ids.filtered(lambda l: l.is_counter_visit)
        line_to_real = {}
        for line in initial_lines:
            real = Visit.create(line._to_field_visit_vals(self.application_id.id))
            line_to_real[line.id] = real
        for line in counter_lines:
            vals = line._to_field_visit_vals(self.application_id.id)
            if line.counter_visit_of_id:
                vals['counter_visit_of_id'] = line_to_real[line.counter_visit_of_id.id].id
            Visit.create(vals)
        return {'type': 'ir.actions.act_window_close'}
