# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


def default_payment_amount_and_journal(loan):
    """Montant et journal suggérés pour un remboursement de ce crédit — réutilisé par le
    formulaire microfinance.loan.payment et par microfinance.loan.payment.wizard, pour ne pas
    dupliquer la logique entre les deux points d'entrée de saisie d'un remboursement.
    Montant : somme des échéances déjà en retard (state == 'overdue') s'il y en a, sinon le
    montant résiduel de la toute prochaine échéance non soldée. Ne duplique pas l'allocation
    pénalité → intérêt → capital (_allocate_to_installments) : ceci ne fait que suggérer un
    montant total, l'allocation détaillée reste calculée séparément à la comptabilisation."""
    journal = loan.product_id.payment_journal_id
    overdue = loan.installment_ids.filtered(lambda i: i.state == 'overdue')
    if overdue:
        amount = sum(overdue.mapped('residual_amount'))
    else:
        next_due = loan.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(
            lambda i: (i.due_date, i.sequence)
        )[:1]
        amount = next_due.residual_amount if next_due else 0.0
    return amount, journal


class MicrofinanceLoanPayment(models.Model):
    _name = 'microfinance.loan.payment'
    _description = 'Remboursement crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True)
    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='restrict', tracking=True)
    partner_id = fields.Many2one(related='loan_id.partner_id', store=True, readonly=True)
    payment_date = fields.Date(string='Date de remboursement', default=fields.Date.context_today, required=True)
    amount = fields.Monetary(string='Montant', required=True)
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', 'in', ('bank','cash')), ('company_id', '=', company_id)]",
    )
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    # Stocké pour les agrégats read_group « remboursement encaissé par agent » du dashboard
    # portefeuille (Lot 1).
    officer_id = fields.Many2one(related='loan_id.officer_id', store=True, readonly=True, index=True, string='Agent crédit')
    # Ordre des champs = ordre de ventilation CEFOR (Décision 2) : intérêt -> principal ->
    # pénalité, cf. _allocate_to_installments() ci-dessous.
    allocated_interest = fields.Monetary(string='Intérêt alloué', readonly=True)
    allocated_principal = fields.Monetary(string='Principal alloué', readonly=True)
    allocated_penalty = fields.Monetary(string='Pénalité allouée', readonly=True)
    move_id = fields.Many2one('account.move', string='Écriture comptable', readonly=True, copy=False)
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False, string='Écriture de contre-passation')
    state = fields.Selection([('draft', 'Brouillon'), ('posted', 'Comptabilisé'), ('cancelled', 'Annulé')], string='État', default='draft', tracking=True)
    installment_ids = fields.Many2many('microfinance.loan.installment', 'microfinance_installment_payment_rel', 'payment_id', 'installment_id', string='Échéances', readonly=True)
    note = fields.Text(string='Note')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                # Séquence par société (format AGENCE/NNNNNN), alignée sur microfinance.loan et
                # microfinance.partner.account (cf. correctif numérotation Sous-lot 3) — remplace
                # l'ancienne séquence globale PAY/%(year)s/NNNNN, partagée entre toutes les
                # agences. Les remboursements déjà enregistrés gardent leur ancien numéro tel
                # quel : name n'est jamais régénéré après création (readonly, cf. déclaration du
                # champ), seuls les nouveaux remboursements utilisent ce format.
                # agency_code est obligatoire sur res.company (NOT NULL) : loan_id est required
                # sur ce modèle, sa société est donc toujours résolue ici.
                loan = self.env['microfinance.loan'].browse(vals.get('loan_id'))
                company = loan.company_id or self.env.company
                number = company._get_or_create_numbering_sequence('microfinance.loan.payment')
                vals['name'] = '%s/%s' % (company.agency_code, number)
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Le montant du remboursement doit être positif.'))

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        for payment in self:
            if not payment.loan_id:
                continue
            amount, journal = default_payment_amount_and_journal(payment.loan_id)
            if amount:
                payment.amount = amount
            if journal:
                payment.journal_id = journal

    @api.model
    def _allocation_plan(self, installments, amount):
        """Générateur (échéance, intérêt_alloué, principal_alloué, pénalité_allouée) selon la
        ventilation CEFOR (Décision 2, distincte de LPF) : intérêt dû -> principal dû ->
        pénalités, sur la tranche courante à chaque itération, avec débordement sur la ou les
        tranches suivantes (même ordre) si `amount` dépasse le total dû de la tranche courante.
        Ne mute rien (aucune écriture) : source unique de vérité, réutilisée à la fois par
        _allocate_to_installments() ci-dessous (qui applique les écritures lors d'un
        remboursement réel) et par preview_repayment_allocation() (aperçu de la ventilation côté
        interface caisse, Lot 4, avant validation — pour ne jamais dupliquer ce calcul en JS)."""
        remaining = amount
        for inst in installments:
            if remaining <= 0.01:
                break
            interest_due = max(inst.interest_amount - inst.paid_interest, 0.0)
            interest_pay = min(remaining, interest_due)
            remaining -= interest_pay
            principal_due = max(inst.principal_amount - inst.paid_principal, 0.0)
            principal_pay = min(remaining, principal_due)
            remaining -= principal_pay
            penalty_due = max(inst.penalty_amount - inst.paid_penalty, 0.0)
            penalty_pay = min(remaining, penalty_due)
            remaining -= penalty_pay
            if interest_pay or principal_pay or penalty_pay:
                yield inst, interest_pay, principal_pay, penalty_pay

    @api.model
    def preview_repayment_allocation(self, loan_id, amount):
        """Aperçu de la ventilation d'un remboursement, sans rien écrire en base — appelé par
        l'interface caisse (Lot 4) avant validation, pour afficher exactement ce que
        _allocate_to_installments() calculerait réellement au moment de la comptabilisation."""
        loan = self.env['microfinance.loan'].browse(loan_id)
        installments = loan.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(lambda i: (i.due_date, i.sequence))
        alloc_interest = alloc_principal = alloc_penalty = 0.0
        for _inst, interest_pay, principal_pay, penalty_pay in self._allocation_plan(installments, amount):
            alloc_interest += interest_pay
            alloc_principal += principal_pay
            alloc_penalty += penalty_pay
        return {
            'interest_amount': alloc_interest,
            'principal_amount': alloc_principal,
            'penalty_amount': alloc_penalty,
        }

    def _allocate_to_installments(self):
        self.ensure_one()
        if self.loan_id.state not in ('active', 'defaulted'):
            raise UserError(_('Le crédit doit être actif ou en défaut pour enregistrer un remboursement.'))
        if not self.loan_id.disbursement_date:
            # Découplage activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md) :
            # un crédit 'active' peut ne pas être encore décaissé — aucun remboursement possible
            # tant que les fonds ne sont pas sortis.
            raise UserError(_(
                "Ce crédit est activé mais pas encore décaissé : aucun remboursement ne peut "
                "être enregistré avant le décaissement effectif en caisse."))
        if self.amount > self.loan_id.balance_total + 0.01:
            raise UserError(_('Surpaiement interdit. Solde restant : %.2f') % self.loan_id.balance_total)
        installments = self.loan_id.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(lambda i: (i.due_date, i.sequence))
        alloc_interest = alloc_principal = alloc_penalty = 0.0
        touched = self.env['microfinance.loan.installment']
        for inst, interest_pay, principal_pay, penalty_pay in self._allocation_plan(installments, self.amount):
            inst.paid_interest += interest_pay
            inst.paid_principal += principal_pay
            inst.paid_penalty += penalty_pay
            alloc_interest += interest_pay
            alloc_principal += principal_pay
            alloc_penalty += penalty_pay
            touched |= inst
        self.write({
            'allocated_penalty': alloc_penalty,
            'allocated_interest': alloc_interest,
            'allocated_principal': alloc_principal,
            'installment_ids': [(6, 0, touched.ids)],
        })

    def _prepare_payment_move(self):
        self.ensure_one()
        product = self.loan_id.product_id
        if not self.journal_id.default_account_id:
            raise UserError(_('Le journal de paiement doit avoir un compte par défaut.'))
        lines = [(0, 0, {
            'name': _('Encaissement remboursement %s') % self.name,
            'partner_id': self.partner_id.id,
            'account_id': self.journal_id.default_account_id.id,
            'debit': self.amount,
            'credit': 0.0,
        })]
        if self.allocated_principal:
            principal_account = product._get_account('principal', self.partner_id)
            lines.append((0, 0, {'name': _('Capital %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': principal_account.id, 'debit': 0.0, 'credit': self.allocated_principal}))
        if self.allocated_interest:
            interest_account = product._get_account('interets_recus', self.partner_id)
            lines.append((0, 0, {'name': _('Intérêt %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': interest_account.id, 'debit': 0.0, 'credit': self.allocated_interest}))
        if self.allocated_penalty:
            if not product.account_penalites_id:
                raise UserError(_('Configurez le compte pénalités crédits du produit pour comptabiliser ce remboursement.'))
            lines.append((0, 0, {'name': _('Pénalité %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.account_penalites_id.id, 'debit': 0.0, 'credit': self.allocated_penalty}))
        return {
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'ref': _('Remboursement crédit %s') % self.loan_id.name,
            'microfinance_loan_id': self.loan_id.id,
            'microfinance_payment_id': self.id,
            'line_ids': lines,
        }

    def action_post(self):
        for payment in self:
            if payment.state != 'draft':
                continue
            payment._allocate_to_installments()
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(payment._prepare_payment_move())
            move.action_post()
            payment.write({'move_id': move.id, 'state': 'posted'})
            payment.loan_id.message_post(body=_('Remboursement %s comptabilisé : %s') % (payment.name, move.name))
            if payment.loan_id.balance_total <= 0.01:
                # Route through action_close() rather than a raw state write so its side
                # effects (releasing guarantees, etc.) also apply on this auto-close path.
                payment.loan_id.action_close()
        return True

    def action_open_cancel_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Annuler le remboursement'),
            'res_model': 'microfinance.loan.payment.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payment_id': self.id},
        }

    def action_cancel(self, reason=None):
        for payment in self:
            if payment.state == 'posted':
                payment._reverse_posted_payment(reason or _('Non renseigné'))
            else:
                payment.state = 'cancelled'
        return True

    def _reverse_posted_payment(self, reason):
        self.ensure_one()
        # No separate group check needed here: ir.model.access.csv already restricts write
        # access on this model to the manager/finance groups (agents only have read access),
        # same convention as action_reschedule/action_confirm_write_off.
        move = self.move_id
        # Raises a clear UserError itself if the original entry's date falls within a locked
        # period (period_lock_date/fiscalyear_lock_date) — no reversal is attempted in that case.
        move._check_fiscalyear_lock_date()

        reversal_move = move._reverse_moves(default_values_list=[{
            'date': fields.Date.context_today(self),
            'ref': _('Contre-passation remboursement %s') % self.name,
        }], cancel=True)

        # Give back, per touched installment (most recently touched first - i.e. reverse
        # chronological order of due_date/sequence, mirroring how a multi-installment overflow
        # payment was originally allocated forward), the amounts this payment had allocated to
        # it. Chaque bucket (pénalité/intérêt/principal) est repris indépendamment via son propre
        # compteur `remaining_*` : l'ordre de ventilation interest -> principal -> pénalités
        # (Décision 2) n'a pas besoin d'être rejoué ici, seul l'ordre des échéances compte.
        remaining_penalty = self.allocated_penalty
        remaining_interest = self.allocated_interest
        remaining_principal = self.allocated_principal
        for inst in self.installment_ids.sorted(lambda i: (i.due_date, i.sequence), reverse=True):
            penalty_back = min(remaining_penalty, inst.paid_penalty)
            interest_back = min(remaining_interest, inst.paid_interest)
            principal_back = min(remaining_principal, inst.paid_principal)
            if penalty_back or interest_back or principal_back:
                inst.write({
                    'paid_penalty': inst.paid_penalty - penalty_back,
                    'paid_interest': inst.paid_interest - interest_back,
                    'paid_principal': inst.paid_principal - principal_back,
                })
            remaining_penalty -= penalty_back
            remaining_interest -= interest_back
            remaining_principal -= principal_back

        loan = self.loan_id
        reopened = loan.state == 'closed'
        if reopened:
            loan.state = 'active'

        self.write({'state': 'cancelled', 'reversal_move_id': reversal_move.id})
        loan.message_post(body=_(
            'Remboursement %(name)s annulé. Motif : %(reason)s. Écriture de contre-passation : %(move)s.%(reopened)s'
        ) % {
            'name': self.name,
            'reason': reason,
            'move': reversal_move.name,
            'reopened': _(' Le crédit repasse en actif.') if reopened else '',
        })
        return reversal_move
