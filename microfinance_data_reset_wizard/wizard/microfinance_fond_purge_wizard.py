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
            funds = Fond.browse(self.fond_ids.ids).exists()
        elif self.scope in ('credit', 'exploitation'):
            funds = Fond.search([('destination', '=', self.scope)])
        else:
            funds = Fond.search([])
        if self.company_ids:
            companies = self.company_ids.ids
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
