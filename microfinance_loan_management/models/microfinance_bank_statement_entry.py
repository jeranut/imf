# -*- coding: utf-8 -*-
"""Ligne saisie d'un relevé bancaire papier et son traitement.

Trois traitements, choisis à la saisie ou après coup :
  - rapprocher : vraie ligne de relevé (comptabilisée) dont la contrepartie est la ligne en attente choisie, puis
    lettrage par le moteur d'Odoo ;
  - pointer : marque une ligne déjà postée directement sur le compte de banque, SANS créer d'écriture (sinon le
    mouvement serait compté deux fois sur le compte de banque) ;
  - nouvelle opération : frais, intérêts, agios… sur un compte choisi (324100 en attente avec alerte sinon).
Convention de saisie : « Entrée » = argent reçu sur le compte (débit comptable de la banque), « Sortie » = argent
sorti (crédit comptable de la banque).
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .microfinance_bank_statement import GROUP_ACCOUNTANT, GROUP_ACCOUNT_MANAGER

TREATMENTS = [('reconcile', 'Rapprocher avec une ligne en attente'), ('point', 'Pointer une écriture bancaire existante'),
              ('new', 'Nouvelle opération (frais, intérêts…)')]


class MicrofinanceBankStatementEntry(models.Model):
    _name = 'microfinance.bank.statement.entry'
    _description = 'Ligne de relevé bancaire papier'
    _order = 'statement_id, sequence, date, id'

    statement_id = fields.Many2one('account.bank.statement', string='Relevé', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='statement_id.company_id', store=True, index=True)
    journal_id = fields.Many2one(related='statement_id.journal_id', store=True)
    currency_id = fields.Many2one('res.currency', related='statement_id.currency_id')
    sequence = fields.Integer(default=10)
    date = fields.Date(string="Date d'opération")
    value_date = fields.Date(string='Date de valeur')
    name = fields.Char(string='Libellé', required=True)
    reference = fields.Char(string='Référence / n° de chèque')
    amount_in = fields.Monetary(string='Entrée', currency_field='currency_id')
    amount_out = fields.Monetary(string='Sortie', currency_field='currency_id')
    amount = fields.Monetary(string='Montant', currency_field='currency_id', compute='_compute_amount', store=True,
                             help="Entrée moins sortie : positif = argent reçu, négatif = argent sorti.")
    treatment = fields.Selection(TREATMENTS, string='Traitement')
    target_line_id = fields.Many2one('account.move.line', string='Ligne choisie', check_company=False)
    candidate_line_ids = fields.Many2many('account.move.line', compute='_compute_candidates')
    suggested_line_id = fields.Many2one('account.move.line', string='Suggestion', compute='_compute_candidates')
    account_id = fields.Many2one('account.account', string='Compte (nouvelle opération)', check_company=False)
    state = fields.Selection([('todo', 'À traiter'), ('done', 'Traitée')], default='todo', required=True, copy=False,
                             index=True)
    statement_line_id = fields.Many2one('account.bank.statement.line', string='Ligne de relevé comptable',
                                        readonly=True, copy=False)
    pointed_line_id = fields.Many2one('account.move.line', string='Écriture pointée', readonly=True, copy=False)
    to_check = fields.Boolean(string='À vérifier', readonly=True, copy=False,
                              help="Nouvelle opération laissée sur le compte en attente de rapprochement.")
    log_ids = fields.One2many('microfinance.bank.statement.log', 'entry_id', string='Historique')

    _sql_constraints = [
        ('amount_sign', 'check(amount_in >= 0 and amount_out >= 0)', "Les entrées et sorties ne peuvent pas être négatives."),
    ]

    # ------------------------------------------------------------------ calculs
    @api.depends('amount_in', 'amount_out')
    def _compute_amount(self):
        for entry in self:
            entry.amount = (entry.amount_in or 0.0) - (entry.amount_out or 0.0)

    def _candidate_domain(self):
        """Lignes proposées selon le traitement : lignes non lettrées des comptes d'attente du journal (rapprocher) ou
        lignes de la banque non pointées et qui ne sont pas elles-mêmes une ligne de relevé (pointer)."""
        self.ensure_one()
        journal, sign_ok = self.journal_id, ('balance', '>', 0) if self.amount > 0 else ('balance', '<', 0)
        base = [('parent_state', '=', 'posted'), ('company_id', '=', self.company_id.id), sign_ok]
        if self.treatment == 'point':
            return base + [('account_id', '=', journal.default_account_id.id), ('mf_pointed_entry_id', '=', False),
                           ('move_id.statement_line_id', '=', False)]
        return base + [('account_id', 'in', journal.sudo()._mf_pending_accounts().ids), ('reconciled', '=', False)]

    @api.depends('treatment', 'amount', 'date', 'reference', 'journal_id', 'state')
    def _compute_candidates(self):
        Line = self.env['account.move.line'].sudo()
        for entry in self:
            lines = Line.browse()
            suggested = Line.browse()
            if entry.state == 'todo' and entry.journal_id and entry.amount and entry.treatment in (False, 'reconcile', 'point'):
                lines = Line.search(entry._candidate_domain(), order='date desc, id desc', limit=200)
                suggested = entry._suggest(lines)
            entry.candidate_line_ids = lines
            entry.suggested_line_id = suggested

    def _suggest(self, lines):
        """Meilleure ligne par montant (exact, ou dans la tolérance de la société), puis date et référence.
        Jamais appliquée sans clic de l'utilisateur."""
        self.ensure_one()
        tolerance = self.company_id.mf_bank_tolerance or 0.0
        currency = self.statement_id._mf_currency()
        best, best_score = lines.browse(), None
        for line in lines:
            gap = abs(self.amount - line.balance)
            if currency.compare_amounts(gap, tolerance) > 0:
                continue
            days = abs((line.date - self.date).days) if self.date and line.date else 9999
            ref_hit = bool(self.reference and self.reference.strip().lower() in
                           ' '.join(filter(None, [line.name, line.ref, line.move_id.name])).lower())
            score = (gap, 0 if ref_hit else 1, days)
            if best_score is None or score < best_score:
                best, best_score = line, score
        return best

    def action_take_suggestion(self):
        for entry in self:
            if entry.suggested_line_id:
                entry.write({'treatment': entry.treatment or 'reconcile', 'target_line_id': entry.suggested_line_id.id})
        return True

    @api.onchange('treatment')
    def _onchange_treatment(self):
        self.target_line_id = False

    # ------------------------------------------------------------------ verrou d'un relevé validé
    def _fill_missing_dates(self):
        previous = False
        for entry in self.sorted(lambda e: (e.sequence, e.id)):
            if not entry.date:
                entry.date = previous or entry.statement_id.mf_date_from
            previous = entry.date

    @api.model_create_multi
    def create(self, vals_list):
        statements = self.env['account.bank.statement'].browse([v['statement_id'] for v in vals_list if v.get('statement_id')])
        if any(s.mf_state == 'validated' for s in statements):
            raise UserError(_("Un relevé validé n'est plus modifiable."))
        last_dates = {}
        for stmt in statements.sudo():
            if not stmt.journal_id and not self.env.su:
                raise UserError(_("Choisissez le journal bancaire du relevé avant d'enregistrer ses lignes."))
            self.env['account.bank.statement']._mf_check_company_allowed(stmt.journal_id.company_id)
        for vals in vals_list:
            if vals.get('statement_id'):  # société posée à l'insertion, jamais déduite d'un enregistrement non enregistré
                vals['company_id'] = self.env['account.bank.statement'].sudo().browse(
                    vals['statement_id']).journal_id.company_id.id
            if not vals.get('date') and vals.get('statement_id'):
                stmt = self.env['account.bank.statement'].browse(vals['statement_id'])
                vals['date'] = last_dates.get(stmt.id) or (stmt.mf_entry_ids.sorted('id')[-1:].date) or stmt.mf_date_from
            last_dates[vals.get('statement_id')] = vals.get('date')
        return super().create(vals_list)

    TREATMENT_FIELDS = {'state', 'statement_line_id', 'pointed_line_id', 'to_check', 'log_ids'}

    def write(self, vals):
        if set(vals) - self.TREATMENT_FIELDS - {'treatment', 'target_line_id', 'account_id', 'sequence'}:
            if any(e.statement_id.mf_state == 'validated' for e in self):
                raise UserError(_("Un relevé validé n'est plus modifiable : rouvrez-le (comptable) avec un motif."))
            if any(e.state == 'done' for e in self):
                raise UserError(_("Une ligne traitée n'est plus modifiable : annulez d'abord son traitement."))
        return super().write(vals)

    def unlink(self):
        if any(e.state == 'done' or e.statement_id.mf_state == 'validated' for e in self):
            raise UserError(_("Une ligne traitée ou d'un relevé validé ne peut pas être supprimée."))
        return super().unlink()

    # ------------------------------------------------------------------ traitement
    def _env_company(self):
        self.ensure_one()
        company = self.company_id
        return self.sudo().with_company(company).with_context(allowed_company_ids=[company.id])

    def _log(self, action, reason=False, detail=False):
        self.env['microfinance.bank.statement.log'].sudo().create({
            'entry_id': self.id, 'statement_id': self.statement_id.id, 'action': action,
            'user_id': self.env.user.id, 'reason': reason, 'detail': detail})
        self.statement_id._mf_post(_("Ligne « %(name)s » : %(action)s") % {
            'name': self.name, 'action': dict(self.env['microfinance.bank.statement.log']._fields['action'].selection)[action]})

    def action_treat(self):
        for entry in self:
            if entry.state != 'todo':
                raise UserError(_("La ligne « %s » est déjà traitée.") % entry.name)
            if not entry.amount:
                raise UserError(_("La ligne « %s » n'a ni entrée ni sortie.") % entry.name)
            if not entry.treatment:
                raise UserError(_("Choisissez un traitement pour la ligne « %s ».") % entry.name)
            getattr(entry, '_treat_' + entry.treatment)()
        return True

    def _statement_line_vals(self, extra=None):
        self.ensure_one()
        vals = {
            'journal_id': self.journal_id.id, 'statement_id': self.statement_id.id, 'date': self.date or fields.Date.today(),
            'payment_ref': ' - '.join(filter(None, [self.name, self.reference])), 'amount': self.amount,
        }
        vals.update(extra or {})
        return vals

    def _treat_reconcile(self):
        self.ensure_one()
        entry = self._env_company()
        journal, target = entry.journal_id, entry.target_line_id
        if not target:
            raise UserError(_("Choisissez la ligne en attente à rapprocher pour « %s ».") % self.name)
        if not entry.env['account.move.line'].search_count(entry._candidate_domain() + [('id', '=', target.id)]):
            raise UserError(_("La ligne choisie n'est pas rapprochable avec cette ligne de relevé (compte, sens, société ou déjà lettrée)."))
        currency = entry.statement_id._mf_currency()
        tolerance = entry.company_id.mf_bank_tolerance or 0.0
        gap = currency.round(entry.amount - target.balance)
        st_line_vals = entry._statement_line_vals({'counterpart_account_id': target.account_id.id})
        if tolerance and gap and currency.compare_amounts(abs(gap), tolerance) <= 0:
            # Écart d'arrondi accepté : la contrepartie est exactement la ligne choisie, le reste va au compte de
            # produit (reçu en plus) ou de charge (payé en plus) du journal.
            adjust_account = journal.profit_account_id if gap > 0 else journal.loss_account_id
            if not adjust_account:
                raise UserError(_("Le journal « %s » n'a pas de compte de produit/perte pour solder l'écart d'arrondi.") % journal.display_name)
            adjust = -gap  # = target.balance - amount
            st_line_vals.pop('counterpart_account_id')
            st_line_vals['line_ids'] = [
                (0, 0, {'name': st_line_vals['payment_ref'], 'account_id': journal.default_account_id.id, 'balance': entry.amount}),
                (0, 0, {'name': st_line_vals['payment_ref'], 'account_id': target.account_id.id, 'balance': -target.balance}),
                (0, 0, {'name': _("Écart d'arrondi"), 'account_id': adjust_account.id, 'balance': adjust}),
            ]
        st_line = entry.env['account.bank.statement.line'].create(st_line_vals)
        counterpart = st_line.move_id.line_ids.filtered(lambda l: l.account_id == target.account_id)
        (target | counterpart).reconcile()
        self.write({'state': 'done', 'statement_line_id': st_line.id})
        self._log('treat', detail=_("Rapproché avec %s") % (target.move_id.name or target.display_name))

    def _treat_point(self):
        self.ensure_one()
        entry = self._env_company()
        target = entry.target_line_id
        currency = entry.statement_id._mf_currency()
        if not target:
            raise UserError(_("Choisissez l'écriture bancaire à pointer pour « %s ».") % self.name)
        if not entry.env['account.move.line'].search_count(entry._candidate_domain() + [('id', '=', target.id)]):
            raise UserError(_("Cette écriture ne peut pas être pointée : elle n'est pas sur le compte de banque du journal, "
                              "est déjà pointée, ou est elle-même une ligne de relevé."))
        if currency.compare_amounts(target.balance, entry.amount) != 0:
            raise UserError(_("Le montant de l'écriture (%(ecriture)s) diffère de celui de la ligne de relevé (%(releve)s).")
                            % {'ecriture': target.balance, 'releve': entry.amount})
        target.write({'mf_pointed_entry_id': self.id, 'mf_pointed_date': fields.Datetime.now(),
                      'mf_pointed_user_id': self.env.user.id})
        self.write({'state': 'done', 'pointed_line_id': target.id})
        self._log('treat', detail=_("Écriture pointée : %s") % (target.move_id.name or target.display_name))

    def _treat_new(self):
        self.ensure_one()
        entry = self._env_company()
        extra = {'counterpart_account_id': entry.account_id.id} if entry.account_id else {}
        st_line = entry.env['account.bank.statement.line'].create(entry._statement_line_vals(extra))
        self.write({'state': 'done', 'statement_line_id': st_line.id, 'to_check': not entry.account_id})
        self._log('treat', detail=_("Nouvelle opération sur %s") % (
            entry.account_id.display_name or _("le compte en attente de rapprochement (à vérifier)")))

    # ------------------------------------------------------------------ annulation
    def _mf_check_cancel_rights(self):
        if not (self.env.user.has_group(GROUP_ACCOUNTANT) or self.env.user.has_group(GROUP_ACCOUNT_MANAGER)):
            raise AccessError(_("L'annulation d'un rapprochement ou d'un pointage est réservée au comptable."))

    def _cancel_treatment(self, reason):
        """Défait le lettrage et extourne l'écriture de la ligne de relevé (jamais supprimée), ou retire le
        pointage. La ligne repasse « à traiter » ; utilisateur, date et motif sont tracés."""
        self._mf_check_cancel_rights()
        for entry in self:
            if entry.state != 'done':
                raise UserError(_("La ligne « %s » n'est pas traitée.") % entry.name)
            env_entry = entry._env_company()
            detail = False
            if entry.pointed_line_id:
                entry.pointed_line_id.sudo().write({'mf_pointed_entry_id': False, 'mf_pointed_date': False,
                                                    'mf_pointed_user_id': False})
                detail = _("Pointage retiré : %s") % entry.pointed_line_id.move_id.name
            if entry.statement_line_id:
                move = env_entry.statement_line_id.move_id
                reconciled = move.line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids)
                reconciled.remove_move_reconcile()
                reversal = move._reverse_moves([{
                    'date': fields.Date.context_today(entry), 'ref': _('Extourne %s') % (move.ref or move.name)}], cancel=True)
                detail = _("Lettrage défait, écriture %(ecr)s extournée (%(ext)s)") % {
                    'ecr': move.name, 'ext': reversal.name}
            entry.write({'state': 'todo', 'statement_line_id': False, 'pointed_line_id': False, 'to_check': False})
            entry._log('cancel', reason=reason, detail=detail)

    def action_open_cancel_wizard(self):
        self.ensure_one()
        self._mf_check_cancel_rights()
        return self.env['microfinance.bank.statement.cancel.wizard']._open('cancel', self)


class MicrofinanceBankStatementLog(models.Model):
    _name = 'microfinance.bank.statement.log'
    _description = "Historique d'une ligne de relevé bancaire"
    _order = 'id desc'

    entry_id = fields.Many2one('microfinance.bank.statement.entry', ondelete='cascade', index=True)
    statement_id = fields.Many2one('account.bank.statement', ondelete='cascade', index=True)
    action = fields.Selection([('treat', 'Traitée'), ('cancel', 'Traitement annulé'), ('reopen', 'Relevé rouvert')],
                              required=True)
    user_id = fields.Many2one('res.users', string='Utilisateur', required=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    reason = fields.Char(string='Motif')
    detail = fields.Char(string='Détail')


class MicrofinanceBankStatementCancelWizard(models.TransientModel):
    _name = 'microfinance.bank.statement.cancel.wizard'
    _description = "Motif d'annulation ou de réouverture"

    kind = fields.Selection([('cancel', "Annuler le traitement d'une ligne"), ('reopen', 'Rouvrir le relevé')], required=True)
    entry_id = fields.Many2one('microfinance.bank.statement.entry')
    statement_id = fields.Many2one('account.bank.statement')
    reason = fields.Char(string='Motif', required=True)

    @api.model
    def _open(self, kind, record):
        key = 'default_entry_id' if kind == 'cancel' else 'default_statement_id'
        title = _("Annuler le traitement") if kind == 'cancel' else _("Rouvrir le relevé")
        return {'type': 'ir.actions.act_window', 'name': title, 'res_model': self._name, 'view_mode': 'form',
                'target': 'new', 'context': {'default_kind': kind, key: record.id}}

    def action_confirm(self):
        self.ensure_one()
        if self.kind == 'cancel':
            self.entry_id._cancel_treatment(self.reason)
        else:
            self.statement_id._mf_reopen(self.reason)
        return {'type': 'ir.actions.act_window_close'}
