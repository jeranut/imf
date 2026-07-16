# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceBailleurFonds(models.Model):
    _name = 'microfinance.bailleur.fonds'
    _description = 'Bailleur de fonds microfinance'
    _order = 'name'

    partner_id = fields.Many2one(
        'res.partner', string='Contact', required=True, ondelete='restrict', copy=False,
        domain="[('microfinance_partner_type', '=', 'bailleur')]",
        help="Fiche res.partner associée (type 'Bailleur de fonds'), créée automatiquement à la "
             "création de ce bailleur si aucun contact existant n'est sélectionné. Permet de "
             "retrouver le bailleur comme tout autre contact de l'instance (adresse, historique "
             "Discuss, etc.), tout en gardant ce référentiel métier léger.",
    )
    name = fields.Char(
        string='Nom du bailleur', related='partner_id.name', store=True, readonly=False, required=True,
    )
    code = fields.Char(string='Code')
    active = fields.Boolean(string='Actif', default=True)
    note = fields.Text(string='Remarques')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('partner_id'):
                # sudo() : la création du bailleur est ouverte à group_microfinance_manager
                # (ir.model.access.csv), qui n'a pas nécessairement de droit de création propre
                # sur res.partner selon l'affectation de groupes de l'utilisateur — le partner
                # créé ici est un sous-produit technique du bailleur, pas une création directe
                # de contact par l'utilisateur.
                partner = self.env['res.partner'].sudo().create({
                    'name': vals.get('name') or 'Nouveau bailleur',
                    'microfinance_partner_type': 'bailleur',
                    'company_id': False,  # référentiel partagé entre agences, comme le bailleur lui-même
                })
                vals['partner_id'] = partner.id
                # name est related=partner_id.name : pas besoin de le dupliquer dans vals,
                # mais le laisser si fourni ne pose pas de problème (super().create() écrira
                # sur le related, donc sur le partner qu'on vient de créer avec le même nom).
        return super().create(vals_list)
