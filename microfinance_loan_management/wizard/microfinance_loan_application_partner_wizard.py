# -*- coding: utf-8 -*-
from odoo import api, fields, models

_EXCLUDED_FIELDS = (
    'id', 'application_id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid',
    'dependent_line_ids',
)


class MicrofinanceLoanApplicationPartnerWizardDependentLine(models.TransientModel):
    """Ligne enfant/personne à charge (wizard) — mirroir de
    microfinance.loan.application.dependent."""
    _name = 'microfinance.loan.application.partner.wizard.dependent.line'
    _description = 'Enfant ou personne à charge (wizard)'

    wizard_id = fields.Many2one(
        'microfinance.loan.application.partner.wizard', required=True, ondelete='cascade')
    name = fields.Char(string='Nom', required=True)
    relationship = fields.Selection([
        ('child', 'Enfant'),
        ('other_dependent', 'Autre personne à charge'),
    ], string='Lien de parenté', required=True, default='child')
    birth_date = fields.Date(string='Date de naissance')
    occupation = fields.Char(string='Occupation / École')


class MicrofinanceLoanApplicationPartnerWizard(models.TransientModel):
    """Wizard popup — Section I : Identification du partenaire (+ Conjoint + Enfants).

    Mono-modèle malgré son nom ("partenaire") : tous ces champs, y compris l'identité et
    l'adresse, vivent en réalité sur microfinance.loan.application elle-même (snapshot
    figé au moment de l'enquête, jamais lié en live à res.partner — cf. audit préalable).
    Seul partner_id (le Many2one lui-même) référence le contact et n'est pas repris ici
    (modifiable directement sur le formulaire principal, hors périmètre de ce wizard)."""
    _name = 'microfinance.loan.application.partner.wizard'
    _description = 'Modifier l\'identification du partenaire'

    application_id = fields.Many2one('microfinance.loan.application', required=True)

    partner_surname = fields.Char(string='Nom de famille')
    partner_id_card_number = fields.Char(string='N° CIN')
    partner_id_card_issue_date = fields.Date(string='CIN délivrée le')
    partner_id_card_issue_place = fields.Char(string='CIN délivrée à')
    partner_current_address = fields.Char(string='Adresse actuelle')
    partner_fokontany = fields.Char(string='Fokontany')
    partner_address_since = fields.Date(string="À cette adresse depuis")
    partner_housing_status = fields.Selection([
        ('owner_inheritance', 'Propriétaire (héritage)'),
        ('owner_purchase', 'Propriétaire (achat)'),
        ('owner_donation', 'Propriétaire (donation)'),
        ('tenant_free', 'Locataire sans loyer'),
        ('tenant_paying', 'Locataire avec loyer'),
    ], string="Statut d'occupation du logement")
    partner_phone = fields.Char(string='Téléphone')
    partner_reference_contact_name = fields.Char(string='Personne de référence')
    partner_reference_contact_phone = fields.Char(string='Téléphone de la référence')
    partner_birth_date = fields.Date(string='Date de naissance')
    partner_birth_place = fields.Char(string='Lieu de naissance')
    partner_marital_status = fields.Selection([
        ('single', 'Célibataire'),
        ('married', 'Marié(e)'),
        ('cohabiting', 'Union libre'),
        ('divorced', 'Divorcé(e)'),
        ('widowed', 'Veuf / Veuve'),
    ], string='Situation matrimoniale')

    spouse_name = fields.Char(string='Nom du conjoint')
    spouse_id_card_number = fields.Char(string='CIN du conjoint')
    spouse_address = fields.Char(string='Adresse du conjoint')
    spouse_fokontany = fields.Char(string='Fokontany du conjoint')
    spouse_profession = fields.Char(string='Profession du conjoint')
    spouse_employer = fields.Char(string='Employeur du conjoint')
    spouse_phone = fields.Char(string='Téléphone du conjoint')
    union_duration = fields.Char(string="Durée de l'union")

    surveyor_comment = fields.Text(string="Commentaire de l'enquêteur")

    dependent_line_ids = fields.One2many(
        'microfinance.loan.application.partner.wizard.dependent.line', 'wizard_id',
        string='Enfants et personnes à charge')

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
        if 'dependent_line_ids' in fields_list:
            res['dependent_line_ids'] = [(0, 0, {
                'name': line.name,
                'relationship': line.relationship,
                'birth_date': line.birth_date,
                'occupation': line.occupation,
            }) for line in application.dependent_ids]
        return res

    def action_validate(self):
        self.ensure_one()
        vals = {f: self[f] for f in self._fields if f not in _EXCLUDED_FIELDS}
        self.application_id.write(vals)
        self.application_id.dependent_ids.unlink()
        self.application_id.write({
            'dependent_ids': [(0, 0, {
                'name': line.name,
                'relationship': line.relationship,
                'birth_date': line.birth_date,
                'occupation': line.occupation,
            }) for line in self.dependent_line_ids],
        })
        return {'type': 'ir.actions.act_window_close'}
