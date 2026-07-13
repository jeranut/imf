# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

CREDIT_TYPES = ('deposit', 'interest_credit')
DEBIT_TYPES = ('withdrawal', 'fee_debit', 'auto_debit', 'transfer')


class MicrofinanceSavingsTransaction(models.Model):
    _name = 'microfinance.savings.transaction'
    _description = "Transaction sur compte d'épargne microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    account_id = fields.Many2one('microfinance.savings.account', string='Compte épargne', required=True, ondelete='restrict', tracking=True)
    transaction_type = fields.Selection([
        ('deposit', 'Dépôt'),
        ('withdrawal', 'Retrait'),
        ('interest_credit', 'Intérêt crédité'),
        ('fee_debit', 'Frais prélevés'),
        ('auto_debit', 'Prélèvement automatique'),
        ('transfer', 'Virement entre comptes'),
    ], string='Type de transaction', required=True, tracking=True)
    amount = fields.Monetary(string='Montant', required=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    payment_method = fields.Selection([
        ('cash', 'Espèces'),
        ('bank_transfer', 'Virement'),
        ('mobile_money', 'Mobile money'),
        ('cheque', 'Chèque'),
    ], string='Moyen de paiement', default='cash')
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('posted', 'Comptabilisé'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', tracking=True)
    cheque_state = fields.Selection([
        ('en_attente', 'En attente'),
        ('compense', 'Compensé'),
        ('rejete', 'Rejeté'),
    ], string='État du chèque', copy=False, readonly=True, tracking=True,
        help="Ne concerne que les dépôts par chèque (payment_method='cheque', "
             "transaction_type='deposit') : un retrait par chèque n'est pas pris en charge par "
             "ce mécanisme (voir docs_dev/savings/ecarts_lpf.md).",
    )
    clearing_move_id = fields.Many2one(
        'account.move', string='Écriture de compensation', readonly=True, copy=False,
        help="Écriture générée par action_clear_cheque(), transférant le montant du compte "
             "d'attente chèques (account_cheques_attente_id) vers le compte du journal de "
             "dépôt. Vide tant que le chèque n'est pas compensé.",
    )
    move_id = fields.Many2one('account.move', string='Écriture comptable', readonly=True, copy=False)
    note = fields.Text(string='Note')
    related_loan_payment_id = fields.Many2one(
        'microfinance.loan.payment', readonly=True, copy=False, string='Paiement crédit lié',
        help='Renseigné uniquement pour un prélèvement automatique (auto_debit).',
    )
    bypass_min_balance = fields.Boolean(
        string='Déroger au solde minimum', default=False,
        help='Si activé, ce retrait peut faire descendre le solde sous le solde minimum du produit '
             "(clôture de compte, ou prélèvement automatique quand le produit de crédit l'autorise "
             'explicitement).',
    )
    bypass_withdrawal_limit = fields.Boolean(
        string='Déroger au plafond de retrait', default=False,
        help='Si activé, ce retrait peut dépasser le plafond de retrait par transaction du '
             'produit (ex. clôture de compte). Dérogation distincte de "Déroger au solde '
             'minimum" : les deux règles sont indépendantes.',
    )
    bypass_cash_balance = fields.Boolean(
        string='Déroger au contrôle de solde de caisse', default=False,
        help="Si activé, la transaction est autorisée même si le solde comptable du journal "
             "concerné (uniquement vérifié pour un journal de type 'Espèces') deviendrait "
             "négatif. Dérogation distincte des autres contrôles de retrait.",
    )
    partner_id = fields.Many2one(related='account_id.partner_id', store=True, readonly=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='account_id.currency_id', readonly=True)
    product_id = fields.Many2one(related='account_id.product_id', readonly=True)

    @api.constrains('amount')
    def _check_amount(self):
        for txn in self:
            if txn.amount <= 0:
                raise ValidationError(_('Le montant de la transaction doit être positif.'))

    @api.constrains('transaction_type', 'amount', 'bypass_min_balance', 'account_id')
    def _check_minimum_balance(self):
        # Ce contrôle se déclenche à la création de la transaction (encore en 'draft', donc pas
        # encore comptée dans account_id.balance) : le solde projeté est simplement le solde actuel
        # diminué du montant du retrait.
        for txn in self:
            if txn.transaction_type not in ('withdrawal', 'auto_debit') or txn.bypass_min_balance:
                continue
            min_balance = txn.account_id.product_id.min_balance
            projected_balance = txn.account_id.balance - txn.amount
            if projected_balance < min_balance - 0.01:
                raise ValidationError(_(
                    'Retrait refusé : le solde après retrait (%(projected).2f) descendrait sous le '
                    'solde minimum du produit (%(minimum).2f).'
                ) % {'projected': projected_balance, 'minimum': min_balance})

    @api.constrains('date', 'account_id', 'state')
    def _check_transaction_date_order(self):
        # Comparaison à la date maximale des autres transactions déjà comptabilisées sur le même
        # compte (pas d'horodatage dans le modèle) : une date strictement antérieure est refusée,
        # une date égale reste acceptée puisque l'ordre de saisie du jour est de toute façon
        # départagé par l'id (croissant à la création, jamais réutilisé).
        for txn in self:
            other_posted = txn.account_id.transaction_ids.filtered(
                lambda t: t.state == 'posted' and t.id != txn.id
            )
            if not other_posted:
                continue
            last_date = max(other_posted.mapped('date'))
            if txn.date < last_date:
                raise ValidationError(_(
                    'Transaction refusée : la date (%(date)s) est antérieure à la dernière '
                    'transaction déjà comptabilisée sur ce compte (%(last)s). Les transactions '
                    'doivent être saisies dans l\'ordre chronologique.'
                ) % {'date': txn.date, 'last': last_date})

    @api.constrains('transaction_type', 'amount', 'bypass_withdrawal_limit', 'account_id')
    def _check_withdrawal_limit(self):
        # Blocage simple par transaction individuelle uniquement (pas de cumul sur une période :
        # non demandé, absent du manuel LPF, écarté pour ne pas introduire une règle métier non
        # validée). Dérogation via son propre flag, distinct de bypass_min_balance. Ne s'applique
        # que si le journal de retrait du produit est de type 'cash' : un retrait viré par
        # banque n'est pas soumis à ce plafond, la contrainte étant liée à la manipulation
        # physique d'espèces (même principe que _check_disbursement_limit côté crédit,
        # microfinance_loan.py).
        for txn in self:
            if txn.transaction_type != 'withdrawal' or txn.bypass_withdrawal_limit:
                continue
            product = txn.account_id.product_id
            limit = product.withdrawal_limit_amount
            if not limit:
                continue
            journal = product.withdrawal_journal_id
            if not journal or journal.type != 'cash':
                continue
            if txn.amount > limit + 0.01:
                raise ValidationError(_(
                    'Retrait refusé : le montant (%(amount).2f) dépasse le plafond de retrait '
                    'par transaction du produit (%(limit).2f).'
                ) % {'amount': txn.amount, 'limit': limit})

    def _compute_early_withdrawal_penalty(self):
        """Pénalité de retrait anticipé (§5/§6) : ne s'applique qu'à un retrait client (pas à un
        prélèvement automatique ni à un virement), au taux unique configuré sur le produit
        (early_withdrawal_penalty_rate), déclenchée par l'une OU l'autre des deux échéances
        suivantes si configurée et pas encore atteinte — jamais cumulée si les deux le sont :
          - maturity_date du compte (uniquement pour un produit à terme, product_type =
            'term_deposit') ;
          - min_retention_days depuis l'ouverture du compte (n'importe quel produit, y compris
            épargne libre). Calculé depuis account.opening_date : ce modèle ne suit pas les
            dépôts individuellement (solde fongible, pas de lots par dépôt), donc il n'existe pas
            d'autre référence temporelle exploitable que l'ouverture du compte, cohérente avec le
            calcul déjà fait pour maturity_date."""
        self.ensure_one()
        account = self.account_id
        product = account.product_id
        if self.transaction_type != 'withdrawal' or not product.early_withdrawal_penalty_rate:
            return 0.0
        before_maturity = bool(account.maturity_date) and self.date < account.maturity_date
        before_retention_end = False
        if product.min_retention_days and account.opening_date:
            retention_end = account.opening_date + relativedelta(days=product.min_retention_days)
            before_retention_end = self.date < retention_end
        if not before_maturity and not before_retention_end:
            return 0.0
        return self.amount * product.early_withdrawal_penalty_rate / 100.0

    def _check_cash_journal_balance(self):
        """Solde comptable réel du journal concerné (withdrawal_journal_id.default_account_id.
        current_balance, champ calculé standard Odoo sur account.account) : blocage dur si la
        transaction ferait passer ce compte sous zéro, sauf dérogation explicite
        (bypass_cash_balance). Ne s'applique qu'aux transactions qui utilisent réellement ce
        journal comme contrepartie (withdrawal, auto_debit, transfer — pas fee_debit, qui
        utilise account_commission_id, cf. _prepare_transaction_move), et seulement si le
        journal est de type 'cash' et si le produit a explicitement activé
        check_cash_balance_at_withdrawal (désactivé par défaut : voir le help de ce champ pour
        la raison) — même principe que _check_disbursement_limit côté crédit
        (microfinance_loan.py)."""
        for txn in self:
            product = txn.account_id.product_id
            if (txn.bypass_cash_balance or not product.check_cash_balance_at_withdrawal
                    or txn.transaction_type not in ('withdrawal', 'auto_debit', 'transfer')):
                continue
            journal = product.withdrawal_journal_id or product.deposit_journal_id
            if not journal or journal.type != 'cash' or not journal.default_account_id:
                continue
            account = journal.default_account_id
            projected_balance = account.current_balance - txn.amount
            if projected_balance < 0:
                raise UserError(_(
                    'Transaction refusée : solde insuffisant sur le journal de caisse '
                    '« %(journal)s » (disponible : %(balance).2f, demandé : %(amount).2f).'
                ) % {'journal': journal.name, 'balance': account.current_balance, 'amount': txn.amount})

    def _prepare_transaction_move(self):
        self.ensure_one()
        account = self.account_id
        product = account.product_id
        deposit_account = product._get_account('epargne', account.partner_id)
        if not deposit_account:
            raise UserError(_("Configurez le compte épargne sur le produit %s.") % product.name)
        label_by_type = {
            'deposit': _('Dépôt épargne %s') % account.name,
            'withdrawal': _('Retrait épargne %s') % account.name,
            'interest_credit': _('Intérêt crédité épargne %s') % account.name,
            'fee_debit': _('Frais de tenue de compte %s') % account.name,
            'auto_debit': _('Prélèvement automatique sur épargne %s') % account.name,
            'transfer': _('Virement épargne %s') % account.name,
        }
        label = label_by_type[self.transaction_type]
        if self.transaction_type in CREDIT_TYPES:
            if self.transaction_type == 'interest_credit':
                interest_account = product._get_account('interet_paye', account.partner_id)
                if not interest_account:
                    raise UserError(_("Configurez le compte intérêt payé sur le produit %s.") % product.name)
                counterpart_account = interest_account
            elif self.transaction_type == 'deposit' and self.payment_method == 'cheque':
                # Compte d'attente chèques plutôt que le compte du journal : le montant n'est
                # transféré vers le compte réel qu'à la compensation (action_clear_cheque), ou
                # intégralement contre-passé en cas de rejet (action_reject_cheque).
                if not product.account_cheques_attente_id:
                    raise UserError(_("Configurez le compte d'attente chèques sur le produit %s.") % product.name)
                counterpart_account = product.account_cheques_attente_id
            else:
                journal = product.deposit_journal_id
                if not journal or not journal.default_account_id:
                    raise UserError(_('Configurez le journal de dépôt et son compte par défaut sur le produit %s.') % product.name)
                counterpart_account = journal.default_account_id
            lines = [
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': counterpart_account.id, 'debit': self.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': deposit_account.id, 'debit': 0.0, 'credit': self.amount}),
            ]
        else:
            if self.transaction_type == 'fee_debit':
                if not product.account_commission_id:
                    raise UserError(_('Configurez le compte commission sur épargne sur le produit %s.') % product.name)
                counterpart_account = product.account_commission_id
            else:
                journal = product.withdrawal_journal_id
                if not journal or not journal.default_account_id:
                    raise UserError(_('Configurez le journal de retrait et son compte par défaut sur le produit %s.') % product.name)
                counterpart_account = journal.default_account_id
            penalty_amount = self._compute_early_withdrawal_penalty()
            if penalty_amount:
                if not product.account_penalites_id:
                    raise UserError(_("Configurez le compte pénalités sur épargne sur le produit %s.") % product.name)
                if penalty_amount >= self.amount:
                    raise UserError(_(
                        "La pénalité de retrait anticipé calculée (%(penalty).2f) est supérieure ou "
                        "égale au montant retiré (%(amount).2f) : vérifiez le taux configuré sur le "
                        "produit %(product)s."
                    ) % {'penalty': penalty_amount, 'amount': self.amount, 'product': product.name})
                lines = [
                    (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': deposit_account.id, 'debit': self.amount, 'credit': 0.0}),
                    (0, 0, {'name': _('Pénalité de retrait anticipé %s') % account.name, 'partner_id': account.partner_id.id, 'account_id': product.account_penalites_id.id, 'debit': 0.0, 'credit': penalty_amount}),
                    (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': counterpart_account.id, 'debit': 0.0, 'credit': self.amount - penalty_amount}),
                ]
            else:
                lines = [
                    (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': deposit_account.id, 'debit': self.amount, 'credit': 0.0}),
                    (0, 0, {'name': label, 'partner_id': account.partner_id.id, 'account_id': counterpart_account.id, 'debit': 0.0, 'credit': self.amount}),
                ]
        journal_for_move = (
            product.deposit_journal_id if self.transaction_type in CREDIT_TYPES and self.transaction_type != 'interest_credit'
            else product.withdrawal_journal_id or product.deposit_journal_id
        )
        if not journal_for_move:
            raise UserError(_('Configurez au moins un journal (dépôt ou retrait) sur le produit %s.') % product.name)
        return {
            'date': self.date,
            'journal_id': journal_for_move.id,
            'ref': label,
            'microfinance_savings_account_id': account.id,
            'microfinance_savings_transaction_id': self.id,
            'line_ids': lines,
        }

    def action_post(self):
        for txn in self:
            if txn.state != 'draft':
                continue
            if txn.transaction_type in ('withdrawal', 'auto_debit', 'transfer') and txn.account_id.state != 'active':
                raise UserError(_('Les retraits ne sont autorisés que sur un compte épargne actif.'))
            if txn.transaction_type == 'deposit' and txn.account_id.state not in ('draft', 'active'):
                raise UserError(_('Dépôt impossible sur un compte clôturé ou dormant.'))
            txn._check_cash_journal_balance()
            move = self.env['account.move'].with_context(
                default_loan_id=False, default_loan_line_id=False,
            ).create(txn._prepare_transaction_move())
            move.action_post()
            vals = {'move_id': move.id, 'state': 'posted'}
            if txn.transaction_type == 'deposit' and txn.payment_method == 'cheque':
                vals['cheque_state'] = 'en_attente'
            txn.write(vals)
            txn.account_id.message_post(body=_('Transaction %(type)s de %(amount).2f comptabilisée. Écriture : %(move)s') % {
                'type': dict(txn._fields['transaction_type'].selection).get(txn.transaction_type),
                'amount': txn.amount, 'move': move.name,
            })

    def action_clear_cheque(self):
        for txn in self:
            if txn.transaction_type != 'deposit' or txn.payment_method != 'cheque':
                raise UserError(_('Seul un dépôt par chèque peut être compensé.'))
            if txn.cheque_state != 'en_attente':
                raise UserError(_(
                    "Ce chèque n'est plus en attente (état actuel : %s)."
                ) % dict(txn._fields['cheque_state'].selection).get(txn.cheque_state))
            product = txn.account_id.product_id
            journal = product.deposit_journal_id
            waiting_account = product.account_cheques_attente_id
            if not journal or not journal.default_account_id:
                raise UserError(_('Configurez le journal de dépôt et son compte par défaut sur le produit %s.') % product.name)
            if not waiting_account:
                raise UserError(_("Configurez le compte d'attente chèques sur le produit %s.") % product.name)
            waiting_line = txn.move_id.line_ids.filtered(lambda l: l.account_id == waiting_account)
            amount = sum(waiting_line.mapped('debit'))
            move = self.env['account.move'].with_context(
                default_loan_id=False, default_loan_line_id=False,
            ).create({
                'date': fields.Date.context_today(txn),
                'journal_id': journal.id,
                'ref': _('Compensation chèque - %s') % txn.account_id.name,
                'microfinance_savings_account_id': txn.account_id.id,
                'microfinance_savings_transaction_id': txn.id,
                'line_ids': [
                    (0, 0, {'name': _('Compensation chèque'), 'partner_id': txn.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': amount, 'credit': 0.0}),
                    (0, 0, {'name': _('Compensation chèque'), 'partner_id': txn.partner_id.id, 'account_id': waiting_account.id, 'debit': 0.0, 'credit': amount}),
                ],
            })
            move.action_post()
            txn.write({'cheque_state': 'compense', 'clearing_move_id': move.id})
            txn.account_id.message_post(body=_('Chèque compensé. Écriture : %s') % move.name)

    def action_reject_cheque(self, reason=None):
        for txn in self:
            if txn.transaction_type != 'deposit' or txn.payment_method != 'cheque':
                raise UserError(_('Seul un dépôt par chèque peut être rejeté.'))
            if txn.cheque_state != 'en_attente':
                raise UserError(_(
                    "Ce chèque n'est plus en attente (état actuel : %s)."
                ) % dict(txn._fields['cheque_state'].selection).get(txn.cheque_state))
            # Le solde du compte a déjà intégré ce dépôt (state='posted' dès la comptabilisation,
            # indépendamment de cheque_state) : si le client a depuis retiré une partie de ces
            # fonds, la contre-passation ferait passer le solde sous le minimum du produit.
            projected_balance = txn.account_id.balance - txn.amount
            min_balance = txn.account_id.product_id.min_balance
            if projected_balance < min_balance - 0.01:
                raise UserError(_(
                    'Rejet refusé : le solde du compte après contre-passation (%(projected).2f) '
                    'descendrait sous le solde minimum du produit (%(minimum).2f). Le client a '
                    'probablement déjà utilisé une partie de ce dépôt.'
                ) % {'projected': projected_balance, 'minimum': min_balance})
            move = txn.move_id
            move._check_fiscalyear_lock_date()
            move._reverse_moves(default_values_list=[{
                'date': fields.Date.context_today(txn),
                'ref': _('Contre-passation chèque rejeté - %s') % (reason or _('Non renseigné')),
            }], cancel=True)
            txn.write({'cheque_state': 'rejete', 'state': 'cancelled'})
            txn.account_id.message_post(body=_('Chèque rejeté : %s') % (reason or _('Non renseigné')))
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_savings_account_id = fields.Many2one('microfinance.savings.account', string='Compte épargne microfinance', index=True, copy=False)
    microfinance_savings_transaction_id = fields.Many2one('microfinance.savings.transaction', string='Transaction épargne microfinance', index=True, copy=False)
