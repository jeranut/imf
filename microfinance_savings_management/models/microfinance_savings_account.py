# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceSavingsAccount(models.Model):
    _name = 'microfinance.savings.account'
    _description = "Compte d'épargne microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Titulaire', required=True, tracking=True)
    product_id = fields.Many2one('microfinance.savings.product', string="Produit d'épargne", required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('active', 'Actif'),
        ('dormant', 'Dormant'),
        ('closed', 'Clôturé'),
    ], string='État', default='draft', tracking=True, index=True)
    balance = fields.Monetary(compute='_compute_balance', store=True, string='Solde')
    opening_date = fields.Date(string="Date d'ouverture", readonly=True)
    closing_date = fields.Date(string='Date de clôture', readonly=True)
    maturity_date = fields.Date(compute='_compute_maturity_date', store=True, string='Date d\'échéance')
    microfinance_loan_id = fields.Many2one(
        'microfinance.loan', string='Crédit lié',
        help="Renseigné quand ce compte est une épargne obligatoire constituée pour un crédit précis.",
    )
    transaction_ids = fields.One2many('microfinance.savings.transaction', 'account_id', string='Transactions')
    transaction_count = fields.Integer(string='Nombre de transactions', compute='_compute_counts')
    loan_count = fields.Integer(compute='_compute_loan_count')
    last_transaction_date = fields.Date(string='Dernière transaction', compute='_compute_last_transaction_date', store=True)
    is_dormant = fields.Boolean(compute='_compute_is_dormant', string='Éligible dormance')
    closure_reason_type = fields.Selection([
        ('client_request', 'Demande client'),
        ('prolonged_dormancy', 'Dormance prolongée'),
        ('other', 'Autre'),
    ], string='Motif de clôture')
    closure_reason_note = fields.Text(string='Note de clôture')

    # Code de type de compte (convention LPF AGENCE/TYPE/SÉRIE) : dérivé de la catégorie du
    # produit (product_type), jamais du titulaire — un compte classique reçoit I quel que soit
    # le client (individuel ou entreprise), une épargne de garantie liée à un crédit reçoit G,
    # un dépôt à terme reçoit T. Avant ce correctif, la lettre dépendait du type de client
    # (individuel/groupe/entreprise) : un compte classique et un compte de garantie du même
    # client individuel étaient alors indiscernables (tous deux 'I'), et 'G' n'était jamais
    # atteignable (microfinance_client_type n'a plus la valeur 'group' depuis la suppression de
    # ce type de client). Décision validée par Micka : la lettre E disparaît (plus de distinction
    # par titulaire dans le numéro de compte).
    _PRODUCT_TYPE_CODE = {'voluntary': 'I', 'compulsory': 'G', 'term_deposit': 'T'}

    def _get_account_type_code(self, product):
        return self._PRODUCT_TYPE_CODE.get(product.product_type, 'I')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                # agency_code est obligatoire sur res.company (NOT NULL) : toute société valide
                # en possède un, pas besoin de re-vérifier ici.
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                product = self.env['microfinance.savings.product'].browse(vals.get('product_id'))
                type_code = self._get_account_type_code(product)
                vals['name'] = self._get_savings_account_name(company, partner, type_code)
        return super().create(vals_list)

    def _get_savings_account_name(self, company, partner, type_code):
        """Le 1er compte épargne d'un type donné pour un client reprend le numéro de compte
        permanent du client (AGENCE/TYPE/NNNNNN, même suffixe numérique que
        partner.microfinance_account_number : IS/000001 -> IS/I/000001) — synchronisé
        mécaniquement, sans séquence propre, cf. correctif numérotation à trois niveaux.
        Un compte supplémentaire du même type pour le même client (cas réel : épargne
        obligatoire liée à un crédit en parallèle d'une épargne volontaire, ou plusieurs
        comptes volontaires) ne peut pas reprendre ce même numéro sans collision : il garde
        l'ancienne numérotation par séquence indépendante, propre à ce type, pour rester
        unique.

        Les deux mécanismes (dérivation directe et séquence indépendante) partagent le même
        espace de numéros AGENCE/TYPE/NNNNNN sans se coordonner entre eux : sans vérification,
        rien n'empêche qu'un numéro déjà pris par l'un soit retiré par l'autre (dans les deux
        sens, pas seulement à la toute première utilisation) — cf. bug détecté par
        test_second_account_same_type_falls_back_to_independent_sequence. D'où la vérification
        d'unicité explicite ci-dessous avant de retenir un candidat, avec repli sur la séquence
        indépendante (en boucle si besoin) tant que le nom dérivé est déjà pris."""
        existing_same_type = self.search([('partner_id', '=', partner.id)]).filtered(
            lambda a: self._get_account_type_code(a.product_id) == type_code
        )
        if not existing_same_type and partner.microfinance_account_number:
            agency, suffix = partner.microfinance_account_number.split('/', 1)
            candidate = '%s/%s/%s' % (agency, type_code, suffix)
            if not self.search_count([('name', '=', candidate)]):
                return candidate
        return self._get_next_available_savings_account_name(company, type_code)

    def _get_next_available_savings_account_name(self, company, type_code):
        while True:
            number = company._get_or_create_numbering_sequence('microfinance.savings.account.%s' % type_code)
            candidate = '%s/%s/%s' % (company.agency_code, type_code, number)
            if not self.search_count([('name', '=', candidate)]):
                return candidate

    @api.depends('transaction_ids.amount', 'transaction_ids.transaction_type', 'transaction_ids.state')
    def _compute_balance(self):
        positive_types = ('deposit', 'interest_credit')
        for account in self:
            posted = account.transaction_ids.filtered(lambda t: t.state == 'posted')
            credit = sum(posted.filtered(lambda t: t.transaction_type in positive_types).mapped('amount'))
            debit = sum(posted.filtered(lambda t: t.transaction_type not in positive_types).mapped('amount'))
            account.balance = credit - debit

    @api.depends('opening_date', 'product_id.product_type', 'product_id.term_months')
    def _compute_maturity_date(self):
        for account in self:
            if account.product_id.product_type == 'term_deposit' and account.opening_date and account.product_id.term_months:
                account.maturity_date = account.opening_date + relativedelta(months=account.product_id.term_months)
            else:
                account.maturity_date = False

    @api.depends('transaction_ids.date', 'transaction_ids.state')
    def _compute_last_transaction_date(self):
        for account in self:
            posted = account.transaction_ids.filtered(lambda t: t.state == 'posted')
            account.last_transaction_date = max(posted.mapped('date')) if posted else False

    def _compute_is_dormant(self):
        today = fields.Date.context_today(self)
        for account in self:
            reference_date = account.last_transaction_date or account.opening_date
            if not reference_date or account.state != 'active':
                account.is_dormant = False
                continue
            months = account.company_id.savings_dormancy_months or 6
            account.is_dormant = reference_date + relativedelta(months=months) <= today

    def _compute_counts(self):
        for account in self:
            account.transaction_count = len(account.transaction_ids)

    @api.depends('partner_id.microfinance_loan_ids')
    def _compute_loan_count(self):
        for account in self:
            account.loan_count = len(account.partner_id.microfinance_loan_ids)

    def action_view_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crédits'),
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.partner_id.id)],
            'context': {'default_partner_id': self.partner_id.id},
        }

    def _create_transaction(self, transaction_type, amount, note=None, bypass_min_balance=False,
                             bypass_withdrawal_limit=False, bypass_cash_balance=False,
                             related_loan_payment_id=False, date=None, payment_method='cash'):
        self.ensure_one()
        transaction = self.env['microfinance.savings.transaction'].create({
            'account_id': self.id,
            'transaction_type': transaction_type,
            'amount': amount,
            'date': date or fields.Date.context_today(self),
            'note': note,
            'bypass_min_balance': bypass_min_balance,
            'bypass_withdrawal_limit': bypass_withdrawal_limit,
            'bypass_cash_balance': bypass_cash_balance,
            'related_loan_payment_id': related_loan_payment_id,
            'payment_method': payment_method,
        })
        transaction.action_post()
        return transaction

    def action_activate(self):
        for account in self:
            if account.state != 'draft':
                raise UserError(_('Seul un compte en brouillon peut être activé.'))
            if account.product_id.min_opening_amount and account.balance < account.product_id.min_opening_amount:
                raise UserError(_(
                    "Le solde doit atteindre le montant minimum d'ouverture (%.2f) avant activation."
                ) % account.product_id.min_opening_amount)
            account.write({'state': 'active', 'opening_date': account.opening_date or fields.Date.context_today(account)})
        return True

    def action_close(self, reason_type=None, reason_note=None):
        for account in self:
            if account.state == 'closed':
                continue
            if (account.microfinance_loan_id and account.microfinance_loan_id.state == 'active'
                    and account.product_id.product_type == 'compulsory'):
                raise UserError(_(
                    'Impossible de clôturer : ce compte est une épargne obligatoire liée à un crédit '
                    'actif (%s).'
                ) % account.microfinance_loan_id.name)
            if abs(account.balance) > 0.01:
                account._create_transaction(
                    'withdrawal', abs(account.balance), note=_('Retrait total avant clôture'),
                    bypass_min_balance=True, bypass_withdrawal_limit=True,
                )
            account.write({
                'state': 'closed',
                'closing_date': fields.Date.context_today(account),
                'closure_reason_type': reason_type or account.closure_reason_type or 'other',
                'closure_reason_note': reason_note or account.closure_reason_note,
            })
        return True

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Transactions'), 'res_model': 'microfinance.savings.transaction',
            'view_mode': 'tree,form', 'domain': [('account_id', '=', self.id)], 'context': {'default_account_id': self.id},
        }

    _CAPITALIZATION_PERIOD = {
        'monthly': relativedelta(months=1),
        'quarterly': relativedelta(months=3),
        'annual': relativedelta(months=12),
    }

    def _reference_balance(self, period_start, period_end):
        """Solde de référence sur [period_start, period_end], selon la méthode du produit
        (solde minimum / moyen / de clôture), reconstitué à partir des transactions comptabilisées
        dans la fenêtre plutôt que d'un solde journalier stocké (non conservé par le modèle)."""
        self.ensure_one()
        product = self.product_id
        if product.balance_method == 'closing_balance':
            return self.balance
        positive_types = ('deposit', 'interest_credit')
        txns = self.transaction_ids.filtered(
            lambda t: t.state == 'posted' and period_start <= t.date <= period_end
        ).sorted('date')
        delta_in_window = sum((t.amount if t.transaction_type in positive_types else -t.amount) for t in txns)
        running_balance = self.balance - delta_in_window
        checkpoints = []
        previous_date = period_start
        for txn in txns:
            days = (txn.date - previous_date).days
            if days > 0:
                checkpoints.append((running_balance, days))
            running_balance += txn.amount if txn.transaction_type in positive_types else -txn.amount
            previous_date = txn.date
        trailing_days = (period_end - previous_date).days
        if trailing_days > 0 or not checkpoints:
            checkpoints.append((running_balance, max(trailing_days, 0) or 1))
        if product.balance_method == 'min_balance':
            return min(balance for balance, _days in checkpoints)
        total_days = sum(days for _balance, days in checkpoints)
        return sum(balance * days for balance, days in checkpoints) / total_days if total_days else self.balance

    def cron_capitalize_interest(self, frequency):
        today = fields.Date.context_today(self)
        period_start = today - self._CAPITALIZATION_PERIOD[frequency]
        accounts = self.search([('state', '=', 'active'), ('product_id.capitalization_frequency', '=', frequency)])
        for account in accounts:
            product = account.product_id
            reference_balance = account._reference_balance(period_start, today)
            if reference_balance <= 0 or not product.interest_rate:
                continue
            period_days = (today - period_start).days
            amount = reference_balance * (product.interest_rate / 100.0) * (period_days / 365.0)
            if amount <= 0.005:
                continue
            txn = account._create_transaction('interest_credit', amount, note=_('Capitalisation des intérêts'))
            account.message_post(body=_(
                'Capitalisation des intérêts : période %(start)s → %(end)s, méthode %(method)s, '
                'solde de référence %(ref).2f, taux %(rate)s%%, montant crédité %(amount).2f. Écriture : %(move)s'
            ) % {
                'start': period_start, 'end': today,
                'method': dict(product._fields['balance_method'].selection).get(product.balance_method),
                'ref': reference_balance, 'rate': product.interest_rate, 'amount': amount, 'move': txn.move_id.name,
            })
        return True

    @api.model
    def cron_detect_dormant_accounts(self):
        active_accounts = self.search([('state', '=', 'active')])
        dormant = active_accounts.filtered(lambda a: a.is_dormant)
        if dormant:
            dormant.write({'state': 'dormant'})
            for account in dormant:
                account.message_post(body=_('Compte marqué dormant : aucune transaction depuis %s mois.') % (
                    account.company_id.savings_dormancy_months or 6
                ))
        return True
