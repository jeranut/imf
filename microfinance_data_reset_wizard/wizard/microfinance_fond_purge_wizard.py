# -*- coding: utf-8 -*-
"""Purge des fonds (crédit ET exploitation) : remise à zéro ou suppression, sans reliquat comptable.

Voir docs_dev/migration_ouverture/PURGE_FONDS_PLAN.md. Principes :
  - le périmètre est défini par les champs de LIEN des fonds sélectionnés (contribution -> écriture, partage -> écritures
    siège / agence), jamais par un libellé, un journal ou un compte ;
  - la simulation exécute le même code que l'exécution réelle dans un SAVEPOINT annulé (chiffres exacts, erreurs
    détectées) ; l'exécution exige une simulation de la MÊME sélection ;
  - une seule transaction (savepoint) pour tout le périmètre : à la moindre erreur, rollback complet.
"""
from collections import defaultdict
from datetime import datetime

from psycopg2 import sql

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_is_zero


TECH_CONTEXT = {'microfinance_skip_parent_check': True}

# Clés étrangères vers les modèles de fonds ou leurs écritures que l'assistant sait traiter (table, colonne).
KNOWN_FOREIGN_KEYS = {
    ('microfinance_fond_contribution', 'fond_id'),
    ('microfinance_fond_allocation', 'fond_id'),
    ('microfinance_fond_partage', 'fond_id'),
    ('microfinance_portfolio_allocation', 'fond_id'),
    ('microfinance_portfolio_allocation_line', 'fond_id'),
    ('microfinance_portfolio_allocation_line', 'allocation_id'),
    ('microfinance_loan', 'fond_credit_id'),
    ('res_company', 'microfinance_fond_credit_default_id'),
    ('microfinance_fond_partage_line', 'partage_id'),
    ('microfinance_fond_partage_line', 'hq_move_id'),
    ('microfinance_fond_partage_line', 'agency_move_id'),
    ('account_move', 'microfinance_fond_partage_id'),
    ('account_move', 'microfinance_fond_partage_line_id'),
    ('account_move', 'microfinance_fond_contribution_id'),
    ('microfinance_fond_contribution', 'move_id'),
    # sélection de fonds de cet assistant lui-même (transitoire)
    ('microfinance_fond_purge_wizard_fond_rel', 'fond_id'),
    # relevés bancaires papier supprimés avec leurs lignes et écritures
    ('microfinance_bank_statement_entry', 'statement_id'),
    ('microfinance_bank_statement_log', 'statement_id'),
    ('microfinance_bank_statement_cancel_wizard', 'statement_id'),
    ('account_bank_statement_line', 'statement_id'),
    ('account_move_line', 'statement_id'),
    ('account_bank_statement_ir_attachment_rel', 'account_bank_statement_id'),
}
# Tables du cœur comptable qui référencent une écriture en CASCADE par construction (lignes, relevés, assistants).
ACCOUNT_MOVE_CASCADE_TABLES = {
    'account_move_line', 'account_bank_statement_line', 'account_payment', 'account_invoice_transaction_rel',
    'account_move_account_move_send_rel', 'account_move_account_resequence_wizard_rel',
    'account_move_reversal_move', 'account_move_reversal_new_move',
}
STORED_FUND_FIELDS = ('total_contributions', 'total_decaisse', 'total_rembourse', 'solde_disponible', 'reste_partageable')


class MicrofinanceFondPurgeWizardLine(models.TransientModel):
    _name = 'microfinance.fond.purge.wizard.line'
    _description = 'Purge des fonds - ligne de simulation'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('microfinance.fond.purge.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer()
    company_name = fields.Char(string='Société')
    item = fields.Char(string='Modèle / nature')
    count = fields.Integer(string='Nombre')
    amount = fields.Float(string='Montant', digits=(16, 2))
    note = fields.Char(string='Remarque')


class MicrofinanceFondPurgeWizardBalance(models.TransientModel):
    _name = 'microfinance.fond.purge.wizard.balance'
    _description = 'Purge des fonds - soldes de contrôle'
    _order = 'company_name, account_code'

    wizard_id = fields.Many2one('microfinance.fond.purge.wizard', required=True, ondelete='cascade')
    company_name = fields.Char(string='Société')
    account_code = fields.Char(string='Compte')
    account_name = fields.Char(string='Intitulé')
    before = fields.Float(string='Solde avant', digits=(16, 2))
    impact = fields.Float(string='Effet attendu', digits=(16, 2))
    after = fields.Float(string='Solde après', digits=(16, 2))
    flag = fields.Char(string='Contrôle')


class MicrofinanceFondPurgeWizard(models.TransientModel):
    _name = 'microfinance.fond.purge.wizard'
    _description = 'Purge des fonds (crédit et exploitation)'

    # Clé du verrou advisory : propre à cet assistant (cf. clés des autres RAZ du même cluster Postgres).
    _LOCK_KEY = 823476515

    scope = fields.Selection([
        ('selection', 'Une sélection de fonds'),
        ('credit', 'Fonds de crédit'),
        ('exploitation', "Fonds d'exploitation"),
        ('both', 'Les deux'),
    ], string='Périmètre', required=True, default='selection')
    fond_ids = fields.Many2many(
        'microfinance.fond.credit', 'microfinance_fond_purge_wizard_fond_rel', 'wizard_id', 'fond_id',
        string='Fonds', context={'active_test': False})
    company_ids = fields.Many2many(
        'res.company', 'microfinance_fond_purge_wizard_company_rel', 'wizard_id', 'company_id',
        string='Société du fonds', help="Facultatif : ne garde que les fonds portés par ces sociétés (la société mère "
                                        "pour un fonds multi-agences). Vide = toutes.")
    mode_raz = fields.Selection([
        ('reset', 'Remettre à zéro (garde le fonds)'),
        ('delete_fund', 'Supprimer le fonds'),
    ], string='Remise à zéro', required=True, default='reset',
        help="« Remettre à zéro » supprime les contributions, partages et allocations du fonds et garde le fonds. "
             "« Supprimer le fonds » fait la même chose puis supprime le fonds ; son compte d'origine automatique "
             "(240xxx / 250xxx) est archivé, jamais supprimé.")
    delete_other_statements = fields.Boolean(
        string='Supprimer aussi tous les autres relevés bancaires des sociétés concernées', default=False,
        help="Coché : supprime AUSSI les relevés bancaires papier sans lien avec les fonds, avec leurs lignes et leurs "
             "écritures, pour les journaux bancaires des sociétés concernées. Décoché : seuls les relevés liés aux "
             "fonds sont supprimés.")
    include_orphans = fields.Boolean(
        string='Inclure les écritures orphelines des journaux de fonds et d\'exploitation', default=True,
        help="Écritures sans plus aucun lien avec un fonds existant (fonds déjà supprimé, purge précédente) dans un journal "
             "d'usage « Fonds » ou « Exploitation », ou portant encore le côté d'un partage. Listées en simulation, traitées "
             "comme les autres (extourne ou suppression, rapprochements défaits). Les lignes de relevé ne sont jamais prises.")
    summary = fields.Char(string='Concerné', compute='_compute_summary')
    done = fields.Boolean(readonly=True)
    log = fields.Text(string='Journal', readonly=True)
    line_ids = fields.One2many('microfinance.fond.purge.wizard.line', 'wizard_id', string='Simulation', readonly=True)
    balance_ids = fields.One2many('microfinance.fond.purge.wizard.balance', 'wizard_id', string='Soldes de contrôle',
                                  readonly=True)

    # ------------------------------------------------------------------ champs calculés
    @api.depends('scope', 'fond_ids', 'company_ids', 'include_orphans', 'delete_other_statements')
    def _compute_summary(self):
        for wiz in self:
            funds = wiz._get_funds()
            moves = wiz.env['account.move'].sudo()
            for fund in funds:
                moves |= wiz._collect(fund)['moves']
            moves |= wiz._orphan_moves()
            scope = wiz._statement_scope(moves, funds)
            wiz.summary = _("%(f)d fonds, %(s)d relevés et %(m)d écritures comptables concernés") % {
                'f': len(funds), 's': len(scope['statements']), 'm': len(moves) + len(scope['lines'])}

    # ------------------------------------------------------------------ périmètre
    def _get_funds(self):
        self.ensure_one()
        Fond = self.env['microfinance.fond.credit'].sudo().with_context(active_test=False)
        if self.scope == 'selection':
            funds = Fond.browse(self.sudo().fond_ids.ids).exists()
        elif self.scope in ('credit', 'exploitation'):
            funds = Fond.search([('destination', '=', self.scope)])
        else:
            funds = Fond.search([])
        if self.sudo().company_ids:
            companies = self.sudo().company_ids.ids
            funds = funds.filtered(lambda f: f._fund_company().id in companies)
        return funds

    def _collect(self, fund):
        """Tout ce que la purge d'un fonds touche, par les champs de lien (sudo, archivés inclus)."""
        env = self.env
        ctx = dict(active_test=False)
        fund = fund.sudo().with_context(**ctx)
        contribs = env['microfinance.fond.contribution'].sudo().with_context(**ctx).search([('fond_id', '=', fund.id)])
        partages = env['microfinance.fond.partage'].sudo().with_context(**ctx).search([('fond_id', '=', fund.id)])
        plines = partages.line_ids
        allocs = env['microfinance.fond.allocation'].sudo().with_context(**ctx).search([('fond_id', '=', fund.id)])
        portfolio = env['microfinance.portfolio.allocation'].sudo().with_context(**ctx).search([('fond_id', '=', fund.id)])
        Move = env['account.move'].sudo().with_context(**ctx)
        moves = Move.search([
            '|', '|',
            ('microfinance_fond_contribution_id', 'in', contribs.ids),
            ('microfinance_fond_partage_id', 'in', partages.ids),
            ('id', 'in', (contribs.move_id | plines.hq_move_id | plines.agency_move_id).ids),
        ])
        return {'fund': fund, 'contribs': contribs, 'partages': partages, 'plines': plines, 'allocs': allocs,
                'portfolio': portfolio, 'moves': moves}

    def _orphan_moves(self):
        """Écritures sans lien avec un fonds existant, dans les journaux de fonds / d'exploitation (ou portant encore le côté
        d'un partage). Jamais les écritures de ligne de relevé ; jamais celles d'un fonds existant (même non sélectionné)."""
        self.ensure_one()
        Move = self.env['account.move'].sudo().with_context(active_test=False)
        if not self.include_orphans:
            return Move
        contribs = self.env['microfinance.fond.contribution'].sudo().with_context(active_test=False).search(
            [('move_id', '!=', False)])
        lines = self.env['microfinance.fond.partage.line'].sudo().search([])
        linked = (contribs.move_id | lines.hq_move_id | lines.agency_move_id).ids
        return Move.search([
            ('microfinance_fond_contribution_id', '=', False), ('microfinance_fond_partage_id', '=', False),
            ('statement_line_id', '=', False), ('id', 'not in', linked),
            '|', ('journal_id.microfinance_usage', 'in', ('fund', 'operating')),
            ('microfinance_partage_side', '!=', False)])

    @api.model
    def _reversed_ids(self, moves):
        Move = self.env['account.move'].sudo().with_context(active_test=False)
        return set(Move.search([('reversed_entry_id', 'in', moves.ids)]).mapped('reversed_entry_id').ids)

    def _statement_scope(self, moves, funds):
        """Relevés bancaires papier à supprimer : ceux dont une ligne est liée à ces écritures (lettrage des lignes de
        suspens, ou lien direct d'une ligne saisie), plus, si la case est cochée, tous les autres relevés des journaux
        bancaires des sociétés concernées."""
        Entry = self.env['microfinance.bank.statement.entry'].sudo()
        Statement = self.env['account.bank.statement'].sudo().with_context(active_test=False)
        lines = moves.sudo().line_ids
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        others = (partials.debit_move_id | partials.credit_move_id) - lines
        st_lines = others.move_id.statement_line_id
        linked_entries = Entry.search([
            '|', '|', ('statement_line_id', 'in', st_lines.ids), ('target_line_id', 'in', lines.ids),
            ('pointed_line_id', 'in', lines.ids)])
        linked = st_lines.statement_id | linked_entries.statement_id
        statements = linked
        if self.delete_other_statements:
            companies = moves.company_id | st_lines.company_id | linked.journal_id.company_id
            for fund in funds:
                companies |= fund._fund_company()
            statements |= Statement.search([
                ('mf_state', '!=', False), ('journal_id.type', '=', 'bank'),
                ('journal_id.company_id', 'in', companies.ids)])
        return {'statements': statements, 'lines': st_lines | statements.line_ids,
                'entries': statements.mf_entry_ids, 'linked_entries': linked_entries, 'linked': linked}

    # ------------------------------------------------------------------ blocages
    def _unknown_dependencies(self, collected):
        """Clés étrangères vers les tables de fonds / d'écritures supprimées qui ne sont pas prévues et qui ont des
        lignes concernées : retournées AVANT toute suppression."""
        cr = self.env.cr
        ids_by_model = defaultdict(set)
        for c in collected:
            moves = c['moves']
            ids_by_model['microfinance.fond.credit'].update(c['fund'].ids)
            ids_by_model['microfinance.fond.contribution'].update(c['contribs'].ids)
            ids_by_model['microfinance.fond.partage'].update(c['partages'].ids)
            ids_by_model['microfinance.fond.partage.line'].update(c['plines'].ids)
            ids_by_model['microfinance.fond.allocation'].update(c['allocs'].ids)
            ids_by_model['microfinance.portfolio.allocation'].update(c['portfolio'].ids)
            ids_by_model['account.move'].update(moves.ids)
        orphans = self._orphan_moves()
        ids_by_model['account.move'].update(orphans.ids)
        every = self.env['account.move'].sudo()
        for c in collected:
            every |= c['moves']
        ids_by_model['account.bank.statement'].update(
            self._statement_scope(every | orphans, [c['fund'] for c in collected])['statements'].ids)
        blockers = []
        for model, ids in ids_by_model.items():
            if not ids:
                continue
            table = self.env[model]._table
            cr.execute("""
                SELECT (SELECT relname FROM pg_class WHERE oid = c.conrelid), a.attname
                  FROM pg_constraint c
                  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                 WHERE c.contype = 'f' AND c.confrelid = %s::regclass AND array_length(c.conkey, 1) = 1
            """, (table,))
            for ref_table, column in cr.fetchall():
                if (ref_table, column) in KNOWN_FOREIGN_KEYS:
                    continue
                if model == 'account.move' and ref_table in ACCOUNT_MOVE_CASCADE_TABLES:
                    continue
                cr.execute(
                    sql.SQL("SELECT count(*) FROM {} WHERE {} = ANY(%s)").format(
                        sql.Identifier(ref_table), sql.Identifier(column)), (list(ids),))
                n = cr.fetchone()[0]
                if n:
                    blockers.append(_(
                        "Dépendance inconnue : %(n)d ligne(s) de la table « %(t)s » (colonne « %(c)s ») référencent %(m)s "
                        "à purger."
                    ) % {'n': n, 't': ref_table, 'c': column, 'm': table})
        return blockers

    def _blockers(self, funds, collected):
        self.ensure_one()
        blockers = []
        if not funds:
            blockers.append(_("Aucun fonds dans le périmètre."))
            return blockers
        blockers += self._unknown_dependencies(collected)
        for c in collected:
            fund = c['fund']
            label = '%s « %s »' % (fund.code, fund.name)
            disbursed = fund.loan_ids.sudo().filtered('disbursement_date')
            if disbursed:
                blockers.append(_("%(f)s : %(n)d crédit(s) déjà décaissé(s) rattaché(s) (%(l)s) - jamais touché.") % {
                    'f': label, 'n': len(disbursed), 'l': ', '.join(disbursed.mapped('name'))})
            elif self.mode_raz == 'delete_fund' and fund.loan_ids.sudo():
                blockers.append(_("%(f)s : crédit(s) rattaché(s) (%(l)s) - détachez-les avant de supprimer le fonds.") % {
                    'f': label, 'l': ', '.join(fund.loan_ids.sudo().mapped('name'))})
            used = c['allocs'].filtered(lambda a: not float_is_zero(a.montant_utilise, precision_digits=2))
            if used:
                blockers.append(_("%(f)s : allocation déjà utilisée par %(a)s.") % {
                    'f': label, 'a': ', '.join(used.mapped('company_id.name'))})
        return blockers

    # ------------------------------------------------------------------ soldes de contrôle
    def _balances(self, pairs):
        """{(société, compte): solde des lignes comptabilisées}."""
        self.env.flush_all()
        result = {pair: 0.0 for pair in pairs}
        if not pairs:
            return result
        companies = list({pair[0] for pair in pairs})
        accounts = list({pair[1] for pair in pairs})
        self.env.cr.execute("""
            SELECT company_id, account_id, COALESCE(SUM(balance), 0)
              FROM account_move_line
             WHERE parent_state = 'posted' AND company_id = ANY(%s) AND account_id = ANY(%s)
          GROUP BY company_id, account_id
        """, (companies, accounts))
        for company_id, account_id, balance in self.env.cr.fetchall():
            if (company_id, account_id) in result:
                result[(company_id, account_id)] = float(balance)
        return result

    # ------------------------------------------------------------------ cœur
    def _purge(self, funds, collected):
        """Dans la transaction en cours (savepoint géré par _run). Retourne les statistiques."""
        self.ensure_one()
        env = self.env
        counts = []
        fund_labels = ['%s « %s »' % (c['fund'].code, c['fund'].name) for c in collected]

        def add(company, item, n, amount=0.0, note=''):
            if n:
                counts.append((company or '', item, n, amount, note))

        def debit(moves):
            return sum(moves.line_ids.mapped('debit'))

        Move = env['account.move'].sudo().with_context(active_test=False)
        all_moves = Move.browse()
        targets = Move.browse()
        plines = env['microfinance.fond.partage.line']
        for c in collected:
            fund = c['fund']
            fund_company = fund._fund_company().name
            add(fund_company, _('Fonds'), 1, 0.0, _('supprimé') if self.mode_raz == 'delete_fund' else _('remis à zéro'))
            add(fund_company, _('Contributions'), len(c['contribs']), sum(c['contribs'].mapped('amount')))
            for partage in c['partages']:
                add(partage.company_id.name, _('Partages'), 1, partage.base_amount, partage.name)
            for line in c['plines']:
                add(line.company_id.name, _('Parts de partage'), 1, line.amount)
            for alloc in c['allocs']:
                add(alloc.company_id.name, _('Allocations'), 1, alloc.amount_allocated)
            for rep in c['portfolio']:
                add(rep.company_id.name, _('Répartitions de portefeuille'), 1, rep.base_amount)
            all_moves |= c['moves']
            targets |= c['moves']
            plines |= c['plines']
        orphans = self._orphan_moves()
        for company in orphans.company_id:
            add(company.name, _('Écritures orphelines (sans fonds)'), len(orphans.filtered(
                lambda m: m.company_id == company)), debit(orphans.filtered(lambda m: m.company_id == company)))
        all_moves |= orphans
        targets |= orphans
        posted = targets.filtered(lambda m: m.state == 'posted')
        for company in targets.company_id:
            mine = lambda recs: recs.filtered(lambda m: m.company_id == company)
            add(company.name, _('Écritures en brouillon (supprimées)'), len(mine(targets - posted)),
                debit(mine(targets - posted)))
            add(company.name, _('Écritures comptabilisées (supprimées)'), len(mine(posted)), debit(mine(posted)))
            add(company.name, _('dont écritures miroirs des agences'), len(mine(targets).filtered(
                lambda m: m.microfinance_partage_side == 'agency')))
        scope = self._statement_scope(targets, [c['fund'] for c in collected])
        statements, st_lines, entries = scope['statements'], scope['lines'], scope['entries']
        for stmt in statements:
            company = stmt.journal_id.company_id.name
            add(company, _('Relevés bancaires supprimés'), 1, stmt.balance_end_real, stmt.display_name)
        for company in entries.company_id:
            mine_e = entries.filtered(lambda e: e.company_id == company)
            add(company.name, _('Lignes de relevé supprimées'), len(mine_e), sum(mine_e.mapped('amount')))
        st_moves = st_lines.move_id
        for company in st_moves.company_id:
            mine_m = st_moves.filtered(lambda m: m.company_id == company)
            add(company.name, _('Écritures de relevé supprimées'), len(mine_m), debit(mine_m))
        statements_report = []
        for stmt in statements:
            own = stmt.mf_entry_ids
            tied = own & scope['linked_entries']
            statements_report.append('%s (%s) : %d ligne(s), dont %d sans lien avec les fonds%s' % (
                stmt.display_name, stmt.journal_id.company_id.name, len(own), len(own - tied),
                '' if stmt in scope['linked'] else ' - relevé sans lien avec les fonds'))

        # Soldes avant et effet attendu (comptes touchés par les écritures + compte du fonds).
        pairs = {(line.company_id.id, line.account_id.id) for line in targets.line_ids}
        for c in collected:
            if c['fund'].account_id:
                pairs.add((c['fund']._fund_company().id, c['fund'].account_id.id))
        # Les écritures des lignes de relevé supprimées entrent dans le contrôle.
        statement_lines = st_moves.line_ids
        pairs |= {(line.company_id.id, line.account_id.id) for line in statement_lines}
        before = self._balances(pairs)
        impact = defaultdict(float)
        for line in posted.line_ids | statement_lines.filtered(lambda l: l.parent_state == 'posted'):
            impact[(line.company_id.id, line.account_id.id)] -= line.balance

        # 2. Répartitions de portefeuille (dépendent des allocations d'agence).
        for c in collected:
            repartitions = c['portfolio']
            if repartitions:
                to_cancel = repartitions.filtered(lambda r: r.state == 'validated')
                if to_cancel:
                    to_cancel.action_cancel()
                repartitions.unlink()

        # 3. Écritures : déliage des partages (RESTRICT), délettrage puis suppression.
        plines.sudo().write({'hq_move_id': False, 'agency_move_id': False})
        all_moves.write({'microfinance_fond_partage_id': False, 'microfinance_fond_partage_line_id': False})
        created = Move.browse()
        reconciled = (targets | st_moves).line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids)
        if reconciled:
            reconciled.remove_move_reconcile()
        # relevés : lignes comptables (et leurs écritures) d'abord, puis les lignes saisies et le relevé lui-même
        st_lines.unlink()
        entries.write({'state': 'todo'})
        statements.filtered(lambda st: st.mf_state == 'validated').write({'mf_state': 'draft'})
        statement_ids, entry_ids, st_line_ids, st_move_ids = statements.ids, entries.ids, st_lines.ids, st_moves.ids
        statements.unlink()
        targets.with_context(force_delete=True).unlink()
        # Contrôle final : plus rien ne référence un fonds purgé.
        left = []
        for model, ids in (('account.move', all_moves.ids + st_move_ids), ('account.bank.statement.line', st_line_ids),
                           ('microfinance.bank.statement.entry', entry_ids), ('account.bank.statement', statement_ids)):
            remaining = env[model].sudo().with_context(active_test=False).browse(ids).exists()
            if remaining:
                left.append('%s : %s' % (model, ', '.join(map(str, remaining.ids))))
        if left:
            raise UserError(_("Contrôle final : des éléments liés aux fonds purgés subsistent (%s). Purge annulée.")
                            % ' ; '.join(left))
        kept_names, created_names = [], []
        stats_statements = statements_report

        # 4. Partages (parts en cascade), contributions, allocations.
        Partage = env['microfinance.fond.partage'].sudo().with_context(active_test=False, **TECH_CONTEXT)
        Contribution = env['microfinance.fond.contribution'].sudo().with_context(active_test=False, **TECH_CONTEXT)
        Allocation = env['microfinance.fond.allocation'].sudo().with_context(
            active_test=False, fond_partage_technique=True, **TECH_CONTEXT)
        for c in collected:
            partages = Partage.browse(c['partages'].ids)
            open_partages = partages.filtered(lambda p: p.state == 'validated')
            if open_partages:
                open_partages.write({'state': 'cancelled'})
            partages.unlink()
            Contribution.browse(c['contribs'].ids).unlink()
            Allocation.browse(c['allocs'].ids).unlink()

        # 5. Fonds : conservés (stockés recalculés) ou supprimés (compte automatique archivé).
        archived = []
        parent = env['res.company']._get_microfinance_parent()
        allowed_move_ids = set(all_moves.ids) | set(created.ids)
        Fond = env['microfinance.fond.credit'].sudo().with_context(active_test=False)
        for c in collected:
            fund = Fond.browse(c['fund'].id)
            if self.mode_raz == 'reset':
                if fund.destination != 'exploitation' and fund.scope == 'multi_company':
                    fund.with_context(**TECH_CONTEXT).write({'allocation_required': bool(parent)})
                continue
            account = fund.account_id if fund.account_auto else env['account.account']
            company = fund._fund_company()
            fund_id = fund.id
            fund.with_context(**TECH_CONTEXT).unlink()
            if not account:
                continue
            others = Fond.search_count([('account_id', '=', account.id), ('id', '!=', fund_id)])
            lines = env['account.move.line'].sudo().search([('account_id', '=', account.id)])
            foreign = lines.filtered(lambda l: l.move_id.id not in allowed_move_ids)
            posted_balance = sum(lines.filtered(lambda l: l.parent_state == 'posted').mapped('balance'))
            if not others and not foreign and float_is_zero(posted_balance, precision_digits=2):
                account.write({'deprecated': True})
                archived.append((company.name, account.code))
            else:
                add(company.name, _("Comptes d'origine conservés (non archivés)"), 1, 0.0, _(
                    "%(code)s : écritures étrangères à cette purge, solde non nul ou compte partagé") % {
                    'code': account.code})
        for company_name, code in archived:
            add(company_name, _('Comptes d\'origine archivés'), 1, 0.0, code)

        # 6. Recalcul des montants stockés et rafraîchissement.
        remaining = Fond.browse([c['fund'].id for c in collected]).exists()
        for fname in STORED_FUND_FIELDS:
            env.add_to_compute(remaining._fields[fname], remaining)
        env.flush_all()
        env.invalidate_all()

        # 7. Soldes après et contrôle.
        after = self._balances(pairs)
        accounts = {a.id: a for a in env['account.account'].sudo().browse({p[1] for p in pairs})}
        companies = {c.id: c for c in env['res.company'].sudo().browse({p[0] for p in pairs})}
        balance_rows, anomalies = [], []
        for pair in sorted(pairs, key=lambda p: (companies[p[0]].name, accounts[p[1]].code)):
            b, a, e = before[pair], after[pair], impact.get(pair, 0.0)
            flag = ''
            if not float_is_zero(a - (b + e), precision_digits=2):
                flag = _('ANOMALIE : écart avec l\'effet attendu')
                anomalies.append('%s %s : avant %.2f, attendu %.2f, obtenu %.2f' % (
                    companies[pair[0]].name, accounts[pair[1]].code, b, b + e, a))
            elif not float_is_zero(a, precision_digits=2):
                flag = _('Solde non nul')
            balance_rows.append((companies[pair[0]].name, accounts[pair[1]].code, accounts[pair[1]].name, b, e, a, flag))
        return {'counts': counts, 'balances': balance_rows, 'anomalies': anomalies, 'kept': kept_names,
                'created': created_names, 'funds': fund_labels, 'statements': stats_statements,
                'n_statements': len(statement_ids), 'n_entries': len(entry_ids), 'n_moves': len(all_moves) + len(st_move_ids),
                'companies': sorted({row[0] for row in balance_rows} | {row[0] for row in counts if row[0]})}

    # ------------------------------------------------------------------ présentation et audit
    @staticmethod
    def _fmt_counts(counts):
        return '\n'.join('%s | %s | %d | %.2f%s' % (company, item, n, amount, (' | ' + note) if note else '')
                         for company, item, n, amount, note in counts)

    @staticmethod
    def _fmt_balances(rows, index):
        return '\n'.join('%s | %s %s | %.2f' % (row[0], row[1], row[2], row[index]) for row in rows)

    def _write_report(self, stats, blockers, execute, error=None):
        self.ensure_one()
        self.line_ids.unlink()
        self.balance_ids.unlink()
        if stats:
            Line = self.env['microfinance.fond.purge.wizard.line']
            for seq, (company, item, n, amount, note) in enumerate(sorted(stats['counts'], key=lambda r: (r[0], r[1]))):
                Line.create({'wizard_id': self.id, 'sequence': seq, 'company_name': company, 'item': item, 'count': n,
                             'amount': amount, 'note': note})
            Balance = self.env['microfinance.fond.purge.wizard.balance']
            for company, code, name, b, e, a, flag in stats['balances']:
                Balance.create({'wizard_id': self.id, 'company_name': company, 'account_code': code, 'account_name': name,
                                'before': b, 'impact': e, 'after': a, 'flag': flag})
        lines = []
        stamp = datetime.now().strftime('%H:%M:%S')
        lines.append('[%s] %s' % (stamp, _("EXÉCUTION RÉELLE") if execute else _("SIMULATION (rien n'est modifié)")))
        for blocker in blockers:
            lines.append('BLOQUÉ : %s' % blocker)
        if error:
            lines.append('ERREUR : %s' % error)
            lines.append(_("Rollback complet effectué - aucune donnée modifiée."))
        if stats:
            lines.append(_("Fonds : %s") % ', '.join(stats['funds']))
            if stats['anomalies']:
                lines.append(_("ANOMALIES DE SOLDE (rien n'a été corrigé) :"))
                lines += ['  - %s' % a for a in stats['anomalies']]
            else:
                lines.append(_("Soldes de contrôle conformes à l'effet attendu."))
            if stats['statements']:
                lines.append(_("Relevés supprimés : %s") % ' ; '.join(stats['statements']))
            if stats['kept']:
                lines.append(_("Écritures conservées et déliées : %s") % ', '.join(stats['kept']))
            if stats['created']:
                lines.append(_("Extournes créées : %s") % ', '.join(stats['created']))
        self.log = '\n'.join(lines)

    def _create_audit(self, stats, execute, error):
        self.ensure_one()
        user = self.env.user
        self.env['microfinance.fond.purge.log'].sudo().create({
            'name': 'PURGE-FONDS/%s' % datetime.now().strftime('%Y%m%d-%H%M%S'),
            'user_id': user.id, 'user_name': user.name,
            'state': 'failed' if error else 'done',
            'companies': ', '.join(stats['companies']) if stats else '',
            'scope': dict(self._fields['scope'].selection)[self.scope],
            'funds': '\n'.join(stats['funds']) if stats else '',
            'mode_raz': dict(self._fields['mode_raz'].selection)[self.mode_raz],
            'move_mode': _('Suppression des écritures liées (comptabilisées comprises)'),
            'options': 'miroirs agences : oui ; rapprochements défaits : oui ; écritures orphelines : %s' % (
                _('oui') if self.include_orphans else _('non')),
            'counts': self._fmt_counts(stats['counts']) if stats else '',
            'balances_before': self._fmt_balances(stats['balances'], 3) if stats else '',
            'balances_after': self._fmt_balances(stats['balances'], 5) if stats else '',
            'anomalies': '\n'.join(stats['anomalies']) if stats else '',
            'kept_moves': '\n'.join(stats['kept'] + stats['created']) if stats else '',
            'statements': '\n'.join(stats['statements']) if stats else '',
            'n_statements': stats['n_statements'] if stats else 0,
            'n_entries': stats['n_entries'] if stats else 0,
            'n_moves': stats['n_moves'] if stats else 0,
            'message': error or '',
        })

    # ------------------------------------------------------------------ exécution
    def _run(self, execute):
        self.ensure_one()
        funds = self._get_funds()
        collected = [self._collect(fund) for fund in funds]
        blockers = self._blockers(funds, collected)
        if blockers:
            if execute:
                raise UserError(_("Purge impossible, rien n'a été supprimé :\n%s") % '\n'.join(blockers))
            self._write_report(None, blockers, execute)
            return self._reopen()
        savepoint = self.env.cr.savepoint()
        stats, error = None, None
        try:
            stats = self._purge(funds, collected)
        except Exception as exc:  # rollback complet, quelle que soit l'erreur
            savepoint.close(rollback=True)
            self.env.invalidate_all()
            error = '%s: %s' % (type(exc).__name__, exc)
        else:
            savepoint.close(rollback=not execute)
            self.env.invalidate_all()
        if execute:
            self._create_audit(stats, execute, error)
            self.write({'done': not error})
        self._write_report(stats, [], execute, error)
        return self._reopen()

    def _acquire_lock_or_raise(self):
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (self._LOCK_KEY,))
        if not self.env.cr.fetchone()[0]:
            raise UserError(_("Une autre purge de fonds est déjà en cours."))

    def action_simulate(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Réservé à l'administrateur technique."))
        self._acquire_lock_or_raise()
        return self._run(execute=False)

    def action_execute(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Réservé à l'administrateur technique."))
        self._acquire_lock_or_raise()
        return self._run(execute=True)

    def action_reset(self):
        self.ensure_one()
        self.write({'done': False, 'log': False})
        self.line_ids.unlink()
        self.balance_ids.unlink()
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}
