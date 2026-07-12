# -*- coding: utf-8 -*-
from odoo import fields, models


class MicrofinanceClientRepresentative(models.Model):
    _name = 'microfinance.client.representative'
    _description = 'Représentant / membre du comité (société ou groupe)'

    partner_id = fields.Many2one('res.partner', string='Client (société/groupe)', required=True,
        ondelete='cascade', domain="[('microfinance_client_type', 'in', ['company', 'group'])]")
    name = fields.Char(string='Nom', required=True)
    role = fields.Selection([
        ('legal_representative', 'Représentant légal'),
        ('president', 'Président'),
        ('secretary', 'Secrétaire'),
        ('treasurer', 'Trésorier'),
        ('member', 'Membre du comité'),
        ('other', 'Autre'),
    ], string='Fonction', required=True, default='member')
    id_card_number = fields.Char(string="N° pièce d'identité")
    account_authorization = fields.Boolean(string='Habilité à opérer le compte')
    phone = fields.Char(string='Téléphone')
    email = fields.Char(string='Email')
