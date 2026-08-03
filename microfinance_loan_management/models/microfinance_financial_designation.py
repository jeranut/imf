# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceFinancialDesignationIncome(models.Model):
    """Désignation de revenu familial (Section V — Analyse financière), configurée dans
    Configuration > Financement. Valeurs par défaut chargées par hooks._load_financial_data."""
    _name = 'microfinance.financial.designation.income'
    _description = 'Désignation de revenu familial'
    _order = 'sequence, id'

    name = fields.Char(string='Désignation', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    active = fields.Boolean(string='Actif', default=True)


class MicrofinanceFinancialDesignationActivityExpense(models.Model):
    """Désignation de dépense d'activité (Section V), configurée dans Configuration >
    Financement."""
    _name = 'microfinance.financial.designation.activity.expense'
    _description = "Désignation de dépense d'activité"
    _order = 'sequence, id'

    name = fields.Char(string='Désignation', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    active = fields.Boolean(string='Actif', default=True)


class MicrofinanceFinancialDesignationFamilyExpense(models.Model):
    """Désignation de dépense familiale (Section V), configurée dans Configuration >
    Financement."""
    _name = 'microfinance.financial.designation.family.expense'
    _description = 'Désignation de dépense familiale'
    _order = 'sequence, id'

    name = fields.Char(string='Désignation', required=True)
    sequence = fields.Integer(string='Séquence', default=10)
    active = fields.Boolean(string='Actif', default=True)


class MicrofinanceFinancialFrequency(models.Model):
    """Fréquence de saisie des montants (Section V) et son multiplicateur vers le montant
    mensuel équivalent (ex. Hebdomadaire ×4). Configurable librement (Configuration >
    Financement) plutôt que figée dans le code — Micka doit pouvoir ajouter d'autres
    fréquences/multiplicateurs sans intervention développeur."""
    _name = 'microfinance.financial.frequency'
    _description = 'Fréquence de montant (Section V — Analyse financière)'
    _order = 'sequence, id'

    name = fields.Char(string='Fréquence', required=True)
    multiplier = fields.Float(
        string='Multiplicateur', required=True, default=1.0,
        help='Montant mensuel = Montant saisi × ce multiplicateur (ex. 4 pour une fréquence '
             'hebdomadaire : 4 semaines par mois).',
    )
    sequence = fields.Integer(string='Séquence', default=10)
    active = fields.Boolean(string='Actif', default=True)
