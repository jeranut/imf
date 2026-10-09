# -*- coding: utf-8 -*-
"""Relevé bancaire papier : en-tête (période, soldes imprimés, pièce jointe, état) sur account.bank.statement.

Les lignes saisies (microfinance.bank.statement.entry) restent de simples données tant qu'elles ne sont pas
traitées : une vraie account.bank.statement.line crée et comptabilise tout de suite son écriture, donc elle n'est
créée qu'au traitement de la ligne (rapprochement ou nouvelle opération). Une ligne « pointée » n'en crée aucune.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

GROUP_ACCOUNTANT = 'microfinance_loan_management.group_microfinance_comptable'
GROUP_ACCOUNT_MANAGER = 'account.group_account_manager'
LOCKED_FIELDS = {'balance_start', 'balance_end_real', 'mf_date_from', 'mf_date_to', 'journal_id'}


class AccountBankStatement(models.Model):
    _name = 'account.bank.statement'
    _inherit = ['account.bank.statement', 'mail.thread']

    mf_state = fields.Selection([('draft', 'Brouillon'), ('validated', 'Validé')], string='État du relevé',
                                copy=False, tracking=True)
    mf_date_from = fields.Date(string='Début de période')
    mf_date_to = fields.Date(string='Fin de période')
    mf_entry_ids = fields.One2many('microfinance.bank.statement.entry', 'statement_id', string='Lignes du relevé')
    mf_last_date = fields.Date(string='Date de la dernière ligne', compute='_compute_mf_last_date')
    mf_balance_computed = fields.Monetary(string='Solde calculé', compute='_compute_mf_balance')
    mf_gap = fields.Monetary(string='Écart avec le solde final', compute='_compute_mf_balance')
    mf_todo_count = fields.Integer(string='Lignes à traiter', compute='_compute_mf_balance')
    mf_has_attachment = fields.Boolean(compute='_compute_mf_balance')

    # ------------------------------------------------------------------ nom
    @api.depends('create_date', 'journal_id', 'mf_date_from', 'mf_date_to', 'mf_state', 'date')
    def _compute_name(self):
        """« <code du journal> – <début> → <fin> » (dates courtes) ; un élément manquant est omis, jamais écrit « False » ;
        sans journal : « Nouveau relevé ». Un relevé validé garde son nom ; en brouillon il suit journal et période."""
        for stmt in self:
            if stmt.mf_state == 'validated' and stmt.name:
                continue
            code = stmt.journal_id.code
            if not code:
                stmt.name = _("Nouveau relevé")
                continue
            start, end = stmt.mf_date_from or stmt.date, stmt.mf_date_to
            period = ' → '.join(d.strftime('%d/%m/%y') for d in (start, end) if d)
            stmt.name = ' – '.join(filter(None, [code, period]))

    # ------------------------------------------------------------------ calculs
    @api.depends('line_ids.journal_id')
    def _compute_journal_id(self):
        # Natif : journal = celui des lignes. Un relevé papier en brouillon n'a pas encore de ligne comptable
        # (les lignes saisies ne deviennent des lignes de relevé qu'à leur traitement) : on garde son journal.
        for stmt in self:
            stmt.journal_id = stmt.line_ids.journal_id[:1] or stmt.journal_id

    @api.depends('mf_entry_ids.date')
    def _compute_mf_last_date(self):
        for stmt in self:
            dates = stmt.mf_entry_ids.mapped('date')
            stmt.mf_last_date = max([d for d in dates if d], default=stmt.mf_date_from)

    def _mf_currency(self):
        """Devise du relevé : celle du journal, sinon celle de sa société, sinon celle de la société courante (formulaire
        « Nouveau » avant le choix du journal). Jamais vide."""
        self.ensure_one()
        journal = self.journal_id
        return journal.currency_id or journal.company_id.currency_id or self.env.company.currency_id

    @api.depends('journal_id', 'balance_start', 'balance_end_real', 'mf_entry_ids.amount', 'mf_entry_ids.state',
                 'attachment_ids')
    def _compute_mf_balance(self):
        for stmt in self:
            stmt.mf_balance_computed = stmt.balance_start + sum(stmt.mf_entry_ids.mapped('amount'))
            # Sans journal (relevé « Nouveau » à l'ouverture du formulaire) : pas d'écart calculable, donc 0 sans
            # arrondir ; l'arrondi lit la précision de la devise du journal une fois celui-ci choisi.
            stmt.mf_gap = (stmt._mf_currency().round(stmt.balance_end_real - stmt.mf_balance_computed)
                           if stmt.journal_id else 0.0)
            stmt.mf_todo_count = len(stmt.mf_entry_ids.filtered(lambda e: e.state == 'todo'))
            stmt.mf_has_attachment = bool(stmt.attachment_ids)

    @api.onchange('journal_id', 'mf_date_from')
    def _onchange_mf_previous_balance(self):
        if self.journal_id and self.mf_date_from and self.mf_state:
            previous = self._mf_previous()
            if previous:
                self.balance_start = previous.balance_end_real

    def _mf_post(self, body):
        """Message de traçabilité dans le fil du relevé. L'expéditeur est toujours renseigné (utilisateur, sinon société,
        sinon OdooBot) : un utilisateur sans adresse e-mail ne doit pas bloquer une validation ou une annulation."""
        self.ensure_one()
        sender = (self.env.user.email_formatted or self.env.company.email_formatted
                  or self.env.ref('base.partner_root').email_formatted)
        return self.message_post(body=body, email_from=sender)

    # ------------------------------------------------------------------ chaînage des relevés
    def _mf_previous(self):
        """Dernier relevé validé du même journal qui se termine avant le début de celui-ci."""
        self.ensure_one()
        domain = [('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'),
                  ('mf_date_to', '<', self.mf_date_from)]
        if self._origin.id:  # relevé « Nouveau » (NewId) : rien à exclure
            domain.append(('id', '!=', self._origin.id))
        return self.sudo().search(domain, order='mf_date_to desc, id desc', limit=1)

    def _mf_next(self):
        self.ensure_one()
        domain = [('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'),
                  ('mf_date_from', '>', self.mf_date_to)]
        if self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        return self.sudo().search(domain, order='mf_date_from asc, id asc', limit=1)

    # ------------------------------------------------------------------ contrôles et validation
    def _mf_check_before_validation(self):
        self.ensure_one()
        currency = self._mf_currency()
        if self.journal_id.type != 'bank':
            raise UserError(_("Un relevé bancaire se saisit sur un journal de type banque."))
        if not self.mf_date_from or not self.mf_date_to or self.mf_date_from > self.mf_date_to:
            raise UserError(_("Renseignez la période du relevé (début ≤ fin)."))
        if not self.mf_entry_ids:
            raise UserError(_("Le relevé n'a aucune ligne."))
        outside = self.mf_entry_ids.filtered(lambda e: not (self.mf_date_from <= e.date <= self.mf_date_to))
        if outside:
            raise UserError(_("Des lignes ont une date hors de la période du relevé (%s).") % ', '.join(
                fields.Date.to_string(d) for d in outside.mapped('date')))
        overlap = self.sudo().search([
            ('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'), ('id', '!=', self.id),
            ('mf_date_from', '<=', self.mf_date_to), ('mf_date_to', '>=', self.mf_date_from)], limit=1)
        if overlap:
            raise UserError(_("La période chevauche celle du relevé validé « %s ».") % overlap.display_name)
        if currency.compare_amounts(self.balance_start + sum(self.mf_entry_ids.mapped('amount')),
                                    self.balance_end_real) != 0:
            raise UserError(_(
                "Les soldes sont incohérents : solde initial %(debut)s + entrées − sorties = %(calcule)s, "
                "mais le solde final imprimé est %(final)s (écart %(ecart)s)."
            ) % {'debut': self.balance_start, 'calcule': self.mf_balance_computed, 'final': self.balance_end_real,
                 'ecart': self.mf_gap})
        previous = self._mf_previous()
        if previous and currency.compare_amounts(self.balance_start, previous.balance_end_real) != 0:
            raise UserError(_(
                "Le solde initial (%(debut)s) ne reprend pas le solde final du relevé précédent « %(prec)s » "
                "(%(fin)s) : une page du relevé manque peut-être."
            ) % {'debut': self.balance_start, 'prec': previous.display_name, 'fin': previous.balance_end_real})
        following = self._mf_next()
        if following and currency.compare_amounts(following.balance_start, self.balance_end_real) != 0:
            raise UserError(_(
                "Le solde final (%(fin)s) ne correspond pas au solde initial (%(debut)s) du relevé suivant « %(suiv)s »."
            ) % {'fin': self.balance_end_real, 'debut': following.balance_start, 'suiv': following.display_name})

    def action_mf_validate(self):
        for stmt in self:
            if stmt.mf_state != 'draft':
                raise UserError(_("Seul un relevé en brouillon peut être validé."))
            stmt._mf_check_before_validation()
            stmt.mf_entry_ids._fill_missing_dates()
            stmt.with_context(mf_allow=True).mf_state = 'validated'
            body = _("Relevé validé : %(n)s lignes, solde initial %(debut)s, solde final %(fin)s.") % {
                'n': len(stmt.mf_entry_ids), 'debut': stmt.balance_start, 'fin': stmt.balance_end_real}
            if not stmt.attachment_ids:
                body += ' ' + _("Attention : aucune pièce jointe (scan ou photo du relevé papier).")
            stmt._mf_post(body)
        return True

    def _mf_check_reopen_rights(self):
        if not (self.env.user.has_group(GROUP_ACCOUNTANT) or self.env.user.has_group(GROUP_ACCOUNT_MANAGER)):
            raise AccessError(_("La réouverture d'un relevé est réservée au comptable."))

    def _mf_reopen(self, reason):
        self._mf_check_reopen_rights()
        for stmt in self:
            if stmt.mf_state != 'validated':
                raise UserError(_("Seul un relevé validé peut être rouvert."))
            stmt.with_context(mf_allow=True).mf_state = 'draft'
            stmt._mf_post(_("Relevé rouvert par %(user)s. Motif : %(motif)s") % {
                'user': self.env.user.name, 'motif': reason})
            self.env['microfinance.bank.statement.log'].sudo().create({
                'statement_id': stmt.id, 'action': 'reopen', 'user_id': self.env.user.id, 'reason': reason})

    def action_mf_open_reopen_wizard(self):
        self.ensure_one()
        self._mf_check_reopen_rights()
        return self.env['microfinance.bank.statement.cancel.wizard']._open('reopen', self)

    def action_mf_treat_all(self):
        self.mf_entry_ids.filtered(lambda e: e.state == 'todo' and e.treatment).action_treat()
        return True

    # ------------------------------------------------------------------ société
    @api.model
    def _mf_check_company_allowed(self, company):
        """La société du journal doit être cochée dans le sélecteur de sociétés : sinon la règle multi-sociétés
        refuserait la ligne avec un message technique. Les accès administrateur (sudo) ne passent pas par les règles."""
        if self.env.su or not company or company in self.env.companies:
            return
        raise UserError(_("Sélectionnez la société « %s » dans le sélecteur de sociétés pour saisir ce relevé.")
                        % company.name)

    @api.model_create_multi
    def create(self, vals_list):
        journals = self.env['account.journal'].sudo()
        for vals in vals_list:
            if vals.get('mf_entry_ids') and not vals.get('journal_id') and not self.env.su:
                raise UserError(_("Choisissez le journal bancaire du relevé avant d'enregistrer ses lignes."))
            if vals.get('journal_id'):
                self._mf_check_company_allowed(journals.browse(vals['journal_id']).company_id)
        return super().create(vals_list)

    # ------------------------------------------------------------------ verrou d'un relevé validé
    def write(self, vals):
        if vals.get('journal_id'):
            self._mf_check_company_allowed(self.env['account.journal'].sudo().browse(vals['journal_id']).company_id)
        if LOCKED_FIELDS & set(vals) and not self.env.context.get('mf_allow'):
            if any(stmt.mf_state == 'validated' for stmt in self):
                raise UserError(_("Un relevé validé n'est plus modifiable : rouvrez-le (comptable) avec un motif."))
        return super().write(vals)

    def unlink(self):
        if any(stmt.mf_state == 'validated' or stmt.mf_entry_ids.filtered(lambda e: e.state == 'done')
               for stmt in self):
            raise UserError(_("Un relevé validé ou dont des lignes sont traitées ne peut pas être supprimé."))
        return super().unlink()
