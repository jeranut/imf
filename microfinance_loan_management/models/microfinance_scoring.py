# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceScoringProfile(models.Model):
    _name = 'microfinance.scoring.profile'
    _description = 'Profil de scoring crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'product_id, name'

    name = fields.Char(string='Nom', required=True, tracking=True)
    active = fields.Boolean(string='Actif', default=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True, tracking=True)
    product_id = fields.Many2one(
        'microfinance.loan.product',
        string='Produit de crédit',
        domain="[('company_id', '=', company_id)]",
        tracking=True,
        help='Laisser vide pour créer un profil générique de la société.',
    )
    min_score = fields.Float(string='Score minimum', default=0.0, required=True)
    max_score = fields.Float(string='Score maximum', default=100.0, required=True)
    approve_threshold = fields.Float(string="Seuil d'approbation", default=70.0, required=True)
    manual_review_threshold = fields.Float(string='Seuil de revue manuelle', default=45.0, required=True)
    reject_threshold = fields.Float(string='Seuil de rejet', default=45.0, required=True)
    rule_ids = fields.One2many('microfinance.scoring.rule', 'profile_id', string='Règles')

    @api.constrains('active', 'company_id', 'product_id')
    def _check_single_active_profile(self):
        for profile in self.filtered('active'):
            domain = [
                ('id', '!=', profile.id),
                ('active', '=', True),
                ('company_id', '=', profile.company_id.id),
                ('product_id', '=', profile.product_id.id if profile.product_id else False),
            ]
            if self.search_count(domain):
                raise ValidationError(_('Un profil de scoring actif existe déjà pour cette société et ce produit.'))

    @api.constrains('min_score', 'max_score', 'approve_threshold', 'manual_review_threshold', 'reject_threshold')
    def _check_thresholds(self):
        for profile in self:
            if profile.min_score >= profile.max_score:
                raise ValidationError(_('Le score minimum doit être inférieur au score maximum.'))
            for field_name in ('approve_threshold', 'manual_review_threshold', 'reject_threshold'):
                value = profile[field_name]
                if value < profile.min_score or value > profile.max_score:
                    raise ValidationError(_('Les seuils doivent être compris entre le score minimum et le score maximum.'))
            if profile.approve_threshold < profile.manual_review_threshold:
                raise ValidationError(_('Le seuil de recommandation doit être supérieur ou égal au seuil de revue manuelle.'))


class MicrofinanceScoringRule(models.Model):
    _name = 'microfinance.scoring.rule'
    _description = 'Règle de scoring crédit microfinance'
    _order = 'profile_id, sequence, id'

    METRIC_SELECTION = [
        ('baseline', 'Constante (valeur 1, pour un score de base)'),
        ('total_loans', 'Total crédits'),
        ('active_loans', 'Crédits actifs'),
        ('closed_loans', 'Crédits clôturés'),
        ('defaulted_loans', 'Crédits en défaut'),
        ('overdue_installments', 'Échéances en retard'),
        ('max_days_overdue', 'Maximum jours de retard'),
        ('average_days_overdue', 'Moyenne jours de retard'),
        ('repayment_rate', 'Taux de remboursement'),
        ('total_borrowed_amount', 'Montant total emprunté'),
        ('total_paid_amount', 'Montant total payé'),
        ('partial_payment_count', 'Nombre paiements partiels'),
        ('customer_age_months', 'Ancienneté client en mois'),
        ('loan_overdue_installment_count', 'Échéances en retard (ce crédit)'),
        ('loan_max_days_overdue', 'Maximum jours de retard (ce crédit)'),
        ('loan_overdue_amount_ratio', 'Montant en retard / montant crédit en % (ce crédit)'),
        ('loan_partial_payment_count', 'Paiements partiels (ce crédit)'),
    ]

    OPERATOR_SELECTION = [
        ('=', '='),
        ('!=', '!='),
        ('>', '>'),
        ('>=', '>='),
        ('<', '<'),
        ('<=', '<='),
        ('between', 'between'),
    ]

    COMPUTATION_SELECTION = [
        ('threshold', 'Seuil (points fixes si la condition est vraie)'),
        ('linear', 'Linéaire (points par unité de la métrique, condition ignorée)'),
    ]

    profile_id = fields.Many2one('microfinance.scoring.profile', string='Profil de scoring', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='profile_id.company_id', store=True, readonly=True)
    name = fields.Char(string='Nom', required=True)
    active = fields.Boolean(string='Actif', default=True)
    sequence = fields.Integer(string='Séquence', default=10)
    metric = fields.Selection(METRIC_SELECTION, string='Métrique', required=True)
    computation = fields.Selection(
        COMPUTATION_SELECTION, required=True, default='threshold', string='Mode de calcul',
        help="Seuil : les points sont appliqués tels quels si la métrique respecte l'opérateur/la valeur. "
             "Linéaire : les points sont multipliés par la valeur de la métrique (opérateur/valeur ignorés).",
    )
    operator = fields.Selection(OPERATOR_SELECTION, string='Opérateur', default='>=')
    value = fields.Char(string='Valeur', help='Pour between, saisir deux nombres séparés par une virgule, par exemple : 10,30.')
    points = fields.Float(string='Points', required=True, default=0.0)
    rule_type = fields.Selection([('bonus', 'Bonus'), ('malus', 'Malus')], string='Type de règle', required=True, default='bonus')
    description = fields.Text(string='Description')

    @api.constrains('computation', 'operator', 'value')
    def _check_rule_value(self):
        for rule in self:
            if rule.computation == 'threshold':
                if not rule.operator or not (rule.value or '').strip():
                    raise ValidationError(_('Un opérateur et une valeur sont requis pour une règle à seuil.'))
                rule._parse_value()

    def _parse_value(self):
        self.ensure_one()
        raw_value = (self.value or '').strip()
        if self.operator == 'between':
            parts = [part.strip() for part in raw_value.replace('..', ',').replace(';', ',').split(',') if part.strip()]
            if len(parts) != 2:
                raise ValidationError(_('La valeur between doit contenir deux nombres, par exemple 10,30.'))
            try:
                lower, upper = float(parts[0]), float(parts[1])
            except ValueError as error:
                raise ValidationError(_('La valeur de scoring doit être numérique.')) from error
            if lower > upper:
                raise ValidationError(_('La borne basse doit être inférieure ou égale à la borne haute.'))
            return lower, upper
        try:
            return float(raw_value)
        except ValueError as error:
            raise ValidationError(_('La valeur de scoring doit être numérique.')) from error

    def _matches(self, metric_value):
        self.ensure_one()
        if self.computation == 'linear':
            return True
        expected = self._parse_value()
        if self.operator == 'between':
            return expected[0] <= metric_value <= expected[1]
        if self.operator == '=':
            return metric_value == expected
        if self.operator == '!=':
            return metric_value != expected
        if self.operator == '>':
            return metric_value > expected
        if self.operator == '>=':
            return metric_value >= expected
        if self.operator == '<':
            return metric_value < expected
        if self.operator == '<=':
            return metric_value <= expected
        return False

    def _get_points(self, metric_value):
        self.ensure_one()
        points = abs(self.points or 0.0)
        if self.computation == 'linear':
            points *= metric_value
        return points if self.rule_type == 'bonus' else -points


class MicrofinanceScoringLine(models.Model):
    _name = 'microfinance.scoring.line'
    _description = 'Historique scoring crédit microfinance'
    _order = 'loan_id, id'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    rule_id = fields.Many2one('microfinance.scoring.rule', string='Règle', readonly=True, ondelete='set null')
    metric_value = fields.Float(string='Valeur de la métrique', readonly=True)
    points_applied = fields.Float(string='Points appliqués', readonly=True)
    note = fields.Char(string='Note', readonly=True)
