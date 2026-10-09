# -*- coding: utf-8 -*-
import csv
import os
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..savings_split_migration import _default_log_dir

RENUMBER_CSV_HEADER = ['produit_id', 'ancien_nom', 'nouveau_nom', 'compte', 'client', 'agence', 'statut']


class MicrofinanceSavingsRenumberWizard(models.TransientModel):
    """Renomme les produits d'épargne au format <numéro du compte>-<rang>. Ne réécrit jamais les
    libellés ni références des écritures comptables existantes : l'ancien nom reste dans
    legacy_number (posé à la migration) pour les retrouver."""
    _name = 'microfinance.savings.renumber.wizard'
    _description = "Renumérotation des produits d'épargne"

    dry_run = fields.Boolean(string='Simulation (aucune écriture)', default=True)
    company_ids = fields.Many2many('res.company', string='Agences', help="Toutes les agences si vide.")
    result_count = fields.Integer(string='Produits concernés', readonly=True)
    result_path = fields.Char(string='Fichier CSV', readonly=True)
    done = fields.Boolean(readonly=True)

    @api.model
    def _target_name(self, product):
        return '%s-%02d' % (product.account_id.name, product.rank)

    def _products_to_rename(self):
        domain = [('account_id', '!=', False), ('rank', '>', 0)]
        if self.company_ids:
            domain.append(('company_id', 'in', self.company_ids.ids))
        products = self.env['microfinance.savings.account'].sudo().search(domain, order='account_id, rank')
        return products.filtered(lambda p: p.name != self._target_name(p))

    def action_run(self):
        self.ensure_one()
        products = self._products_to_rename()
        rows = []
        for product in products:
            new_name, old_name = self._target_name(product), product.name
            if not self.dry_run:
                product.write({'name': new_name, 'legacy_number': product.legacy_number or product.name})
            rows.append({
                'produit_id': product.id, 'ancien_nom': old_name,
                'nouveau_nom': new_name, 'compte': product.account_id.name, 'client': product.partner_id.display_name,
                'agence': product.company_id.display_name, 'statut': 'RENOMME' if not self.dry_run else 'A_RENOMMER',
            })
        path = self._write_csv(rows)
        self.write({'result_count': len(rows), 'result_path': path or '', 'done': True})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def _write_csv(self, rows):
        directory = _default_log_dir()
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(directory, 'renumerotation_produits_epargne_%s_%s_%s.csv' % (
            self.env.cr.dbname, stamp, 'dryrun' if self.dry_run else 'reel'))
        try:
            os.makedirs(directory, exist_ok=True)
            with open(path, 'x', encoding='utf-8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=RENUMBER_CSV_HEADER, delimiter=';')
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            if not self.dry_run:
                raise UserError(_("Trace CSV impossible à écrire (%s) : renumérotation annulée.") % exc)
            return False
        return path
