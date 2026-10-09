# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Produit d'épargne souscrit (libellé UI). Le compte du client est microfinance.savings.holder.account
# (docs_dev/epargne_split/) : tout produit y est rattaché (account_id) et numéroté
# <numéro du compte>-<rang sur 2 chiffres>, le rang n'étant jamais réutilisé.


class MicrofinanceSavingsAccount(models.Model):
    _name = 'microfinance.savings.account'
    _description = "Produit d'épargne souscrit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    legacy_number = fields.Char(
        string='Ancien numéro', readonly=True, copy=False, index=True,
        help="Référence d'avant la scission compte / produit (ex. AD/I/000012), conservée pour "
             "retrouver les écritures et documents antérieurs.")
    account_id = fields.Many2one(
        'microfinance.savings.holder.account', string='Compte épargne', index=True, ondelete='restrict',
        tracking=True, copy=False,
        help="Compte épargne du titulaire dans l'agence, résolu (ou créé) automatiquement à la "
             "souscription ; ne change plus ensuite.")
    rank = fields.Integer(string='Rang', readonly=True, copy=False,
                          help="Rang du produit dans son compte, jamais réutilisé.")
    partner_id = fields.Many2one('res.partner', string='Titulaire', required=True, tracking=True)
    # Transition (scission 17.0.1.7.0) : colonne conservée pour la migration des anciens conteneurs,
    # plus utilisée par le code ni affichée ; retirée après le passage 2.
    is_container = fields.Boolean(string='Ancien conteneur', default=False, copy=False, readonly=True)
    product_id = fields.Many2one('microfinance.savings.product', string="Produit d'épargne", tracking=True)
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
        'microfinance.loan', string='Crédit lié', domain="[('partner_id', '=', partner_id)]",
        help="Renseigné quand ce compte est une épargne obligatoire constituée pour un crédit précis.",
    )
    transaction_ids = fields.One2many('microfinance.savings.transaction', 'account_id', string='Transactions')
    transaction_count = fields.Integer(string='Nombre de transactions', compute='_compute_counts')
    loan_count = fields.Integer(compute='_compute_loan_count')
    loan_account_id = fields.Many2one(
        'microfinance.loan.account', string='Compte crédit', compute='_compute_loan_account_id',
    )
    last_transaction_date = fields.Date(string='Dernière transaction', compute='_compute_last_transaction_date', store=True)
    is_dormant = fields.Boolean(compute='_compute_is_dormant', string='Éligible dormance')
    closure_reason_type = fields.Selection([
        ('client_request', 'Demande client'),
        ('prolonged_dormancy', 'Dormance prolongée'),
        ('other', 'Autre'),
    ], string='Motif de clôture')
    closure_reason_note = fields.Text(string='Note de clôture')

    _sql_constraints = [
        ('account_rank_unique', 'unique(account_id, rank)', "Ce rang existe déjà dans ce compte épargne."),
    ]

    @api.constrains('account_id', 'product_id', 'state')
    def _check_no_duplicate_product_per_account(self):
        """Un même produit d'épargne ne peut pas être souscrit deux fois en même temps sur le
        même compte (titulaire) : un produit fermé (clôturé) ne compte plus, un client peut donc
        se réabonner à un même produit après clôture du précédent. Migration (réattachement des
        anciens conteneurs) exemptée : des doublons hérités de l'ancien format ne doivent pas
        faire échouer un write() de rattachement, déjà safepointé ligne par ligne côté script."""
        if self.env.context.get('savings_split_migration'):
            return
        for account in self:
            if not account.account_id or not account.product_id or account.state == 'closed':
                continue
            duplicate = self.search([
                ('id', '!=', account.id),
                ('account_id', '=', account.account_id.id),
                ('product_id', '=', account.product_id.id),
                ('state', '!=', 'closed'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "%(partner)s a déjà un produit « %(product)s » ouvert (%(existing)s) sur ce "
                    "compte épargne : impossible d'en attribuer un second tant que le premier "
                    "n'est pas clôturé."
                ) % {
                    'partner': account.partner_id.display_name,
                    'product': account.product_id.display_name,
                    'existing': duplicate.display_name,
                })

    @api.model_create_multi
    def create(self, vals_list):
        # Garde d'attribution (docs_dev/attribution_epargne_client/) : le menu « Produits
        # d'épargne » pose ce contexte (consultation seule, cf. son action) ; seuls les points
        # d'entrée légitimes (smart button client, bouton Épargne du crédit) posent en plus le
        # flag d'attribution. Portée volontairement limitée à ce seul contexte : migration,
        # tests, load_test, guichet, wizards ne posent jamais savings_menu_readonly et ne sont
        # donc jamais affectés (cf. docs_dev/attribution_epargne_client/STATUS.md, étape 0).
        if self.env.context.get('savings_menu_readonly') and not self.env.context.get('microfinance_savings_attribution'):
            raise UserError(_(
                "L'attribution d'un produit d'épargne se fait depuis la fiche client "
                "(bouton Épargne)."))
        Holder = self.env['microfinance.savings.holder.account']
        # Défauts du contexte (bouton « Épargne » du crédit) appliqués avant de résoudre le compte.
        vals_list = [self._add_missing_default_values(vals) for vals in vals_list]
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
            # Cohérence agence (point 6) : un agent n'attribue un produit qu'à un client de sa
            # propre agence. microfinance.savings.holder_account._check_coherence() refuse déjà
            # structurellement un compte dont l'agence diffère de celle du titulaire (même
            # ValidationError, déjà couverte par test_product_of_other_agency_client_rejected) ;
            # ce contrôle-ci donne un message métier plus clair, AVANT d'atteindre cette
            # contrainte générique, dans le cas le plus courant (agence active différente de
            # celle du client).
            if partner.company_id and company != partner.company_id:
                raise ValidationError(_(
                    "Impossible d'attribuer un produit d'épargne à %(partner)s pour l'agence "
                    "%(company)s : ce client appartient à l'agence %(partner_company)s."
                ) % {
                    'partner': partner.display_name, 'company': company.display_name,
                    'partner_company': partner.company_id.display_name,
                })
            holder = Holder.browse(vals['account_id']) if vals.get('account_id') else Holder._get_or_create_for(partner, company)
            vals['account_id'] = holder.id
            vals['rank'] = holder.sudo()._reserve_rank()
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = '%s-%02d' % (holder.name, vals['rank'])
        return super().create(vals_list)

    def write(self, vals):
        if 'account_id' in vals and not self.env.context.get('savings_split_migration'):
            if any(product.account_id and product.account_id.id != vals['account_id'] for product in self):
                raise UserError(_("Le compte épargne d'un produit ne peut plus être changé après sa création."))
        return super().write(vals)

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

    @api.depends('account_id.loan_account_id')
    def _compute_loan_account_id(self):
        for account in self:
            account.loan_account_id = account.account_id.loan_account_id

    def action_view_loan_account(self):
        self.ensure_one()
        if not self.loan_account_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compte crédit'),
            'res_model': 'microfinance.loan.account',
            'view_mode': 'form',
            'res_id': self.loan_account_id.id,
        }

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
        if not self.product_id:
            raise UserError(_("%s n'est pas un produit d'épargne : aucune transaction possible.") % self.name)
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

    @api.constrains('microfinance_loan_id', 'partner_id')
    def _check_microfinance_loan_partner_match(self):
        # Le domain= posé sur le champ (ci-dessus) ne protège que la sélection depuis le
        # formulaire - un import, un appel ORM direct ou un menu de création sans contexte crédit
        # le contournent sans effort. Cf. docs_dev/epargne_exigee_display/
        # AUDIT_COMPLEMENT_credit_lie.md : rien ne garantissait jusqu'ici que le crédit lié
        # appartienne bien au titulaire du compte.
        for account in self:
            if account.microfinance_loan_id and account.microfinance_loan_id.partner_id != account.partner_id:
                raise ValidationError(_(
                    "Le crédit lié (%(loan)s) appartient à %(loan_partner)s, pas à %(account_partner)s "
                    "(titulaire de ce compte épargne)."
                ) % {
                    'loan': account.microfinance_loan_id.name,
                    'loan_partner': account.microfinance_loan_id.partner_id.name,
                    'account_partner': account.partner_id.name,
                })

    @api.constrains('product_id', 'account_id', 'partner_id', 'company_id')
    def _check_product_and_account(self):
        for product in self:
            if not product.product_id:
                raise ValidationError(_("Le produit d'épargne est obligatoire."))
            account = product.account_id
            if not account:
                raise ValidationError(_("Un produit d'épargne doit être rattaché à un compte épargne."))
            if account.partner_id != product.partner_id or account.company_id != product.company_id:
                raise ValidationError(_(
                    "Le produit %(name)s doit avoir le même titulaire et la même agence que son compte "
                    "épargne %(account)s."
                ) % {'name': product.name, 'account': account.name})

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
                # sudo() scopé à cette seule création (même motif que _run_posting_sudo côté
                # guichet, cf. microfinance_caisse_mouvement.py) : la clôture est accessible à
                # tout utilisateur ayant accès à la fiche compte (bouton sans groups=), donc à
                # group_savings_agent - qui n'a plus create sur microfinance.savings.transaction
                # (ir.model.access.csv, verrouillage de la création directe hors guichet). Sans
                # ce sudo, la clôture d'un compte à solde non nul échouerait pour tout
                # agent/caissier.
                account.sudo()._create_transaction(
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

    @api.model
    def get_account_transactions(self, account_id, company_id=False):
        """Historique des transactions d'un compte épargne, pour le panneau des onglets
        « Dépôt épargne » / « Retrait épargne » du guichet (affiché sous le compte
        sélectionné). Même présentation que la page « Transactions » de la fiche compte, sans
        la colonne « Écriture comptable ». Trié par date décroissante.

        Réutilise les champs deposit_amount / withdrawal_amount déjà calculés sur la
        transaction (aucun recalcul ici). `company_id` optionnel, vérifié en défense en
        profondeur (comme get_loan_schedule / get_pending_or_late de ce chantier) : renvoie []
        si le compte n'appartient pas à l'agence de la session."""
        account = self.browse(account_id)
        if not account.exists() or (company_id and account.company_id.id != company_id):
            return []
        method_labels = dict(
            self.env['microfinance.savings.transaction']._fields['payment_method'].selection)
        transactions = account.transaction_ids.sorted(key=lambda t: (t.date, t.id), reverse=True)
        return [{
            'id': txn.id,
            'date': txn.date,
            'deposit_amount': txn.deposit_amount,
            'withdrawal_amount': txn.withdrawal_amount,
            'payment_method': txn.payment_method,
            'payment_method_label': method_labels.get(txn.payment_method, txn.payment_method or ''),
        } for txn in transactions]

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
        active_accounts = self.search([('state', '=', 'active'), ('product_id', '!=', False)])
        dormant = active_accounts.filtered(lambda a: a.is_dormant)
        if dormant:
            dormant.write({'state': 'dormant'})
            for account in dormant:
                account.message_post(body=_('Compte marqué dormant : aucune transaction depuis %s mois.') % (
                    account.company_id.savings_dormancy_months or 6
                ))
        return True
