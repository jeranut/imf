# -*- coding: utf-8 -*-
"""Contrôle des journaux interactif : même famille d'écrans que le Grand livre (dont on réutilise les domaines de période,
de société et de pièces, donc les mêmes totaux). Totaux et compteurs par journal en agrégats ; les pièces d'un journal
et les lignes d'une pièce ne sont lues qu'au dépliage. Aucun sudo : les règles d'accès et de société s'appliquent.

Anomalies : pièces déséquilibrées, brouillons, pièces annulées, trous de numérotation (information : un trou signale une
pièce supprimée ou un numéro consommé). Les pièces manuelles sur un journal de banque ou de caisse ne sont PAS contrôlées :
rien ne distingue de façon fiable une pièce d'Ampaly d'une saisie manuelle (plusieurs flux d'Ampaly, p. ex. l'écart de
caisse d'un comptage ou d'anciens dépôts de bailleurs, n'ont ni lien d'origine ni ligne de relevé)."""
from odoo import api, models

PAGE_SIZE = 80
MAX_MISSING = 200  # numéros manquants listés par préfixe ; le reste est résumé par le compteur
ANOMALY_KINDS = ('unbalanced', 'draft', 'cancel')
MOVE_ORDERS = {
    'sort_date': 'date, id',
    'sort_number': 'sequence_prefix, sequence_number, id',
}
STATE_LABELS = {'draft': 'Brouillon', 'posted': 'Comptabilisée', 'cancel': 'Annulée'}


class AccountJournalControlReport(models.AbstractModel):
    _name = 'account.journal.control.report'
    _inherit = 'account.general.ledger.report'
    _description = 'Contrôle des journaux (écran interactif)'

    # ------------------------------------------------------------------ domaines
    @api.model
    def _move_domain(self, company, journal_ids, date_from, date_to, search=None, states=None):
        domain = [('company_id', '=', company.id)]
        if journal_ids:
            domain.append(('journal_id', 'in', journal_ids))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if states:
            domain.append(('state', 'in', states))
        if search:
            domain.append(('name', 'ilike', search))
        return domain

    @api.model
    def _shown_states(self, target_move):
        return ['posted'] if target_move != 'all' else ['draft', 'posted']

    @api.model
    def _line_domain(self, company, journal_ids, date_from, date_to, target_move, search=None):
        domain = self._period_domain(company, journal_ids, date_from, date_to, target_move)
        if search:
            domain.append(('move_id.name', 'ilike', search))
        return domain

    # ------------------------------------------------------------------ agrégats par journal
    @api.model
    def _lines_by_journal(self, domain):
        groups = self.env['account.move.line'].read_group(domain, ['debit:sum', 'credit:sum'], ['journal_id'], lazy=False)
        return {g['journal_id'][0]: (g['debit'] or 0.0, g['credit'] or 0.0) for g in groups if g['journal_id']}

    @api.model
    def _moves_by_journal(self, domain):
        groups = self.env['account.move'].read_group(domain, ['journal_id'], ['journal_id'], lazy=False)
        return {g['journal_id'][0]: g['__count'] for g in groups if g['journal_id']}

    @api.model
    def _unbalanced_by_journal(self, company, line_domain):
        """Nombre de pièces dont le débit diffère du crédit, par journal : une seule requête agrégée, règles d'accès
        appliquées (lecture seule)."""
        MoveLine = self.env['account.move.line']
        query = MoveLine._where_calc(line_domain)
        MoveLine._apply_ir_rules(query, 'read')
        from_clause, where_clause, params = query.get_sql()
        self.env.cr.execute(
            'SELECT t.journal_id, COUNT(*) FROM ('
            'SELECT "account_move_line".move_id, "account_move_line".journal_id FROM ' + from_clause +
            ' WHERE ' + where_clause + ' GROUP BY 1, 2 '
            'HAVING ABS(SUM("account_move_line".debit) - SUM("account_move_line".credit)) >= %s) t GROUP BY t.journal_id',
            params + [company.currency_id.rounding / 2.0])
        return dict(self.env.cr.fetchall())

    @api.model
    def _numbering_gaps(self, company, journal_ids, date_from, date_to, search=None):
        """Trous de numérotation par (journal, préfixe) sur la période : numéros manquants entre le premier et le
        dernier numéro consommé. Toutes les pièces numérotées comptent (brouillon et annulées gardent leur numéro)."""
        domain = self._move_domain(company, journal_ids, date_from, date_to, search) + [
            ('sequence_number', '>', 0), ('name', '!=', '/')]
        Move = self.env['account.move']
        groups = Move.read_group(domain, ['seq_min:min(sequence_number)', 'seq_max:max(sequence_number)',
                                         'seq_used:count_distinct(sequence_number)'],
                                 ['journal_id', 'sequence_prefix'], lazy=False)
        gaps = {}
        for g in groups:
            low, high, used = g['seq_min'], g['seq_max'], g['seq_used']
            if not g['journal_id'] or not low or high - low + 1 <= used:
                continue
            numbers = {m['sequence_number'] for m in Move.search_read(g['__domain'], ['sequence_number'])}
            missing = [n for n in range(low, high + 1) if n not in numbers]
            prefix = g['sequence_prefix'] or ''
            gaps.setdefault(g['journal_id'][0], []).append({
                'prefix': prefix, 'count': len(missing), 'missing': missing[:MAX_MISSING],
                'labels': ['%s%s' % (prefix, str(n).zfill(5)) for n in missing[:MAX_MISSING]]})
        return gaps

    # ------------------------------------------------------------------ une ligne par journal
    @api.model
    def get_journals(self, company, journal_ids, date_from, date_to, target_move, search=None):
        currency = company.currency_id
        line_domain = self._line_domain(company, journal_ids, date_from, date_to, target_move, search)
        sums = self._lines_by_journal(line_domain)
        shown = self._shown_states(target_move)
        counts = self._moves_by_journal(self._move_domain(company, journal_ids, date_from, date_to, search, shown))
        drafts = (self._moves_by_journal(self._move_domain(company, journal_ids, date_from, date_to, search, ['draft']))
                  if target_move == 'all' else {})
        cancelled = self._moves_by_journal(self._move_domain(company, journal_ids, date_from, date_to, search, ['cancel']))
        unbalanced = self._unbalanced_by_journal(company, line_domain)
        gaps = self._numbering_gaps(company, journal_ids, date_from, date_to, search)
        type_labels = dict(self.env['account.journal']._fields['type']._description_selection(self.env))
        journal_domain = [('company_id', '=', company.id)]
        if journal_ids:
            journal_domain.append(('id', 'in', journal_ids))
        rows = []
        for journal in self.env['account.journal'].with_context(active_test=False).search(journal_domain, order='code, id'):
            debit, credit = sums.get(journal.id, (0.0, 0.0))
            anomalies = {
                'unbalanced': unbalanced.get(journal.id, 0), 'draft': drafts.get(journal.id, 0),
                'cancel': cancelled.get(journal.id, 0),
                'gaps': sum(g['count'] for g in gaps.get(journal.id, [])),
            }
            count = counts.get(journal.id, 0)
            if not (count or anomalies['cancel']):
                continue
            rows.append({
                'id': journal.id, 'code': journal.code, 'name': journal.name, 'type': type_labels.get(journal.type, ''),
                'count': count, 'debit': currency.round(debit), 'credit': currency.round(credit),
                'gap': currency.round(debit - credit), 'anomalies': anomalies, 'gap_details': gaps.get(journal.id, []),
                'status': 'anomaly' if anomalies['unbalanced'] else ('info' if any(anomalies.values()) else 'ok'),
            })
        totals = {key: currency.round(sum(r[key] for r in rows)) for key in ('debit', 'credit')}
        totals['count'] = sum(r['count'] for r in rows)
        totals['gap'] = currency.round(totals['debit'] - totals['credit'])
        totals['anomalies'] = {k: sum(r['anomalies'][k] for r in rows) for k in ('unbalanced', 'draft', 'cancel', 'gaps')}
        return {'journals': rows, 'totals': totals, 'balanced': currency.is_zero(totals['gap'])}

    # ------------------------------------------------------------------ pièces d'un journal (pages de 80)
    @api.model
    def get_moves(self, company, journal_id, date_from, date_to, target_move, sortby='sort_date', search=None,
                  anomaly=None, offset=0, limit=PAGE_SIZE):
        empty = {'rows': [], 'total_rows': 0, 'offset': offset, 'has_more': False}
        journal = self.env['account.journal'].with_context(active_test=False).search(
            [('id', '=', journal_id), ('company_id', '=', company.id)], limit=1)
        if not journal:
            return empty
        currency = company.currency_id
        states = {'draft': ['draft'], 'cancel': ['cancel']}.get(anomaly) or self._shown_states(target_move)
        domain = self._move_domain(company, [journal.id], date_from, date_to, search, states)
        Move = self.env['account.move']
        if anomaly == 'unbalanced':
            ids = self._unbalanced_move_ids(company, self._line_domain(company, [journal.id], date_from, date_to,
                                                                       target_move, search))
            domain.append(('id', 'in', ids))
        offset = max(int(offset or 0), 0)
        limit = int(limit) if limit else PAGE_SIZE
        total = Move.search_count(domain)
        moves = Move.search(domain, order=MOVE_ORDERS.get(sortby, MOVE_ORDERS['sort_date']), offset=offset, limit=limit)
        sums = {}
        for g in self.env['account.move.line'].read_group(
                [('move_id', 'in', moves.ids), ('display_type', 'not in', ('line_section', 'line_note'))],
                ['debit:sum', 'credit:sum'], ['move_id'], lazy=False):
            sums[g['move_id'][0]] = (g['debit'] or 0.0, g['credit'] or 0.0)
        rows = []
        for move in moves:
            debit, credit = sums.get(move.id, (0.0, 0.0))
            rows.append({
                'move_id': move.id, 'date': str(move.date), 'piece': move.name or '', 'state': move.state,
                'state_label': STATE_LABELS.get(move.state, move.state), 'partner_name': move.partner_id.name or '',
                'label': move.ref or '', 'debit': currency.round(debit), 'credit': currency.round(credit),
                'balanced': currency.is_zero(debit - credit)})
        return {'rows': rows, 'total_rows': total, 'offset': offset, 'has_more': offset + len(rows) < total}

    @api.model
    def _unbalanced_move_ids(self, company, line_domain):
        MoveLine = self.env['account.move.line']
        query = MoveLine._where_calc(line_domain)
        MoveLine._apply_ir_rules(query, 'read')
        from_clause, where_clause, params = query.get_sql()
        self.env.cr.execute(
            'SELECT "account_move_line".move_id FROM ' + from_clause + ' WHERE ' + where_clause +
            ' GROUP BY 1 HAVING ABS(SUM("account_move_line".debit) - SUM("account_move_line".credit)) >= %s',
            params + [company.currency_id.rounding / 2.0])
        return [row[0] for row in self.env.cr.fetchall()]

    # ------------------------------------------------------------------ lignes d'une pièce (au dépliage)
    @api.model
    def get_move_lines(self, company, move_id):
        move = self.env['account.move'].search([('id', '=', move_id), ('company_id', '=', company.id)], limit=1)
        return [{'line_id': line.id, 'account': '%s %s' % (line.account_id.code, line.account_id.name),
                 'label': line.name or '', 'debit': line.debit, 'credit': line.credit}
                for line in move.line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note'))]

    @api.model
    def get_anomaly_moves_for_export(self, company, journals, date_from, date_to, target_move, search=None):
        """Export : pièces déséquilibrées, brouillons et annulées de chaque journal (les pièces normales ne sont pas listées)."""
        result = {}
        for journal in journals:
            for kind in ANOMALY_KINDS:
                if journal['anomalies'][kind]:
                    result.setdefault(journal['id'], {})[kind] = self.get_moves(
                        company, journal['id'], date_from, date_to, target_move, 'sort_number', search, kind, 0,
                        journal['anomalies'][kind])['rows']
        return result
