# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceSocialScoreBracket(models.Model):
    _name = 'microfinance.social.score.bracket'
    _description = "Tranche de notation sociale"
    _order = 'category, sequence'
    _rec_name = 'label'

    _sql_constraints = [
        ('category_company_sequence_unique', 'unique(category, company_id, sequence)',
         "Une tranche avec cette note existe déjà pour cette catégorie et cette société."),
    ]

    company_id = fields.Many2one(
        'res.company', string='Société', required=True, default=lambda self: self.env.company)
    category = fields.Selection([
        ('assets', 'Actifs / Patrimoine'),
        ('food', 'Alimentation'),
        ('activity', 'Activité'),
        ('health', 'Santé'),
        ('income', 'Revenus (bénéfice net du ménage)'),
        ('housing_state', 'Habitat — état du toit'),
        ('housing_surface', 'Habitat — surface'),
        ('education_borrower', "Niveau d'éducation du candidat emprunteur"),
        ('education_children', 'Éducation des enfants'),
    ], string='Catégorie', required=True)
    # Note attribuée si la tranche est sélectionnée. Commence à 0 pour housing_state et
    # education_borrower (0 est une séquence valide, pas "pas de tranche" — cf. les composants
    # microfinance_loan_application.py qui la lisent : distinguer 0 d'un bracket_id vide via la
    # présence du Many2one, pas via la valeur de sequence).
    sequence = fields.Integer(string='Note attribuée', required=True)
    is_amount_based = fields.Boolean(
        string='Basée sur un montant',
        help="Coché : le libellé est généré automatiquement à partir du seuil ci-dessous. "
             "Décoché : le libellé est saisi librement.")
    threshold_amount = fields.Monetary(
        string='Seuil (≤)', currency_field='currency_id',
        help="Utilisé uniquement si 'Basée sur un montant' est coché. Vide/0 sur la dernière "
             "tranche = pas de plafond.")
    currency_id = fields.Many2one(related='company_id.currency_id')
    label = fields.Char(
        string='Libellé', compute='_compute_label', inverse='_inverse_label', store=True,
        help="Généré automatiquement pour les tranches basées sur un montant ; libre sinon.")

    _AMOUNT_LABEL_SUFFIX = {
        'income': ' par mois et UC',
    }

    @api.depends('is_amount_based', 'threshold_amount', 'category', 'sequence', 'company_id')
    def _compute_label(self):
        for bracket in self:
            if not bracket.is_amount_based:
                continue  # libellé saisi manuellement, ne pas écraser
            previous = self.search([
                ('category', '=', bracket.category),
                ('company_id', '=', bracket.company_id.id),
                ('sequence', '<', bracket.sequence),
            ], order='sequence desc', limit=1)
            symbol = bracket.currency_id.symbol or 'Ar'
            suffix = self._AMOUNT_LABEL_SUFFIX.get(bracket.category, '')
            fmt = lambda v: f'{v:,.0f}'.replace(',', ' ')
            if not bracket.threshold_amount:
                bracket.label = (
                    f'{bracket.sequence}. > {fmt(previous.threshold_amount)} {symbol}{suffix}'
                    if previous else f'{bracket.sequence}.'
                )
            elif previous:
                bracket.label = (
                    f'{bracket.sequence}. > {fmt(previous.threshold_amount)} et '
                    f'≤ {fmt(bracket.threshold_amount)} {symbol}{suffix}'
                )
            else:
                bracket.label = f'{bracket.sequence}. ≤ {fmt(bracket.threshold_amount)} {symbol}{suffix}'

    def _inverse_label(self):
        pass  # permet la saisie libre du libellé quand is_amount_based=False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._recompute_category_labels()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'threshold_amount', 'sequence', 'is_amount_based', 'category'} & set(vals):
            self._recompute_category_labels()
        return res

    def _recompute_category_labels(self):
        # Le label d'une tranche basée sur un montant dépend de la tranche PRÉCÉDENTE de la
        # même catégorie/société (cf. _compute_label) : @api.depends ne peut pas suivre cette
        # dépendance inter-enregistrements, donc un changement de seuil sur une tranche doit
        # explicitement redéclencher le recalcul de toute sa catégorie (pas seulement la
        # tranche modifiée), sous peine de libellés désynchronisés sur les tranches suivantes.
        seen = set()
        for record in self:
            key = (record.category, record.company_id.id)
            if key in seen:
                continue
            seen.add(key)
            siblings = self.search([
                ('category', '=', record.category), ('company_id', '=', record.company_id.id),
            ])
            siblings._compute_label()
