# -*- coding: utf-8 -*-
"""Tuile compacte « Trésorerie » de la Vue d'ensemble : REMPLACE l'ancienne tuile « Trésorerie d'exploitation » (une
ligne par banque, illisible au-delà de 4 ou 5 banques). Le détail est dans l'onglet « Trésorerie » du tableau de bord.

« Fonds d'exploitation reçus » reste inchangée (argent des bailleurs, calculé sur les contributions et les partages
seulement) ; elle reçoit seulement un lien vers l'onglet, filtré sur l'usage Exploitation.
"""
from odoo import api, models, _


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    @api.model
    def _get_overview_tiles(self):
        tiles = super()._get_overview_tiles()
        treasury = self._treasury_overview_tile()
        funds = next((t for t in tiles if t['key'] == 'exploitation_funds'), None)
        if treasury:
            if funds:
                tiles.insert(tiles.index(funds) + 1, treasury)
            else:
                anchor = next((i for i, t in enumerate(tiles) if t['key'] == 'exploitation_funds_agency'), None)
                tiles.insert(len(tiles) if anchor is None else anchor + 1, treasury)
        if funds and treasury:
            funds['extra_links'] = [{
                'label': _("Voir la trésorerie d'exploitation"), 'topic': 'tresorerie', 'usage': 'operating'}]
        return tiles

    @api.model
    def _treasury_overview_tile(self):
        if not self._treasury_has_rights():
            return None
        holder = {}

        def available():
            rows = self._treasury_rows()[0]
            holder['watch'] = sum(1 for row in rows if row['watch'])
            holder['late'] = sum(1 for row in rows if row['late'])
            holder['count'] = len(rows)
            return sum(row['available'] for row in rows)

        tile = self._overview_tile(
            'treasury_overview', _('Trésorerie'), 'money', 'fa-bank', 'fonds', available,
            tooltip=_("Disponible total de tous les comptes bancaires (solde en banque moins sorties en transit "
                      "non rapprochées). Distinct de « Fonds d'exploitation reçus »."))
        if not tile['error'] and not holder.get('count'):
            return None
        tile['secondary_items'] = [{
            'label': _('%(watch)s comptes à surveiller · %(late)s relevés à saisir') % {
                'watch': holder.get('watch', 0), 'late': holder.get('late', 0)},
            'text': True}]
        tile['counts'] = {'watch': holder.get('watch', 0), 'late': holder.get('late', 0)}
        tile['extra_links'] = [{'label': _('Voir la trésorerie'), 'topic': 'tresorerie', 'usage': ''}]
        return tile
