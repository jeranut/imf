# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MicrofinanceGeoCommune(models.Model):
    """Unité administrative de niveau commune, alignée sur le référentiel
    de codification de la Banque Centrale de Madagascar (BCM).

    Structure générique à 2 niveaux (commune -> fokontany), scalable à
    n'importe quelle ville malgache :
    - Une ville "simple" (ex: Fianarantsoa) = une seule commune.
    - Une ville à arrondissements (ex: Antananarivo) = plusieurs communes
      BCM (Antananarivo I à VI), chacune rattachée à une commune "mère"
      virtuelle via parent_city_id, uniquement pour le regroupement/reporting.

    Le libellé "Arrondissement" vs "Commune" est calculé automatiquement
    depuis la présence ou non de parent_city_id : aucune configuration
    manuelle requise, et la structure s'adapte d'elle-même si une ville
    change de découpage (fusion, scission, nouveaux arrondissements).
    """
    _name = 'microfinance.geo.commune'
    _description = 'Commune (référentiel BCM)'
    _order = 'name'
    _rec_name = 'display_name'
    _parent_name = 'parent_city_id'

    code = fields.Char(
        string='Code BCM', index=True,
        help="Code commune selon le référentiel de la Banque Centrale de "
             "Madagascar. Laisser vide pour une entrée de regroupement "
             "purement locale (ex: ville mère sans code BCM propre).")
    name = fields.Char(string='Nom', required=True, index=True)
    postal_code = fields.Char(string='Code postal')

    parent_city_id = fields.Many2one(
        'microfinance.geo.commune', string='Ville mère',
        domain="[('id', '!=', id)]",
        help="À renseigner uniquement si cette commune est en réalité un "
             "arrondissement d'une ville plus grande (ex: Antananarivo I "
             "-> ville mère Antananarivo). Laisser vide pour une commune "
             "autonome (ex: Fianarantsoa).")
    child_ids = fields.One2many(
        'microfinance.geo.commune', 'parent_city_id', string='Arrondissements')

    district_id = fields.Many2one(
        'microfinance.geo.district', string='District',
        help="District de rattachement, selon le référentiel administratif "
             "officiel (Loi n°2018-011). Nullable : toutes les communes du "
             "référentiel BCM n'ont pas encore été rattachées automatiquement "
             "— voir data/unmatched_ambiguous_report.csv pour les cas "
             "restant à traiter manuellement (noms ambigus ou introuvables "
             "lors du rapprochement automatique).")
    region_id = fields.Many2one(
        related='district_id.region_id', string='Région', store=True,
        readonly=True)

    unit_label = fields.Selection([
        ('commune', 'Commune'),
        ('arrondissement', 'Arrondissement'),
    ], string='Type', compute='_compute_unit_label', store=True,
        help="Calculé automatiquement : 'Arrondissement' si une ville mère "
             "est renseignée, 'Commune' sinon. Ne jamais définir à la main.")

    fokontany_ids = fields.One2many(
        'microfinance.geo.fokontany', 'commune_id', string='Fokontany')
    fokontany_count = fields.Integer(
        string='Nb. fokontany', compute='_compute_fokontany_count')

    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', "Ce code BCM existe déjà."),
    ]

    @api.depends('parent_city_id')
    def _compute_unit_label(self):
        for rec in self:
            rec.unit_label = 'arrondissement' if rec.parent_city_id else 'commune'

    @api.depends('fokontany_ids')
    def _compute_fokontany_count(self):
        for rec in self:
            rec.fokontany_count = len(rec.fokontany_ids)

    @api.depends('name', 'parent_city_id.name', 'code')
    def _compute_display_name(self):
        for rec in self:
            if rec.parent_city_id:
                rec.display_name = f"{rec.parent_city_id.name} / {rec.name}"
            else:
                rec.display_name = rec.name

    @api.constrains('parent_city_id')
    def _check_no_cycle(self):
        for rec in self:
            if not rec._check_recursion():
                raise ValidationError(
                    "Une commune ne peut pas être sa propre ville mère, "
                    "directement ou indirectement.")
