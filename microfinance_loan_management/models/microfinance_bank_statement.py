# -*- coding: utf-8 -*-
"""Relevé bancaire papier : en-tête (période, soldes imprimés, pièce jointe, état) sur account.bank.statement.

Les lignes saisies (microfinance.bank.statement.entry) restent de simples données tant qu'elles ne sont pas
traitées : une vraie account.bank.statement.line crée et comptabilise tout de suite son écriture, donc elle n'est
créée qu'au traitement de la ligne (rapprochement ou nouvelle opération). Une ligne « pointée » n'en crée aucune.
"""
from datetime import datetime, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

GROUP_ACCOUNTANT = 'microfinance_loan_management.group_microfinance_comptable'
GROUP_ACCOUNT_MANAGER = 'account.group_account_manager'
LOCKED_FIELDS = {'balance_start', 'balance_end_real', 'mf_date_from', 'mf_date_to', 'mf_datetime_from',
                 'mf_datetime_to', 'journal_id'}
DEFAULT_TZ_PARAM = 'mf.default_tz'
FALLBACK_TZ = 'Indian/Antananarivo'
FMT_SHORT, FMT_LONG = '%d/%m/%y %H:%M', '%d/%m/%Y %H:%M'


class AccountBankStatement(models.Model):
    _name = 'account.bank.statement'
    _inherit = ['account.bank.statement', 'mail.thread']

    mf_state = fields.Selection([('draft', 'Brouillon'), ('validated', 'Validé')], string='État du relevé',
                                copy=False, tracking=True)
    # Champs natifs sensibles d'un relevé papier : seul le suivi est ajouté, le reste de leur définition est inchangé.
    journal_id = fields.Many2one(tracking=True)
    balance_start = fields.Monetary(tracking=True)
    balance_end_real = fields.Monetary(tracking=True)
    # Période du relevé : plage date + heure (UTC en base, heure locale à l'affichage). Obligatoire pour tout relevé papier
    # (contrôlé par contrainte : les relevés natifs d'Odoo n'en ont pas).
    mf_datetime_from = fields.Datetime(string='Début de période', tracking=True, copy=False)
    mf_datetime_to = fields.Datetime(string='Fin de période', tracking=True, copy=False)
    # Anciennes colonnes conservées : date LOCALE du début et de la fin, calculées depuis la plage.
    mf_date_from = fields.Date(string='Début de période (date)', compute='_compute_mf_dates', store=True)
    mf_date_to = fields.Date(string='Fin de période (date)', compute='_compute_mf_dates', store=True)
    mf_tz_missing = fields.Boolean(compute='_compute_mf_tz_missing')
    mf_entry_ids = fields.One2many('microfinance.bank.statement.entry', 'statement_id', string='Lignes du relevé')
    mf_last_date = fields.Date(string='Date de la dernière ligne', compute='_compute_mf_last_date')
    mf_balance_computed = fields.Monetary(string='Solde calculé', compute='_compute_mf_balance')
    mf_gap = fields.Monetary(string='Écart avec le solde final', compute='_compute_mf_balance')
    mf_todo_count = fields.Integer(string='Lignes à traiter', compute='_compute_mf_balance')
    mf_has_attachment = fields.Boolean(compute='_compute_mf_balance')

    # ------------------------------------------------------------------ fuseau horaire
    def _mf_tz(self):
        """Fuseau d'affichage : celui de l'utilisateur, sinon celui de la société du journal, sinon mf.default_tz."""
        company = self.journal_id.company_id or self.env.company
        param = self.env['ir.config_parameter'].sudo().get_param(DEFAULT_TZ_PARAM)
        user_tz = False if self.env.context.get('mf_ignore_user_tz') else self.env.user.tz
        for name in (user_tz, company.sudo().partner_id.tz, param, FALLBACK_TZ):
            if name in pytz.all_timezones_set:
                return pytz.timezone(name)

    def _mf_local(self, value):
        """Datetime UTC naïf (base) -> datetime local aware."""
        return pytz.utc.localize(value).astimezone(self._mf_tz()) if value else False

    def _mf_utc(self, local_naive):
        """Datetime local naïf -> UTC naïf (base)."""
        return self._mf_tz().localize(local_naive).astimezone(pytz.utc).replace(tzinfo=None)

    def _mf_fmt(self, value, fmt=FMT_SHORT):
        local = self._mf_local(value)
        return local.strftime(fmt) if local else ''

    def _mf_range_text(self):
        """« du JJ/MM/AAAA HH:MM au JJ/MM/AAAA HH:MM » en heure locale (messages d'erreur, trace)."""
        self.ensure_one()
        return _('du %(debut)s au %(fin)s') % {'debut': self._mf_fmt(self.mf_datetime_from, FMT_LONG) or '—',
                                             'fin': self._mf_fmt(self.mf_datetime_to, FMT_LONG) or '—'}

    @api.depends_context('uid')
    def _compute_mf_tz_missing(self):
        for stmt in self:
            stmt.mf_tz_missing = not self.env.user.tz

    @api.depends('mf_datetime_from', 'mf_datetime_to')
    def _compute_mf_dates(self):
        for stmt in self:
            start, end = stmt._mf_local(stmt.mf_datetime_from), stmt._mf_local(stmt.mf_datetime_to)
            stmt.mf_date_from = start.date() if start else False
            stmt.mf_date_to = end.date() if end else False

    def _mf_default_start(self, journal):
        """Début par défaut : fin du dernier relevé validé du journal, sinon début de la journée en heure locale."""
        last = self.sudo().search([('journal_id', '=', journal.id), ('mf_state', '=', 'validated')],
                                  order='mf_datetime_to desc, id desc', limit=1) if journal else self.browse()
        if last.mf_datetime_to:
            return last.mf_datetime_to
        today = self._mf_local(fields.Datetime.now()).date()
        return self._mf_utc(datetime.combine(today, time.min))

    def _mf_vals_dates_to_datetimes(self, vals):
        """Compatibilité : une écriture des anciens champs date devient une écriture de la plage (début 00:00:00, fin
        23:59:59, heure locale). Les anciens champs sont calculés et ne sont jamais écrits directement."""
        for old, new, clock in (('mf_date_from', 'mf_datetime_from', time.min),
                                ('mf_date_to', 'mf_datetime_to', time(23, 59, 59))):
            if old in vals:
                day = fields.Date.to_date(vals.pop(old))
                if new not in vals:
                    vals[new] = self._mf_utc(datetime.combine(day, clock)) if day else False
        return vals

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get('mf_state') == 'draft' or self.env.context.get('default_mf_state'):
            stmt = self.new({'journal_id': res.get('journal_id') or self.env.context.get('default_journal_id')})
            if 'mf_datetime_from' in fields_list and not res.get('mf_datetime_from'):
                res['mf_datetime_from'] = stmt._mf_default_start(stmt.journal_id)
            if 'mf_datetime_to' in fields_list and not res.get('mf_datetime_to'):
                res['mf_datetime_to'] = fields.Datetime.now().replace(second=0, microsecond=0)
        return res

    @api.constrains('mf_datetime_from', 'mf_datetime_to', 'mf_state')
    def _check_mf_period(self):
        for stmt in self.filtered('mf_state'):
            if not stmt.mf_datetime_from or not stmt.mf_datetime_to:
                raise ValidationError(_("Renseignez le début et la fin de la période du relevé (date et heure)."))
            if stmt.mf_datetime_to <= stmt.mf_datetime_from:
                raise ValidationError(_("La fin de la période doit être strictement après son début (%s).")
                                      % stmt._mf_range_text())

    # ------------------------------------------------------------------ nom
    @api.depends('create_date', 'journal_id', 'mf_datetime_from', 'mf_datetime_to', 'mf_state', 'date')
    def _compute_name(self):
        """« <code> – JJ/MM/AA HH:MM → JJ/MM/AA HH:MM » (« <code> – JJ/MM/AA HH:MM → HH:MM » le même jour) en heure locale ;
        un élément manquant est omis, jamais écrit « False » ; sans journal : « Nouveau relevé ». Un relevé validé garde
        son nom ; en brouillon il suit journal et période."""
        for stmt in self:
            if stmt.mf_state == 'validated' and stmt.name:
                continue
            code = stmt.journal_id.code
            if not code:
                stmt.name = _("Nouveau relevé")
                continue
            start, end = stmt._mf_local(stmt.mf_datetime_from), stmt._mf_local(stmt.mf_datetime_to)
            if start and end and start.date() == end.date():
                period = '%s → %s' % (start.strftime(FMT_SHORT), end.strftime('%H:%M'))
            else:
                period = ' → '.join(d.strftime(FMT_SHORT) for d in (start, end) if d)
            stmt.name = ' – '.join(filter(None, [code, period]))

    # ------------------------------------------------------------------ calculs
    @api.depends('line_ids.journal_id')
    def _compute_journal_id(self):
        # Natif : journal = celui des lignes. Un relevé papier en brouillon n'a pas encore de ligne comptable
        # (les lignes saisies ne deviennent des lignes de relevé qu'à leur traitement) : on garde son journal.
        for stmt in self:
            stmt.journal_id = stmt.line_ids.journal_id[:1] or stmt.journal_id

    @api.depends('mf_entry_ids.date', 'mf_date_from')
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

    @api.onchange('journal_id')
    def _onchange_mf_journal_period(self):
        # Journal choisi après l'ouverture du formulaire : le début reprend la fin du dernier relevé de CE journal.
        if self.journal_id and self.mf_state == 'draft' and not self._origin.id and not self.mf_entry_ids:
            self.mf_datetime_from = self._mf_default_start(self.journal_id)

    @api.onchange('journal_id', 'mf_datetime_from')
    def _onchange_mf_previous_balance(self):
        if self.journal_id and self.mf_datetime_from and self.mf_state:
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
        """Relevé validé du même journal dont la fin est la plus récente et ≤ au début de celui-ci."""
        self.ensure_one()
        if not self.mf_datetime_from:
            return self.browse()
        domain = [('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'),
                  ('mf_datetime_to', '<=', self.mf_datetime_from)]
        if self._origin.id:  # relevé « Nouveau » (NewId) : rien à exclure
            domain.append(('id', '!=', self._origin.id))
        return self.sudo().search(domain, order='mf_datetime_to desc, id desc', limit=1)

    def _mf_next(self):
        """Relevé validé du même journal qui commence à la fin de celui-ci ou après (le plus proche)."""
        self.ensure_one()
        if not self.mf_datetime_to:
            return self.browse()
        domain = [('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'),
                  ('mf_datetime_from', '>=', self.mf_datetime_to)]
        if self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        return self.sudo().search(domain, order='mf_datetime_from asc, id asc', limit=1)

    # ------------------------------------------------------------------ contrôles et validation
    def _mf_check_before_validation(self):
        self.ensure_one()
        currency = self._mf_currency()
        if self.journal_id.type != 'bank':
            raise UserError(_("Un relevé bancaire se saisit sur un journal de type banque."))
        if (not self.mf_datetime_from or not self.mf_datetime_to
                or self.mf_datetime_from >= self.mf_datetime_to):
            raise UserError(_("Renseignez la période du relevé (début strictement avant la fin)."))
        if not self.mf_entry_ids:
            raise UserError(_("Le relevé n'a aucune ligne."))
        # Les lignes restent datées au jour : bornes incluses, entre la date locale du début et celle de la fin.
        first, last = self._mf_local(self.mf_datetime_from).date(), self._mf_local(self.mf_datetime_to).date()
        outside = self.mf_entry_ids.filtered(lambda e: not (first <= e.date <= last))
        if outside:
            raise UserError(_("Des lignes ont une date hors de la période du relevé (%s).") % ', '.join(
                fields.Date.to_string(d) for d in outside.mapped('date')))
        # Chevauchement : début_A < fin_B ET début_B < fin_A (un relevé qui commence à la fin d'un autre est accepté).
        overlap = self.sudo().search([
            ('journal_id', '=', self.journal_id.id), ('mf_state', '=', 'validated'), ('id', '!=', self.id),
            ('mf_datetime_from', '<', self.mf_datetime_to), ('mf_datetime_to', '>', self.mf_datetime_from)], limit=1)
        if overlap:
            raise UserError(_(
                "La période de ce relevé (%(a)s) chevauche celle du relevé validé « %(n)s » (%(b)s)."
            ) % {'a': self._mf_range_text(), 'n': overlap.display_name, 'b': overlap._mf_range_text()})
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

    @api.model
    def _mf_migrate_period_datetimes(self):
        """Relevés papier existants : début = date de début à 00:00:00, fin = date de fin à 23:59:59 (heure locale de la
        société, puis mf.default_tz ; converti en UTC). Idempotent : ne touche que les relevés dont la plage est vide. Les anciens champs date sont conservés."""
        todo = self.sudo().with_context(
            mf_allow=True, tracking_disable=True, mf_ignore_user_tz=True).search([
            ('mf_state', '!=', False), ('mf_datetime_from', '=', False), ('mf_date_from', '!=', False)])
        for stmt in todo:
            stmt.write(stmt._mf_vals_dates_to_datetimes({'mf_date_from': stmt.mf_date_from,
                                                         'mf_date_to': stmt.mf_date_to}))
        return todo

    @api.model_create_multi
    def create(self, vals_list):
        journals = self.env['account.journal'].sudo()
        for vals in vals_list:
            self._mf_vals_dates_to_datetimes(vals)
            if vals.get('mf_state') or self.env.context.get('default_mf_state'):
                journal = journals.browse(vals.get('journal_id') or self.env.context.get('default_journal_id'))
                if not vals.get('mf_datetime_from'):
                    vals['mf_datetime_from'] = self.new({'journal_id': journal.id})._mf_default_start(journal)
                if not vals.get('mf_datetime_to'):
                    vals['mf_datetime_to'] = fields.Datetime.now().replace(second=0, microsecond=0)
            if vals.get('mf_entry_ids') and not vals.get('journal_id') and not self.env.su:
                raise UserError(_("Choisissez le journal bancaire du relevé avant d'enregistrer ses lignes."))
            if vals.get('journal_id'):
                self._mf_check_company_allowed(journals.browse(vals['journal_id']).company_id)
        return super().create(vals_list)

    # ------------------------------------------------------------------ verrou d'un relevé validé
    def write(self, vals):
        vals = self._mf_vals_dates_to_datetimes(dict(vals))
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
