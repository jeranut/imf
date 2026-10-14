# -*- coding: utf-8 -*-
"""Balance d'ouverture : une par société, saisie en brouillon puis validée en UNE écriture comptable (journal des
à-nouveaux) à la date d'ouverture, après quoi elle est verrouillée. Niveau comptable seulement : l'import des clients,
crédits et épargnes avec contrôle de concordance est la suite (voir docs_dev/balance_ouverture/STATUS.md).

Patron suivi : le relevé bancaire papier (brouillon / validé, verrou, chatter). Aucun SQL : tout passe par l'ORM."""
from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError, ValidationError

from . import microfinance_opening_xlsx as xlsx

JOURNAL_CODE_PARAM = 'microfinance.opening_journal_code'  # journal des à-nouveaux (code), « AN » par défaut
JOURNAL_CODE_DEFAULT = 'AN'
LOCKED_FIELDS = {'company_id', 'date', 'line_ids'}


class MicrofinanceOpeningTemplate(models.Model):
    """Comptes proposés par « Charger le modèle » (liste configurable). Les comptes de trésorerie des journaux de la société
    et les comptes de fonds s'ajoutent dynamiquement : voir MicrofinanceOpeningBalance._template_accounts."""
    _name = 'microfinance.opening.template'
    _description = "Compte du modèle de balance d'ouverture"
    _order = 'sequence, code'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='Code du compte', required=True)
    block = fields.Char(string='Bloc', help="Regroupement d'affichage (trésorerie, crédit, épargne, fonds propres…).")
    active = fields.Boolean(default=True)

    _sql_constraints = [('code_unique', 'unique(code)', "Ce compte est déjà dans le modèle.")]


class MicrofinanceOpeningBalance(models.Model):
    _name = 'microfinance.opening.balance'
    _description = "Balance d'ouverture"
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', string='Société', required=True, default=lambda self: self.env.company,
                                 index=True, tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(string="Date d'ouverture", required=True, default=fields.Date.context_today, tracking=True,
                       copy=False, help="Date de l'écriture d'ouverture ; figée à la validation.")
    state = fields.Selection([('draft', 'Brouillon'), ('validated', 'Validée')], string='État', default='draft',
                             required=True, copy=False, tracking=True)
    line_ids = fields.One2many('microfinance.opening.balance.line', 'balance_id', string='Lignes', copy=True)
    move_id = fields.Many2one('account.move', string="Écriture d'ouverture", readonly=True, copy=False)
    total_debit = fields.Monetary(string='Total débit', compute='_compute_totals', currency_field='currency_id')
    total_credit = fields.Monetary(string='Total crédit', compute='_compute_totals', currency_field='currency_id')
    difference = fields.Monetary(string='Écart (débit - crédit)', compute='_compute_totals', currency_field='currency_id')
    line_count = fields.Integer(string='Lignes', compute='_compute_totals')

    # ------------------------------------------------------------------ calculs
    @api.depends('company_id', 'date')
    def _compute_name(self):
        for balance in self:
            balance.name = _("Balance d'ouverture - %(company)s - %(date)s") % {
                'company': balance.company_id.name or '', 'date': balance.date and balance.date.strftime('%d/%m/%Y') or ''}

    @api.depends('line_ids.debit', 'line_ids.credit')
    def _compute_totals(self):
        for balance in self:
            debit, credit = sum(balance.line_ids.mapped('debit')), sum(balance.line_ids.mapped('credit'))
            balance.total_debit, balance.total_credit = debit + 0.0, credit + 0.0
            balance.difference = balance._no_negative_zero(debit - credit)
            balance.line_count = len(balance.line_ids)

    def _no_negative_zero(self, value):
        """Montant arrondi à la devise de la société, jamais -0.0 (qui s'afficherait « -0,00 »)."""
        currency = self.company_id.currency_id
        return (currency.round(value) if currency else round(value, 2)) + 0.0

    # ------------------------------------------------------------------ une seule balance par société
    @api.model
    def _existing_for_company(self, company_id):
        """Balance déjà créée pour CETTE société (jamais globalement). sudo : on veut savoir si elle existe, même si
        l'utilisateur ne la voit pas."""
        return self.sudo().with_context(active_test=False).search([('company_id', '=', company_id)], limit=1)

    @api.model
    def _check_no_balance_for_company(self, company_id):
        """Refuse la création d'une seconde balance dans une société qui en a déjà une (brouillon ou validée).
        La clé de contexte mf_opening_allow_multiple n'est lue qu'en mode test (suite de tests existante)."""
        if self.env.context.get('mf_opening_allow_multiple') and tools.config['test_enable']:
            return
        existing = self._existing_for_company(company_id)
        if existing:
            raise UserError(_(
                "Une balance d'ouverture existe déjà pour cette société (%s). Ouvrez-la au lieu d'en créer une nouvelle."
            ) % (_('validée') if existing.state == 'validated' else _('brouillon')))

    @api.model
    def default_get(self, fields_list):
        # Appelé par le client web à l'ouverture du formulaire « Nouveau » (onchange sans champ modifié) : le formulaire
        # ne s'ouvre pas. Limité aux demandes portant company_id ; create() garde le filet côté serveur.
        if 'company_id' in fields_list:
            self._check_no_balance_for_company(self.env.company.id)
        return super().default_get(fields_list)

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access_rights('create')  # les droits d'abord : un profil sans droit reçoit l'erreur d'accès
        companies = [vals.get('company_id') or self.env.company.id for vals in vals_list]
        for company_id in set(companies):
            self._check_no_balance_for_company(company_id)
        if len(companies) != len(set(companies)):
            raise UserError(_("Une seule balance d'ouverture par société."))
        return super().create(vals_list)

    def copy(self, default=None):
        raise UserError(_("Une balance d'ouverture ne se duplique pas : il n'y en a qu'une par société."))

    def init(self):
        super().init()
        # Filet en base : au plus un brouillon par société.
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS microfinance_opening_balance_one_draft_per_company "
            "ON microfinance_opening_balance (company_id) WHERE state = 'draft'")

    # ------------------------------------------------------------------ verrous
    @api.constrains('company_id', 'state')
    def _check_one_validated_per_company(self):
        for balance in self.filtered(lambda b: b.state == 'validated'):
            if self.search_count([('company_id', '=', balance.company_id.id), ('state', '=', 'validated'),
                                  ('id', '!=', balance.id)]):
                raise ValidationError(_("La société « %s » a déjà une balance d'ouverture validée.")
                                      % balance.company_id.name)

    def write(self, vals):
        if LOCKED_FIELDS & set(vals) and any(b.state == 'validated' for b in self):
            raise UserError(_("Une balance d'ouverture validée n'est plus modifiable."))
        return super().write(vals)

    def unlink(self):
        # Seul le RAZ microfinance (administrateur technique) peut supprimer une balance validée, à des fins de test.
        purge = self.env.context.get('mf_opening_purge') and self.env.user.has_group('base.group_system')
        if any(b.state == 'validated' for b in self) and not purge:
            raise UserError(_("Une balance d'ouverture validée ne peut pas être supprimée."))
        return super().unlink()

    # ------------------------------------------------------------------ validation
    def _opening_journal(self):
        self.ensure_one()
        code = self.env['ir.config_parameter'].sudo().get_param(JOURNAL_CODE_PARAM) or JOURNAL_CODE_DEFAULT
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('code', '=', code), ('type', '=', 'general')], limit=1)
        if not journal:
            raise UserError(_("Journal des à-nouveaux « %(code)s » introuvable dans la société « %(company)s » : créez-le "
                              "ou changez le paramètre système « %(param)s ».") % {
                'code': code, 'company': self.company_id.name, 'param': JOURNAL_CODE_PARAM})
        return journal

    def action_validate(self):
        for balance in self:
            if balance.state != 'draft':
                raise UserError(_("Seule une balance en brouillon peut être validée."))
            currency = balance.company_id.currency_id
            lines = balance.line_ids.filtered(lambda l: not currency.is_zero(l.debit) or not currency.is_zero(l.credit))
            if not lines:
                raise UserError(_("La balance n'a aucune ligne avec un montant."))
            if not currency.is_zero(sum(lines.mapped('debit')) - sum(lines.mapped('credit'))):
                raise UserError(_("La balance n'est pas équilibrée : total débit %(debit)s, total crédit %(credit)s "
                                  "(écart %(gap)s).") % {'debit': balance.total_debit, 'credit': balance.total_credit,
                                                         'gap': balance.difference})
            earlier = self.env['account.move'].search_count([
                ('company_id', '=', balance.company_id.id), ('state', '=', 'posted'), ('date', '<', balance.date)])
            if earlier:
                raise UserError(_("Il existe %(n)s écriture(s) comptabilisée(s) antérieure(s) au %(date)s dans la société "
                                  "« %(company)s » : l'ouverture doit précéder toute écriture.") % {
                    'n': earlier, 'date': balance.date.strftime('%d/%m/%Y'), 'company': balance.company_id.name})
            if self.search_count([('company_id', '=', balance.company_id.id), ('state', '=', 'validated'),
                                  ('id', '!=', balance.id)]):
                raise UserError(_("La société « %s » a déjà une balance d'ouverture validée.") % balance.company_id.name)
            journal = balance._opening_journal()
            move = self.env['account.move'].with_company(balance.company_id).create({
                'move_type': 'entry', 'journal_id': journal.id, 'date': balance.date, 'company_id': balance.company_id.id,
                'ref': balance.name,
                'line_ids': [(0, 0, {
                    'account_id': line.account_id.id, 'partner_id': line.partner_id.id, 'debit': line.debit,
                    'credit': line.credit, 'name': line.name or balance.name}) for line in lines]})
            move.action_post()
            balance.with_context(mf_opening_allow=True).write({'state': 'validated', 'move_id': move.id})
            balance.message_post(body=_("Balance validée : écriture %(move)s du %(date)s, %(n)s lignes, total %(total)s.") % {
                'move': move.name, 'date': balance.date.strftime('%d/%m/%Y'), 'n': len(lines), 'total': balance.total_debit})
        return True

    # ------------------------------------------------------------------ modèle
    def _template_accounts(self):
        """Comptes du modèle pour la société : liste configurable + comptes de trésorerie des journaux bank/cash actifs +
        comptes de fonds. Retourne un recordset account.account (ordre : code), limité à la société."""
        self.ensure_one()
        Account = self.env['account.account']
        codes = self.env['microfinance.opening.template'].search([]).mapped('code')
        accounts = Account.search([('company_id', '=', self.company_id.id), ('code', 'in', codes)])
        journals = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', 'in', ('bank', 'cash')), ('active', '=', True)])
        accounts |= journals.default_account_id
        accounts |= self.company_id.microfinance_fond_account_default_id
        if 'microfinance.fond.credit' in self.env:
            accounts |= self.env['microfinance.fond.credit'].with_context(active_test=False).search([
                ('company_id', 'in', (self.company_id.id, False))]).account_id.filtered(
                lambda a: a.company_id == self.company_id)
        return accounts.filtered(lambda a: a.company_id == self.company_id).sorted('code')

    def _missing_template_codes(self):
        self.ensure_one()
        codes = self.env['microfinance.opening.template'].search([]).mapped('code')
        found = set(self.env['account.account'].search([('company_id', '=', self.company_id.id),
                                                        ('code', 'in', codes)]).mapped('code'))
        return sorted(set(codes) - found)

    def action_load_template(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Le modèle ne se charge que dans une balance en brouillon."))
        existing = self.line_ids.account_id
        todo = self._template_accounts() - existing
        self.write({'line_ids': [(0, 0, {'account_id': account.id, 'debit': 0.0, 'credit': 0.0}) for account in todo]})
        missing = self._missing_template_codes()
        message = _("%(n)s compte(s) ajouté(s) à zéro.") % {'n': len(todo)}
        if missing:
            message += ' ' + _("Comptes du modèle absents de cette société (ignorés) : %s.") % ', '.join(missing)
        self.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("Modèle chargé"), 'message': message, 'type': 'success' if not missing else 'warning',
                           'sticky': bool(missing), 'next': {'type': 'ir.actions.client', 'tag': 'reload'}}}

    def _template_workbook(self):
        """Contenu du classeur modèle : comptes du modèle + lignes déjà saisies (montants actuels)."""
        self.ensure_one()
        by_account = {}
        for line in self.line_ids:
            by_account.setdefault(line.account_id, line)
        accounts = (self._template_accounts() | self.line_ids.account_id).sorted('code')
        rows = []
        for account in accounts:
            line = by_account.get(account)
            rows.append((account.code, account.name, line.partner_id.name if line else '',
                         line.debit if line else 0.0, line.credit if line else 0.0))
        instructions = [
            _("1. Renseignez le débit OU le crédit de chaque compte (jamais les deux) ; laissez à 0 les comptes sans solde."),
            _("2. Ne modifiez pas la colonne « Code du compte » : elle sert à retrouver le compte dans la société."),
            _("3. Vous pouvez ajouter des lignes (code d'un compte existant). Le partenaire est facultatif (nom exact)."),
            _("4. Le total des débits doit égaler le total des crédits pour pouvoir valider la balance."),
            _("5. Importez le fichier depuis la balance d'ouverture (bouton « Importer le fichier Excel »)."),
        ]
        return xlsx.build_template(self.company_id.name, self.date.strftime('%d/%m/%Y'), rows, instructions)

    def action_download_template(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': '/microfinance/opening_balance/%s/template.xlsx' % self.id}

    def action_open_import_wizard(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("L'import ne se fait que dans une balance en brouillon."))
        return {'type': 'ir.actions.act_window', 'name': _("Importer le fichier Excel"),
                'res_model': 'microfinance.opening.balance.import', 'view_mode': 'form', 'target': 'new',
                'context': {'default_balance_id': self.id}}

    # ------------------------------------------------------------------ point de départ des relevés bancaires
    @api.model
    def bank_starting_balance(self, journal, on_date):
        """Solde du compte de la banque (journal) repris par la balance d'ouverture validée de la société, si elle est datée
        au plus tard `on_date` ; None s'il n'y en a pas."""
        account = journal.default_account_id
        if not account or not on_date:
            return None
        balance = self.sudo().search([('company_id', '=', journal.company_id.id), ('state', '=', 'validated'),
                                      ('date', '<=', on_date)], limit=1)
        if not balance:
            return None
        lines = balance.line_ids.filtered(lambda l: l.account_id == account)
        return sum(lines.mapped('debit')) - sum(lines.mapped('credit')) if lines else None


class MicrofinanceOpeningBalanceLine(models.Model):
    _name = 'microfinance.opening.balance.line'
    _description = "Ligne de balance d'ouverture"
    _order = 'account_code, id'

    balance_id = fields.Many2one('microfinance.opening.balance', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='balance_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='balance_id.company_id.currency_id')
    state = fields.Selection(related='balance_id.state')
    account_id = fields.Many2one('account.account', string='Compte', required=True, check_company=True,
                                 domain="[('company_id', '=', company_id), ('deprecated', '=', False)]")
    account_code = fields.Char(related='account_id.code', store=True)
    partner_id = fields.Many2one('res.partner', string='Partenaire')
    name = fields.Char(string='Libellé')
    debit = fields.Monetary(string='Débit', currency_field='currency_id', default=0.0)
    credit = fields.Monetary(string='Crédit', currency_field='currency_id', default=0.0)

    @api.constrains('debit', 'credit')
    def _check_amounts(self):
        for line in self:
            if line.debit < 0 or line.credit < 0:
                raise ValidationError(_("Les montants ne peuvent pas être négatifs (compte %s).") % line.account_id.code)
            if line.debit and line.credit:
                raise ValidationError(_("Compte %s : renseignez le débit OU le crédit, pas les deux.") % line.account_id.code)

    @api.model_create_multi
    def create(self, vals_list):
        balances = self.env['microfinance.opening.balance'].browse([v['balance_id'] for v in vals_list if v.get('balance_id')])
        if any(b.state == 'validated' for b in balances):
            raise UserError(_("Une balance d'ouverture validée n'est plus modifiable."))
        return super().create(vals_list)

    def write(self, vals):
        if any(l.balance_id.state == 'validated' for l in self):
            raise UserError(_("Une balance d'ouverture validée n'est plus modifiable."))
        return super().write(vals)

    def unlink(self):
        if any(l.balance_id.state == 'validated' for l in self):
            raise UserError(_("Une balance d'ouverture validée n'est plus modifiable."))
        return super().unlink()
