# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MicrofinanceProvisionRule(models.Model):
    _name = 'microfinance.provision.rule'
    _description = 'Règle de provisionnement selon ancienneté des arriérés'
    _order = 'company_id, min_days'

    name = fields.Char(string='Nom', compute='_compute_name', store=True)
    min_days = fields.Integer(string='Jours de retard min.', required=True, default=0)
    max_days = fields.Integer(string='Jours de retard max. (0 = illimité)', default=0)
    provision_rate = fields.Float(string='Taux de provision (%)', required=True, default=0.0)
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True)

    @api.depends('min_days', 'max_days', 'provision_rate')
    def _compute_name(self):
        for rule in self:
            if rule.max_days:
                rule.name = _('%(min)s-%(max)s jours : %(rate)s%%') % {
                    'min': rule.min_days, 'max': rule.max_days, 'rate': rule.provision_rate,
                }
            else:
                rule.name = _('%(min)s+ jours : %(rate)s%%') % {'min': rule.min_days, 'rate': rule.provision_rate}

    @api.constrains('min_days', 'max_days', 'provision_rate')
    def _check_values(self):
        for rule in self:
            if rule.min_days < 0:
                raise ValidationError(_('Le nombre de jours minimum ne peut pas être négatif.'))
            if rule.max_days and rule.max_days < rule.min_days:
                raise ValidationError(_('Le nombre de jours maximum doit être supérieur ou égal au minimum (ou 0 pour illimité).'))
            if rule.provision_rate < 0 or rule.provision_rate > 100:
                raise ValidationError(_('Le taux de provision doit être compris entre 0 et 100.'))

    @api.constrains('min_days', 'max_days', 'company_id')
    def _check_no_overlap(self):
        for rule in self:
            siblings = self.search([('id', '!=', rule.id), ('company_id', '=', rule.company_id.id)])
            rule_max = rule.max_days or float('inf')
            for other in siblings:
                other_max = other.max_days or float('inf')
                if rule.min_days <= other_max and other.min_days <= rule_max:
                    raise ValidationError(_(
                        'Les tranches de provisionnement ne doivent pas se chevaucher '
                        '(conflit entre "%(rule)s" et "%(other)s").'
                    ) % {'rule': rule.name, 'other': other.name})
