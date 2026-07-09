# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceClientGroupMember(models.Model):
    _name = 'microfinance.client.group.member'
    _description = 'Membre de groupe de clients'

    group_id = fields.Many2one('res.partner', string='Groupe', required=True, ondelete='cascade',
        domain="[('microfinance_client_type', '=', 'group')]")
    member_partner_id = fields.Many2one('res.partner', string='Membre', required=True,
        domain="[('microfinance_client_type', '!=', 'group')]")
    membership_number = fields.Char(string="Nº d'adhésion")
    entry_date = fields.Date(string="Date d'entrée")
    exit_date = fields.Date(string='Date de sortie')
    education_level = fields.Selection([
        ('none', 'Aucun'), ('primary', 'Primaire'), ('secondary', 'Secondaire'), ('higher', 'Supérieur'),
    ], string="Niveau d'éducation")
    currency_id = fields.Many2one('res.currency', related='group_id.currency_id')
    income = fields.Monetary(string='Revenu')
    planned_periodic_savings = fields.Monetary(string='Épargne périodique prévue')
