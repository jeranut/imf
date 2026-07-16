# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_partner_type = fields.Selection([
        ('bailleur', 'Bailleur de fonds'),
        ('agence', 'Agence'),
        ('client', 'Client'),
    ], string='Type de partenaire',
        help="Catégorie du partenaire au sens microfinance, distincte de « Type de client » "
             "(particulier/société) qui décrit la nature juridique. Détermine la visibilité "
             "dans le menu Clients (filtré sur 'client') et dans la sélection des bailleurs sur "
             "microfinance.bailleur.fonds (filtrée sur 'bailleur'). Toujours renseigné par le code "
             "(jamais saisi à la main) : 'agence' synchronisé depuis res.company, 'bailleur' fixé à la "
             "création depuis microfinance.bailleur.fonds, 'client' par défaut de contexte sur le menu "
             "Clients. Volontairement non 'required=True' au niveau champ : ce partner est partagé "
             "avec les autres usages de l'instance (EAT, immobilier), qui n'ont pas cette notion.")

    microfinance_client_type = fields.Selection([
        ('individual', 'Particulier'),
        ('company', 'Société'),
    ], string='Type de client', default='individual')

    # Champ natif res.partner.company_id (déjà filtré par la règle multi-société standard
    # base.res_partner_rule) : un client microfinance est rattaché à une seule agence, pas
    # de partage entre sociétés. Non requis au niveau du champ pour ne pas impacter les
    # partenaires des autres usages de l'instance (EAT, immobilier...) qui restent partagés ;
    # le caractère obligatoire n'est appliqué qu'en contexte microfinance (cf. contrainte
    # _check_microfinance_company_required ci-dessous).
    company_id = fields.Many2one(
        'res.company', string='Société (agence)',
        default=lambda self: self.env.company if self.env.context.get('microfinance_context') else False,
        help="Agence à laquelle ce client est rattaché de façon exclusive. Obligatoire pour "
             "les clients microfinance, laissé vide pour les partenaires partagés entre "
             "sociétés (usages hors microfinance de l'instance).",
    )

    @api.onchange('microfinance_client_type')
    def _onchange_microfinance_client_type(self):
        for partner in self:
            partner.is_company = partner.microfinance_client_type == 'company'

    @api.constrains('company_id', 'microfinance_client_type')
    def _check_microfinance_company_required(self):
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            if not partner.company_id:
                raise ValidationError(_('La société (agence) est obligatoire pour un client microfinance.'))

    # --- Communs ---
    microfinance_internal_reference = fields.Char(string='Référence interne')
    microfinance_statistical_number = fields.Char(string='Numéro statistique')
    microfinance_category_1 = fields.Many2one('microfinance.client.category', string='Catégorie 1')
    microfinance_category_2 = fields.Many2one('microfinance.client.category', string='Catégorie 2')
    microfinance_category_3 = fields.Many2one('microfinance.client.category', string='Catégorie 3')
    microfinance_exit_date = fields.Date(string="Date de sortie")
    microfinance_exit_reason = fields.Text(string="Motif de sortie")
    microfinance_blacklist_ids = fields.One2many('microfinance.client.blacklist', 'partner_id', string='Liste noire')
    microfinance_is_blacklisted = fields.Boolean(compute='_compute_microfinance_is_blacklisted', store=True)

    # --- Crédit ---
    microfinance_loan_ids = fields.One2many('microfinance.loan', 'partner_id', string='Crédits')
    microfinance_loan_count = fields.Integer(compute='_compute_microfinance_loan_count')

    @api.depends('microfinance_loan_ids')
    def _compute_microfinance_loan_count(self):
        for partner in self:
            partner.microfinance_loan_count = len(partner.microfinance_loan_ids)

    def action_view_microfinance_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crédits',
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    # --- Particulier : Identification ---
    microfinance_registration_number = fields.Char(string="N° d'enregistrement")
    microfinance_id_type = fields.Selection([
        ('cin', 'CIN'), ('passport', 'Passeport'), ('other', 'Autre'),
    ], string="Type de pièce d'identité")
    microfinance_id_number = fields.Char(string="N° pièce d'identité")
    microfinance_id_issue_date = fields.Date(string='Date de délivrance')
    microfinance_id_issue_place = fields.Char(string='Lieu de délivrance')
    microfinance_birthdate = fields.Date(string='Date de naissance')
    microfinance_gender = fields.Selection([('m', 'Masculin'), ('f', 'Féminin')], string='Genre')
    microfinance_marital_status = fields.Selection([
        ('single', 'Célibataire'), ('married', 'Marié(e)'), ('divorced', 'Divorcé(e)/Séparé(e)'), ('widowed', 'Veuf/Veuve'),
    ], string='Situation matrimoniale')
    microfinance_profession = fields.Many2one(
        'microfinance.profession', string='Profession',
        help="Autocomplete sur un référentiel configurable (menu Microfinance > Configuration "
             "> Professions), plutôt qu'une liste figée : une institution peut y ajouter ses "
             "propres valeurs à tout moment.",
    )
    microfinance_education_level = fields.Selection([
        ('none', 'Aucun'), ('primary', 'Primaire'), ('secondary', 'Secondaire'), ('higher', 'Supérieur'),
    ], string="Niveau d'éducation")

    # --- Particulier : Famille et compte ---
    microfinance_spouse_name = fields.Char(string='Nom du conjoint')
    microfinance_spouse_phone = fields.Char(string='Téléphone du conjoint')
    microfinance_spouse_profession = fields.Char(string='Profession du conjoint')
    microfinance_next_of_kin_name = fields.Char(string='Personne à contacter')
    microfinance_next_of_kin_address = fields.Char(string='Adresse contact')
    microfinance_co_holder_name = fields.Char(string='Co-titulaire')
    microfinance_required_signatures = fields.Integer(string='Signatures requises', default=1)

    # --- Société : Identité légale (NIF/STAT/RCS remplacent le N° TVA natif) ---
    microfinance_trade_name = fields.Char(string='Nom commercial')
    microfinance_acronym = fields.Char(string='Sigle')
    microfinance_enterprise_type = fields.Selection([
        ('sole_proprietorship', 'Entreprise individuelle'), ('sarl', 'SARL'), ('sa', 'SA'),
        ('cooperative', 'Coopérative'), ('association', 'Association'), ('ngo', 'ONG'),
        ('public', 'Institution publique'), ('other', 'Autre'),
    ], string="Type d'entreprise")
    microfinance_nif = fields.Char(string='NIF')
    microfinance_stat = fields.Char(string='STAT')
    microfinance_rcs = fields.Char(string='RCS')
    microfinance_legal_form = fields.Char(string='Forme juridique')
    microfinance_creation_date = fields.Date(string='Date création')

    # --- Société : Activité et finances ---
    microfinance_business_sector = fields.Char(string="Secteur d'activité")
    microfinance_main_activity = fields.Char(string='Activité principale')
    microfinance_share_capital = fields.Monetary(string='Capital social')
    microfinance_estimated_turnover = fields.Monetary(string='CA estimé')
    microfinance_employee_count = fields.Integer(string='Employés')

    # --- Société : Localisation étendue ---
    microfinance_region = fields.Char(string='Région')
    microfinance_district = fields.Char(string='District')
    microfinance_commune = fields.Char(string='Commune')
    microfinance_locality = fields.Char(string='Localité')
    microfinance_gps_coordinates = fields.Char(string='GPS')
    microfinance_distance_to_branch = fields.Float(string='Distance succursale')

    # --- Société : Fermeture ---
    microfinance_closure_date = fields.Date(string='Date de fermeture')
    microfinance_closure_reason = fields.Text(string='Motif')

    # --- Groupe ---
    microfinance_sub_group_count = fields.Integer(string='Nombre de sous-groupes')

    # --- Comité (Société + Groupe) et Membres (Groupe) ---
    microfinance_representative_ids = fields.One2many('microfinance.client.representative', 'partner_id', string='Comité')
    microfinance_member_ids = fields.One2many('microfinance.client.group.member', 'group_id', string='Membres du groupe')

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    microfinance_id_number_display = fields.Char(
        string='N° pièce (affiché)', compute='_compute_id_number_display', inverse='_inverse_id_number_display',
        help="Présentation en blocs de 3 chiffres pour la lisibilité (ex. 123 456 789 012 pour "
             "un CIN). La valeur brute (chiffres uniquement) reste stockée dans le champ "
             "technique 'N° pièce d'identité' — cette présentation n'affecte ni la validation "
             "12 chiffres ni la recherche. Sans effet pour un type de pièce autre que CIN "
             "(passeport, autre), affiché tel quel.",
    )

    @api.depends('microfinance_id_number', 'microfinance_id_type')
    def _compute_id_number_display(self):
        for partner in self:
            raw = partner.microfinance_id_number or ''
            if partner.microfinance_id_type == 'cin':
                digits = re.sub(r'\D', '', raw)
                partner.microfinance_id_number_display = ' '.join(digits[i:i + 3] for i in range(0, len(digits), 3)) if digits else ''
            else:
                partner.microfinance_id_number_display = raw

    def _inverse_id_number_display(self):
        for partner in self:
            value = partner.microfinance_id_number_display or ''
            if partner.microfinance_id_type == 'cin':
                partner.microfinance_id_number = re.sub(r'\D', '', value)
            else:
                partner.microfinance_id_number = value

    @api.depends('microfinance_blacklist_ids.active', 'microfinance_blacklist_ids.date_end')
    def _compute_microfinance_is_blacklisted(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.microfinance_is_blacklisted = any(
                b.active and (not b.date_end or b.date_end >= today) for b in partner.microfinance_blacklist_ids
            )

    @api.constrains('microfinance_id_type', 'microfinance_id_number')
    def _check_cin_format(self):
        for partner in self:
            if partner.microfinance_id_type == 'cin' and partner.microfinance_id_number:
                digits = re.sub(r'\D', '', partner.microfinance_id_number)
                if len(digits) != 12:
                    raise ValidationError(_('Le numéro de CIN doit contenir exactement 12 chiffres.'))

    @api.constrains('microfinance_client_type', 'microfinance_nif')
    def _check_nif_format(self):
        for partner in self:
            if partner.microfinance_client_type == 'company' and partner.microfinance_nif:
                digits = re.sub(r'\D', '', partner.microfinance_nif)
                if len(digits) != 12:
                    raise ValidationError(_('Le NIF doit contenir exactement 12 chiffres.'))

    @api.constrains('microfinance_marital_status', 'microfinance_spouse_name', 'microfinance_spouse_phone')
    def _check_spouse_required_if_married(self):
        # Hors contexte microfinance, ce contact est partagé avec d'autres usages de l'instance
        # (EAT, immobilier) : aucune contrainte microfinance ne doit s'y appliquer.
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            if partner.microfinance_marital_status == 'married' and not (
                partner.microfinance_spouse_name and partner.microfinance_spouse_phone
            ):
                raise ValidationError(_(
                    'Le nom et le téléphone du conjoint sont obligatoires pour un client marié.'
                ))
