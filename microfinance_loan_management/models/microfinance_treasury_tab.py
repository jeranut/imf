# -*- coding: utf-8 -*-
"""Onglet « Trésorerie » du tableau de bord Ampaly : données (une ligne par journal bancaire), bande espèces/mobile money
et réglages de société.

LECTURE SEULE : aucune écriture, aucun relevé, aucun flux comptable n'est créé ou modifié. Calcul AGRÉGÉ (read_group
sur les lignes comptabilisées groupées par journal et compte, sur les relevés groupés par journal) : le nombre de
requêtes ne dépend pas du nombre de banques. Le solde, les sorties (139500) et les encaissements (139100) en transit
viennent de account.journal._mf_treasury_amounts (mf_operating_treasury.py), non dupliqué.

Droits : direction du siège, gestionnaire comptable et chef d'agence (groupes Manager crédit / Comptable / Responsable
comptabilité) ; jamais le caissier. Les sociétés lues sont celles du sélecteur (env.companies : Odoo refuse une société
que l'utilisateur n'a pas). Les journaux d'usage « fund » ne sont visibles que de la société mère.
"""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

# La caisse (cash) et Mvola (mobile) ont leur propre bande : jamais des comptes du tableau.
TREASURY_EXCLUDED_USAGES = ['cash', 'mobile']


class ResCompany(models.Model):
    _inherit = 'res.company'

    mf_treasury_watch_pct = fields.Integer(
        string="Seuil « À surveiller » (%)", default=10,
        help="Un compte est « À surveiller » quand son solde est positif et que son disponible (solde moins sorties en "
             "transit) est inférieur ou égal à ce pourcentage du solde, ou quand il est négatif.")
    mf_treasury_statement_days = fields.Integer(
        string="Jours sans relevé avant alerte", default=7,
        help="Un compte est « Relevé en retard » quand son dernier relevé validé date de plus de ce nombre de jours (ou "
             "qu'il n'en a aucun) ET qu'il a des écritures postérieures à la fin de ce relevé.")
    mf_treasury_receivable_days = fields.Integer(
        string="Ancienneté d'un montant à recevoir (jours)", default=7,
        help="Un encaissement en transit (139100) plus ancien que ce nombre de jours est compté dans « dont X depuis "
             "plus de N jours » de la tuile « À recevoir ».")


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mf_treasury_watch_pct = fields.Integer(related='company_id.mf_treasury_watch_pct', readonly=False)
    mf_treasury_statement_days = fields.Integer(related='company_id.mf_treasury_statement_days', readonly=False)
    mf_treasury_receivable_days = fields.Integer(related='company_id.mf_treasury_receivable_days', readonly=False)


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    @api.model
    def _treasury_has_rights(self):
        from .microfinance_fond_exploitation import GROUP_ACCOUNT_MANAGER, GROUP_COMPTABLE, GROUP_MANAGER, _has_any_group
        return _has_any_group(self.env, (GROUP_MANAGER, GROUP_COMPTABLE, GROUP_ACCOUNT_MANAGER))

    @api.model
    def _treasury_check(self):
        """Refus (AccessError) du caissier et de tout utilisateur sans droit de trésorerie. `env.companies` lève
        lui-même AccessError pour une société que l'utilisateur n'a pas (allowed_company_ids falsifié)."""
        if not self._treasury_has_rights():
            raise AccessError(_("La trésorerie est réservée à la direction, à la comptabilité et aux chefs d'agence."))
        return self.env.companies

    @api.model
    def get_dashboard_data(self, portfolio_id=None):
        data = super().get_dashboard_data(portfolio_id)
        if isinstance(data, dict):
            try:
                self._treasury_check()
                data['treasury_visible'] = True
            except AccessError:
                data['treasury_visible'] = False
        return data

    # ------------------------------------------------------------------ lignes (une par journal bancaire)
    @api.model
    def _treasury_rows(self):
        """(lignes, journaux espèces/mobile) des sociétés du sélecteur. Une ligne par journal bancaire hors espèces et
        mobile money ; les journaux de fonds seulement pour la société mère."""
        companies = self._treasury_check()
        env = self.env
        today = fields.Date.context_today(self)
        settings = env.company
        watch_ratio = (settings.mf_treasury_watch_pct or 0) / 100.0
        statement_days = settings.mf_treasury_statement_days or 0
        receivable_days = settings.mf_treasury_receivable_days or 0
        parent = env['res.company']._get_microfinance_parent()
        Journal = env['account.journal'].sudo()
        domain = [('company_id', 'in', companies.ids), ('type', '=', 'bank'),
                  ('microfinance_usage', 'not in', TREASURY_EXCLUDED_USAGES)]
        journals = Journal.search(domain, order='company_id, id')
        journals = journals.filtered(
            lambda j: j.microfinance_usage != 'fund' or (parent and j.company_id == parent))
        band_journals = Journal.search([
            ('company_id', 'in', companies.ids), ('microfinance_usage', 'in', TREASURY_EXCLUDED_USAGES)],
            order='company_id, id')
        amounts = (journals | band_journals)._mf_treasury_amounts()
        Line = env['account.move.line'].sudo()
        # sorties/entrées : montant ancien (> N jours) à recevoir
        old_in = {}
        in_accounts = {amounts[j.id]['in_account_id'] for j in journals if amounts[j.id]['in_account_id']}
        if journals and in_accounts:
            cutoff = today - timedelta(days=receivable_days)
            for group in Line.read_group(
                    [('journal_id', 'in', journals.ids), ('account_id', 'in', list(in_accounts)),
                     ('reconciled', '=', False), ('parent_state', '=', 'posted'), ('date', '<', cutoff)],
                    ['amount_residual:sum'], ['journal_id', 'account_id'], lazy=False):
                key = (group['journal_id'][0], group['account_id'][0])
                old_in[key] = group['amount_residual']
        # dernier relevé validé par journal
        last_statement = {}
        if journals:
            for group in env['account.bank.statement'].sudo().read_group(
                    [('journal_id', 'in', journals.ids), ('mf_state', '=', 'validated')],
                    ['mf_date_to:max'], ['journal_id'], lazy=False):
                last_statement[group['journal_id'][0]] = fields.Date.to_date(group['mf_date_to'])
        # dernière écriture comptabilisée sur le compte bancaire (tous journaux) ou les comptes d'attente du journal
        pending = {j.id: j._mf_pending_accounts() for j in journals}
        watched_accounts = {j.default_account_id.id for j in journals if j.default_account_id}
        for accounts in pending.values():
            watched_accounts.update(accounts.ids)
        account_last, journal_account_last = {}, {}
        if watched_accounts:
            for group in Line.read_group(
                    [('account_id', 'in', list(watched_accounts)), ('parent_state', '=', 'posted')],
                    ['date:max'], ['journal_id', 'account_id'], lazy=False):
                last_date = fields.Date.to_date(group['date'])
                account_id = group['account_id'][0]
                journal_account_last[(group['journal_id'][0], account_id)] = last_date
                if last_date and (account_id not in account_last or last_date > account_last[account_id]):
                    account_last[account_id] = last_date
        rows = []
        for journal in journals:
            values = amounts[journal.id]
            bank_id = values['bank_account_id']
            last_move = account_last.get(bank_id)
            for account in pending[journal.id]:
                moved = journal_account_last.get((journal.id, account.id))
                if moved and (not last_move or moved > last_move):
                    last_move = moved
            last_end = last_statement.get(journal.id)
            days = (today - last_end).days if last_end else None
            has_later = bool(last_move and (not last_end or last_move > last_end))
            late = bool(has_later and (last_end is None or days > statement_days))
            bank, out_transit = values['bank'], values['out_transit']
            available = values['available']
            watch = bool(bank < 0 or available < 0 or (bank > 0 and available <= bank * watch_ratio))
            bank_rec = journal.microfinance_bank_id
            rows.append({
                'journal_id': journal.id, 'journal_name': journal.name,
                'company_id': journal.company_id.id, 'company_name': journal.company_id.name,
                'bank_id': bank_rec.id or False, 'bank_name': bank_rec.name or journal.name,
                'usage': journal.microfinance_usage or '',
                'account_id': bank_id, 'account_name': journal.default_account_id.display_name or '',
                'out_account_id': values['out_account_id'], 'in_account_id': values['in_account_id'],
                'bank_balance': bank, 'out_transit': out_transit, 'in_transit': values['in_transit'],
                'in_transit_old': old_in.get((journal.id, values['in_account_id']), 0.0),
                'available': available,
                'last_statement_date': fields.Date.to_string(last_end) if last_end else False,
                'last_statement_days': days, 'watch': watch, 'late': late,
            })
        return rows, band_journals, amounts

    @api.model
    def _treasury_band(self, band_journals, amounts):
        """Bande « Espèces et mobile money » : solde des journaux d'usage cash / mobile et état du dernier comptage."""
        env = self.env
        Comptage = env['microfinance.caisse.comptage'].sudo()
        latest = {}
        if band_journals:
            companies = band_journals.company_id
            groups = Comptage.read_group([('company_id', 'in', companies.ids)], ['date:max'], ['company_id'], lazy=False)
            maxima = {g['company_id'][0]: g['date'] for g in groups}
            if maxima:
                for comptage in Comptage.search([('company_id', 'in', list(maxima)), ('date', 'in', list(maxima.values()))],
                                                order='id desc'):
                    if comptage.date == maxima.get(comptage.company_id.id):
                        latest.setdefault(comptage.company_id.id, comptage)
        items = []
        for journal in band_journals:
            item = {'kind': journal.microfinance_usage, 'journal_id': journal.id, 'name': journal.name,
                    'company_id': journal.company_id.id, 'company_name': journal.company_id.name,
                    'account_id': amounts[journal.id]['bank_account_id'], 'balance': amounts[journal.id]['bank'],
                    'count': None}
            if journal.microfinance_usage == 'cash':
                comptage = latest.get(journal.company_id.id)
                if comptage:
                    variance = comptage.variance
                    item['count'] = {'date': fields.Datetime.to_string(comptage.date), 'variance': variance,
                                     'ok': abs(variance) < 0.01}
            items.append(item)
        return items

    @api.model
    def get_treasury_data(self):
        """UN appel par ouverture de l'onglet : toutes les lignes (le filtre usage / recherche / regroupement se fait
        dans le navigateur sur ces lignes), la bande espèces/mobile et les réglages."""
        rows, band_journals, amounts = self._treasury_rows()
        env = self.env
        usage_labels = dict(env['account.journal']._fields['microfinance_usage'].selection)
        shown = {row['usage'] for row in rows}
        usages = [{'id': key, 'label': usage_labels[key]} for key in usage_labels
                  if key not in TREASURY_EXCLUDED_USAGES and (key != 'fund' or 'fund' in shown or self._treasury_fund_visible())]
        if any(not row['usage'] for row in rows):
            usages.append({'id': '__other', 'label': _('Autre')})
        company = env.company
        return {
            'currency': company.currency_id.symbol or '',
            'usages': usages, 'rows': rows, 'band': self._treasury_band(band_journals, amounts),
            'settings': {'watch_pct': company.mf_treasury_watch_pct, 'statement_days': company.mf_treasury_statement_days,
                         'receivable_days': company.mf_treasury_receivable_days},
            'multi_company': len(env.companies) > 1,
        }

    @api.model
    def _treasury_fund_visible(self):
        parent = self.env['res.company']._get_microfinance_parent()
        return bool(parent) and parent in self.env.companies
