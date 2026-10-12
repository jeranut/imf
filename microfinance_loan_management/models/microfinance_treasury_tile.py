# -*- coding: utf-8 -*-
"""Tuile « Trésorerie d'exploitation » du tableau de bord (Vue d'ensemble), distincte de « Fonds d'exploitation reçus ».

« Fonds d'exploitation reçus » ne compte que les contributions de bailleurs et leurs partages. Cette tuile-ci montre, par
journal d'exploitation de la société courante (nommé par sa banque), ce que dit le compte bancaire : solde en banque
(balance d'ouverture comprise), paiements et encaissements en transit, solde disponible. Aucun montant n'est repris de
la tuile des fonds, et inversement.
"""
from odoo import api, models, _


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    @api.model
    def _get_overview_tiles(self):
        tiles = super()._get_overview_tiles()
        company = self.env.company
        treasury = self._operating_treasury_tiles(company)
        funds = next((t for t in tiles if t['key'] == 'exploitation_funds'), None)
        if treasury:
            treasury = treasury[0]
            if funds:
                # liens croisés entre les deux tuiles, placées côte à côte
                treasury['extra_links'].append({
                    'label': _("Voir les fonds d'exploitation"), 'model': funds['model'], 'domain': funds['domain'],
                    'name': funds['label'], 'views': funds.get('views'),
                })
                tiles.insert(tiles.index(funds) + 1, treasury)
            else:
                anchor = next((i for i, t in enumerate(tiles) if t['key'] == 'exploitation_funds_agency'), None)
                tiles.insert(len(tiles) if anchor is None else anchor + 1, treasury)
        if funds and treasury:
            funds['extra_links'] = [{
                'label': _("Voir la trésorerie d'exploitation"), 'model': 'account.journal',
                'domain': treasury['journals_domain'], 'name': treasury['label'], 'views': False,
            }]
        return tiles

    @api.model
    def _operating_treasury_tiles(self, company):
        from .microfinance_fond_exploitation import GROUP_ACCOUNT_MANAGER, GROUP_COMPTABLE, GROUP_MANAGER, _has_any_group
        Journal = self.env['account.journal']
        if not _has_any_group(self.env, (GROUP_MANAGER, GROUP_COMPTABLE, GROUP_ACCOUNT_MANAGER)) \
                or not Journal.check_access_rights('read', raise_exception=False):
            return []
        holder = {}

        def disponible():
            journals = Journal.search([
                ('company_id', '=', company.id), ('microfinance_usage', '=', 'operating'), ('type', '=', 'bank')],
                order='id')
            holder['journals_domain'] = [('id', 'in', journals.ids)]
            amounts = journals._mf_treasury_amounts()
            items, rows = [], []
            for journal in journals.sudo():
                values = amounts[journal.id]
                bank = journal.microfinance_bank_id.name or journal.name
                base = [('journal_id', '=', journal.id), ('reconciled', '=', False), ('parent_state', '=', 'posted')]
                rows.append(dict(
                    journal_id=journal.id, bank=bank, bank_balance=values['bank'],
                    out_transit=values['out_transit'], in_transit=values['in_transit'],
                    available=values['available']))
                items += [
                    {'label': bank, 'text': True,
                     'link': {'model': 'account.journal', 'res_id': journal.id, 'name': bank}},
                    {'label': _('%s · Solde en banque') % bank, 'value': values['bank']},
                    {'label': _('%s · Paiements en transit') % bank, 'value': values['out_transit'],
                     'link': {'model': 'account.move.line', 'name': _('Paiements en transit - %s') % bank,
                              'domain': base + [('account_id', '=', values['out_account_id'])]}},
                    {'label': _('%s · Encaissements en transit') % bank, 'value': values['in_transit'],
                     'link': {'model': 'account.move.line', 'name': _('Encaissements en transit - %s') % bank,
                              'domain': base + [('account_id', '=', values['in_account_id'])]}},
                    {'label': _('%s · Solde disponible') % bank, 'value': values['available']},
                ]
            holder['items'], holder['rows'] = items, rows
            return sum(row['available'] for row in rows)

        tile = self._overview_tile(
            'operating_treasury', _("Trésorerie d'exploitation"), 'money', 'fa-bank', 'fonds', disponible,
            'account.journal', False, False,
            tooltip=_("Solde réel des comptes bancaires d'exploitation (balance d'ouverture comprise), distinct de "
                      "« Fonds d'exploitation reçus ». Disponible = solde en banque moins paiements en transit non "
                      "rapprochés. Chiffre principal : total disponible."))
        if not tile['error'] and not holder.get('rows'):
            return []   # pas de journal d'exploitation : rien à montrer
        domain = holder.get('journals_domain', [('id', '=', 0)])
        # Pas de lien principal (model/domain) : le chiffre affiché (total disponible) n'est pas un nombre de lignes de
        # la liste ouverte. Les ouvertures sont des liens secondaires : la banque (fiche du journal), « En transit »
        # (lignes concernées) et « Voir les journaux d'exploitation ».
        tile.update({
            'secondary_items': holder.get('items', []), 'journals': holder.get('rows', []),
            'journals_domain': domain,
            'extra_links': [{'label': _("Voir les journaux d'exploitation"), 'model': 'account.journal',
                             'domain': domain, 'name': _("Journaux d'exploitation"), 'views': False}],
        })
        return [tile]
