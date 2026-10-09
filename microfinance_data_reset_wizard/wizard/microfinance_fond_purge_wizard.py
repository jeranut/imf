# -*- coding: utf-8 -*-
"""Purge des fonds (crédit ET exploitation) : remise à zéro ou suppression, sans reliquat comptable.

Voir docs_dev/migration_ouverture/PURGE_FONDS_PLAN.md. Principes :
  - le périmètre est défini par les champs de LIEN des fonds sélectionnés (contribution -> écriture, partage -> écritures
    siège / agence), jamais par un libellé, un journal ou un compte ;
  - la simulation exécute le même code que l'exécution réelle dans un SAVEPOINT annulé (chiffres exacts, erreurs
    détectées) ; l'exécution exige une simulation de la MÊME sélection ;
  - une seule transaction (savepoint) pour tout le périmètre : à la moindre erreur, rollback complet.
"""
import hashlib
from collections import defaultdict
from datetime import datetime

from psycopg2 import sql

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_is_zero

from .microfinance_fond_credit_purge_wizard import MicrofinanceFondCreditPurgeWizard as LegacyPurgeWizard

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
    PHRASE = 'PURGER'
    APPLY_PARAM = LegacyPurgeWizard.APPLY_PARAM
    TEST_ENV_PARAM = 'microfinance.raz_environnement_test'

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
    move_mode = fields.Selection([
        ('reverse', 'A - Extourner les écritures comptabilisées (garde la trace)'),
        ('delete', 'B - Supprimer les écritures de test (même comptabilisées)'),
    ], string='Écritures comptables', required=True, default='reverse',
        help="A (défaut) : extourne par les actions normales d'Odoo. B : suppression (contexte force_delete), "
             "seulement si le paramètre système microfinance.raz_environnement_test vaut True.")
    include_mirror = fields.Boolean(
        string='Inclure les écritures miroirs des agences', default=True,
        help="Décoché : les écritures côté agence ne sont ni extournées ni supprimées (seulement déliées du partage) ; "
             "les comptes de liaison resteront déséquilibrés.")
    undo_bank = fields.Boolean(
        string='Défaire les rapprochements bancaires liés et remettre les lignes de relevé à traiter', default=True,
        help="Défait le lettrage des lignes de suspens (139100 / 139500) rapprochées avec une ligne de relevé, extourne "
             "l'écriture de cette ligne et remet la ligne à l'état « à traiter ». Les relevés ne sont jamais supprimés.")
    confirm_text = fields.Char(string='Tapez « PURGER » pour confirmer')

    test_env_enabled = fields.Boolean(compute='_compute_test_env_enabled')
    current_key = fields.Char(compute='_compute_current_key')
    simulated_key = fields.Char(readonly=True, copy=False)
    has_blockers = fields.Boolean(readonly=True)
    can_execute = fields.Boolean(compute='_compute_can_execute')
    done = fields.Boolean(readonly=True)
    log = fields.Text(string='Journal', readonly=True)
    line_ids = fields.One2many('microfinance.fond.purge.wizard.line', 'wizard_id', string='Simulation', readonly=True)
    balance_ids = fields.One2many('microfinance.fond.purge.wizard.balance', 'wizard_id', string='Soldes de contrôle',
                                  readonly=True)

    # ------------------------------------------------------------------ champs calculés
    def _compute_test_env_enabled(self):
        enabled = self._test_env_enabled()
        for wiz in self:
            wiz.test_env_enabled = enabled

    @api.model
    def _test_env_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(self.TEST_ENV_PARAM) == 'True'

    @api.depends('scope', 'fond_ids', 'company_ids', 'mode_raz', 'move_mode', 'include_mirror', 'undo_bank')
    def _compute_current_key(self):
        for wiz in self:
            wiz.current_key = wiz._selection_key()

    @api.depends('current_key', 'simulated_key', 'has_blockers', 'done')
    def _compute_can_execute(self):
        for wiz in self:
            wiz.can_execute = bool(
                wiz.simulated_key and wiz.simulated_key == wiz._selection_key() and not wiz.has_blockers
                and not wiz.done)

    def _selection_key(self):
        """Empreinte de la sélection RÉSOLUE (fonds trouvés + options) : une simulation ne vaut que pour elle."""
        self.ensure_one()
        payload = repr((self.scope, self.mode_raz, self.move_mode, bool(self.include_mirror), bool(self.undo_bank),
                        sorted(self._get_funds().ids)))
        return hashlib.sha1(payload.encode()).hexdigest()

    @api.onchange('move_mode')
    def _onchange_move_mode(self):
        if self.move_mode == 'delete' and not self._test_env_enabled():
            self.move_mode = 'reverse'
            return {'warning': {
                'title': _('Option B indisponible'),
                'message': _("Le paramètre système « %s » doit valoir True pour supprimer des écritures comptabilisées.")
                % self.TEST_ENV_PARAM}}

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

    def _targets(self, moves):
        """Écritures réellement neutralisées : sans les miroirs agence si la case est décochée."""
        self.ensure_one()
        if self.include_mirror:
            return moves
        return moves.filtered(lambda m: m.microfinance_partage_side != 'agency')

    @api.model
    def _reversed_ids(self, moves):
        Move = self.env['account.move'].sudo().with_context(active_test=False)
        return set(Move.search([('reversed_entry_id', 'in', moves.ids)]).mapped('reversed_entry_id').ids)

    def _split_moves(self, moves):
        """(à extourner, à supprimer quel que soit le mode, neutres déjà extournés ou extournes) pour les écritures ciblées."""
        draft = moves.filtered(lambda m: m.state != 'posted')
        posted = moves - draft
        already = self._reversed_ids(posted)
        reversible = posted.filtered(lambda m: not m.reversed_entry_id and m.id not in already)
        return reversible, draft, posted - reversible

    def _bank_entries(self, moves):
        """Lignes de relevé (lot B) rapprochées avec une ligne de ces écritures : par le lettrage, jamais par libellé."""
        lines = moves.sudo().line_ids
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        others = (partials.debit_move_id | partials.credit_move_id) - lines
        stmt_lines = others.move_id.statement_line_id
        if not stmt_lines:
            return self.env['microfinance.bank.statement.entry']
        return self.env['microfinance.bank.statement.entry'].sudo().search([
            ('statement_line_id', 'in', stmt_lines.ids), ('state', '=', 'done')])

    # ------------------------------------------------------------------ blocages
    def _unknown_dependencies(self, collected):
        """Clés étrangères vers les tables de fonds / d'écritures supprimées qui ne sont pas prévues et qui ont des
        lignes concernées : retournées AVANT toute suppression."""
        cr = self.env.cr
        delete_all_moves = self.move_mode == 'delete'
        ids_by_model = defaultdict(set)
        for c in collected:
            moves = self._targets(c['moves'])
            ids_by_model['microfinance.fond.credit'].update(c['fund'].ids)
            ids_by_model['microfinance.fond.contribution'].update(c['contribs'].ids)
            ids_by_model['microfinance.fond.partage'].update(c['partages'].ids)
            ids_by_model['microfinance.fond.partage.line'].update(c['plines'].ids)
            ids_by_model['microfinance.fond.allocation'].update(c['allocs'].ids)
            ids_by_model['microfinance.portfolio.allocation'].update(c['portfolio'].ids)
            ids_by_model['account.move'].update((moves if delete_all_moves else moves.filtered(
                lambda m: m.state != 'posted')).ids)
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
        if self.move_mode == 'delete' and not self._test_env_enabled():
            blockers.append(_(
                "Le mode B (supprimer les écritures) exige le paramètre système « %s » = True (absent ou différent de "
                "True).") % self.TEST_ENV_PARAM)
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
            if not self.undo_bank:
                entries = self._bank_entries(self._targets(c['moves']))
                if entries:
                    blockers.append(_(
                        "%(f)s : %(n)d ligne(s) de relevé rapprochée(s) avec les écritures du fonds - cochez « Défaire les "
                        "rapprochements bancaires ».") % {'f': label, 'n': len(entries)})
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
        today = fields.Date.context_today(self)
        reverse_mode = self.move_mode == 'reverse'
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
        entries_all = env['microfinance.bank.statement.entry']
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
            targets |= self._targets(c['moves'])
            plines |= c['plines']
        reversible, drafts, neutral = self._split_moves(targets)
        posted_effect = reversible if reverse_mode else (targets - drafts)
        kept_mirrors = all_moves - targets
        for company in targets.company_id | kept_mirrors.company_id:
            mine = lambda recs: recs.filtered(lambda m: m.company_id == company)
            add(company.name, _('Écritures en brouillon (supprimées)'), len(mine(drafts)), debit(mine(drafts)))
            if reverse_mode:
                add(company.name, _('Écritures comptabilisées (extournées)'), len(mine(reversible)),
                    debit(mine(reversible)))
                add(company.name, _('Écritures déjà neutralisées (conservées)'), len(mine(neutral)),
                    debit(mine(neutral)))
            else:
                add(company.name, _('Écritures comptabilisées (supprimées)'), len(mine(targets - drafts)),
                    debit(mine(targets - drafts)))
            add(company.name, _('dont écritures miroirs des agences'), len(mine(targets).filtered(
                lambda m: m.microfinance_partage_side == 'agency')))
            add(company.name, _('Écritures miroirs des agences laissées en place (déliées)'), len(mine(kept_mirrors)))
        entries_all = self._bank_entries(targets) if self.undo_bank else entries_all
        for entry in entries_all:
            add(entry.company_id.name, _('Lignes de relevé délettrées (remises à traiter)'), 1, entry.amount)

        # Soldes avant et effet attendu (comptes touchés par les écritures + compte du fonds).
        pairs = {(line.company_id.id, line.account_id.id) for line in targets.line_ids}
        for c in collected:
            if c['fund'].account_id:
                pairs.add((c['fund']._fund_company().id, c['fund'].account_id.id))
        # Les écritures des lignes de relevé défaites sont extournées : leur effet entre dans le contrôle.
        statement_lines = entries_all.statement_line_id.move_id.line_ids
        pairs |= {(line.company_id.id, line.account_id.id) for line in statement_lines}
        before = self._balances(pairs)
        impact = defaultdict(float)
        for line in posted_effect.line_ids | statement_lines:
            impact[(line.company_id.id, line.account_id.id)] -= line.balance

        # 1. Rapprochements bancaires (avant toute extourne : une ligne lettrée ne peut pas être extournée).
        if entries_all:
            entries_all._cancel_treatment_unchecked(_('Purge des fonds'))

        # 2. Répartitions de portefeuille (dépendent des allocations d'agence).
        for c in collected:
            repartitions = c['portfolio']
            if repartitions:
                to_cancel = repartitions.filtered(lambda r: r.state == 'validated')
                if to_cancel:
                    to_cancel.action_cancel()
                repartitions.unlink()

        # 3. Écritures : déliage des partages (RESTRICT), puis extourne / suppression.
        plines.sudo().write({'hq_move_id': False, 'agency_move_id': False})
        all_moves.write({'microfinance_fond_partage_id': False, 'microfinance_fond_partage_line_id': False})
        created = Move.browse()
        if reverse_mode:
            for move in reversible:
                company = move.company_id
                created |= move.with_company(company).with_context(allowed_company_ids=[company.id])._reverse_moves(
                    [{'date': today, 'ref': _('Extourne %s') % (move.ref or move.name)}], cancel=True)
            drafts.unlink()
        else:
            reconciled = targets.line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids)
            if reconciled:
                reconciled.remove_move_reconcile()
            targets.with_context(force_delete=True).unlink()
        kept = (all_moves - drafts) if reverse_mode else kept_mirrors
        kept_names = ['%s (%s)' % (m.name, m.company_id.name) for m in kept.exists()]
        created_names = ['%s (%s)' % (m.name, m.company_id.name) for m in created]
        for company in created.company_id:
            add(company.name, _('Écritures d\'extourne créées'), len(created.filtered(lambda m: m.company_id == company)))

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
                'created': created_names, 'funds': fund_labels,
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
            'move_mode': dict(self._fields['move_mode'].selection)[self.move_mode],
            'options': 'miroirs agences : %s ; rapprochements défaits : %s' % (
                _('oui') if self.include_mirror else _('non'), _('oui') if self.undo_bank else _('non')),
            'counts': self._fmt_counts(stats['counts']) if stats else '',
            'balances_before': self._fmt_balances(stats['balances'], 3) if stats else '',
            'balances_after': self._fmt_balances(stats['balances'], 5) if stats else '',
            'anomalies': '\n'.join(stats['anomalies']) if stats else '',
            'kept_moves': '\n'.join(stats['kept'] + stats['created']) if stats else '',
            'message': error or '',
        })

    # ------------------------------------------------------------------ exécution
    def _run(self, execute):
        self.ensure_one()
        funds = self._get_funds()
        collected = [self._collect(fund) for fund in funds]
        blockers = self._blockers(funds, collected)
        if blockers:
            self.write({'has_blockers': True, 'simulated_key': False})
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
        key = self._selection_key()
        if execute:
            self._create_audit(stats, execute, error)
            self.write({'done': not error, 'simulated_key': False if not error else self.simulated_key,
                        'has_blockers': False, 'confirm_text': False})
        else:
            self.write({'has_blockers': bool(error), 'simulated_key': False if error else key})
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
        if self.env['ir.config_parameter'].sudo().get_param(self.APPLY_PARAM) != 'True':
            raise UserError(_(
                "L'exécution réelle est désactivée par le paramètre système « %s » (absent ou différent de \"True\"). "
                "Un administrateur technique doit l'activer explicitement.") % self.APPLY_PARAM)
        if (self.confirm_text or '').strip() != self.PHRASE:
            raise UserError(_('Tapez exactement « %s » pour confirmer.') % self.PHRASE)
        if not self.simulated_key or self.simulated_key != self._selection_key():
            raise UserError(_("Lancez d'abord la simulation de cette même sélection (la sélection a changé ou n'a pas "
                              "été simulée)."))
        self._acquire_lock_or_raise()
        return self._run(execute=True)

    def action_reset(self):
        self.ensure_one()
        self.write({'simulated_key': False, 'has_blockers': False, 'done': False, 'confirm_text': False, 'log': False})
        self.line_ids.unlink()
        self.balance_ids.unlink()
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}
