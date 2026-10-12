# -*- coding: utf-8 -*-
"""Paiement du NET des bulletins de paie, en transit sur le compte d'exploitation.

« Marquer Payé » (bulletin ou lot) ne change plus seulement l'état : il prépare un paiement de salaire (un bulletin =
un lot d'un seul bulletin) qui, une fois validé, passe UNE écriture dans le journal d'exploitation de la banque :

    Dr « Personnel, rémunérations dues » (net de chaque bulletin, lettré avec la ligne du bulletin)
    Cr 139500 (paiement sortant en suspens du journal, pour le total)

139500 reste en transit : seule la ligne de sortie du relevé bancaire papier la solde (Dr 139500 / Cr banque), par le
rapprochement existant (une ligne de relevé = UNE ligne en attente). Pour une banque qui débite chaque virement
séparément, « Une ligne de relevé par employé » crédite 139500 employé par employé.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .mf_trace import mf_amount, mf_safe

GROUP_PAYROLL_MANAGER = 'hr_payroll_community.group_hr_payroll_community_manager'
STATUS = [('unpaid', 'Non payé'), ('transit', 'En transit'), ('confirmed', 'Confirmé en banque')]


def _check_pay_rights(env):
    """Les mêmes droits que l'ancien bouton « Marquer Payé » (responsable paie)."""
    if not env.su and not env.user.has_group(GROUP_PAYROLL_MANAGER):
        raise AccessError(_("Le paiement des salaires est réservé au responsable de la paie."))


class HrPayslipPayment(models.Model):
    _name = 'hr.payslip.payment'
    _inherit = ['mail.thread']
    _description = 'Paiement de salaires (en transit)'
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', string='Société', required=True, readonly=True,
                                 default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Brouillon'), ('posted', 'En transit'), ('cancelled', 'Annulé')],
                             string='État', default='draft', readonly=True, copy=False, tracking=True)
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Lot de bulletins', readonly=True, copy=False,
                                     index=True)
    journal_id = fields.Many2one(
        'account.journal', string="Journal d'exploitation", required=True, check_company=True,
        domain="[('company_id', '=', company_id), ('microfinance_usage', '=', 'operating'), ('type', '=', 'bank')]",
        help="Journal d'exploitation de la banque qui paie. Par défaut celui du réglage de la société ; modifiable "
             "tant que le paiement n'est pas validé, entre les journaux d'exploitation de la société.")
    bank_id = fields.Many2one(related='journal_id.microfinance_bank_id', string='Banque')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    split_bank_lines = fields.Boolean(
        string='Une ligne de relevé par employé',
        help="Cochez si la banque débite chaque virement séparément : 139500 est alors crédité employé par employé, "
             "chacun se rapproche de sa propre ligne de relevé. Sinon, une seule ligne pour le total.")
    line_ids = fields.One2many('hr.payslip.payment.line', 'payment_id', string='Bulletins payés')
    amount_total = fields.Monetary(string='Total', compute='_compute_amount_total', store=True,
                                   currency_field='currency_id')
    move_id = fields.Many2one('account.move', string='Écriture de paiement', readonly=True, copy=False,
                              check_company=False)
    reversal_move_id = fields.Many2one('account.move', string="Écriture d'extourne", readonly=True, copy=False,
                                       check_company=False)
    warning_message = fields.Char(string='Avertissement', compute='_compute_warning_message')

    # ------------------------------------------------------------------ calculs
    @api.depends('line_ids.amount')
    def _compute_amount_total(self):
        for payment in self:
            payment.amount_total = sum(payment.line_ids.mapped('amount'))

    @api.depends('journal_id', 'amount_total', 'state')
    def _compute_warning_message(self):
        """Avertissement NON bloquant : montant supérieur au solde disponible du journal d'exploitation (solde en
        banque moins les paiements sortants en transit non rapprochés)."""
        for payment in self:
            payment.warning_message = False
            if payment.state != 'draft' or not payment.journal_id:
                continue
            available = payment.journal_id._mf_treasury_amounts()[payment.journal_id.id]['available']
            if payment.currency_id.compare_amounts(payment.amount_total, available) > 0:
                payment.warning_message = _(
                    "Attention : ce paiement (%(montant)s) dépasse le solde disponible du journal « %(journal)s » "
                    "(%(dispo)s : solde en banque moins paiements en transit). Vous pouvez le valider quand même."
                ) % {'montant': mf_amount(payment.amount_total), 'journal': payment.journal_id.display_name,
                     'dispo': mf_amount(available)}

    # ------------------------------------------------------------------ création
    @api.model
    def _default_operating_journal(self, company):
        journal = company.microfinance_operating_journal_id
        if journal and journal.microfinance_usage == 'operating':
            return journal
        return self.env['account.journal'].search([
            ('company_id', '=', company.id), ('microfinance_usage', '=', 'operating'), ('type', '=', 'bank'),
        ], limit=1)

    @api.model
    def _create_from_payslips(self, payslips, run=None):
        """Brouillon de paiement pour `payslips` (bulletins « Validé » d'une seule société). Contrôle chaque bulletin
        avant de créer quoi que ce soit : un seul refus annule tout le paiement."""
        _check_pay_rights(self.env)
        if not payslips:
            raise UserError(_("Aucun bulletin validé à payer."))
        company = payslips.company_id
        if len(company) != 1:
            raise UserError(_("Un paiement ne peut regrouper que des bulletins d'une même société."))
        journal = self._default_operating_journal(company)
        if not journal:
            raise UserError(_(
                "Aucun journal bancaire d'exploitation n'est défini pour la société « %s » : renseignez-le dans les "
                "réglages de la société.") % company.name)
        lines = []
        for slip in payslips:
            slip._mf_check_payable()
            lines.append((0, 0, {'payslip_id': slip.id, 'amount': slip._mf_net_amount()}))
        return self.with_company(company).create({
            'company_id': company.id, 'journal_id': journal.id, 'line_ids': lines,
            'payslip_run_id': run.id if run else False,
        })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.payslip.payment') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(payment.state != 'draft' for payment in self):
            raise UserError(_("Seul un paiement en brouillon peut être supprimé : annulez les autres (extourne)."))
        return super().unlink()

    def _get_form_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.name, 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current',
        }

    # ------------------------------------------------------------------ validation
    def _payment_account(self):
        self.ensure_one()
        account = self.env['microfinance.fond.partage']._payment_account(self.journal_id, 'outbound')
        if not account:
            raise UserError(_("Le journal « %s » n'a pas de compte de paiement en suspens sortant (139500).")
                            % self.journal_id.display_name)
        return account

    def _check_ready(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Ce paiement est déjà validé ou annulé."))
        if not self.line_ids:
            raise UserError(_("Ce paiement ne contient aucun bulletin."))
        journal = self.journal_id
        if journal.company_id != self.company_id or journal.microfinance_usage != 'operating' \
                or journal.type != 'bank':
            raise UserError(_("Le journal « %s » n'est pas un journal bancaire d'exploitation de la société « %s ».")
                            % (journal.display_name, self.company_id.name))
        for line in self.line_ids:
            line.payslip_id._mf_check_payable(exclude=self)
            line._check_amount()

    def _move_vals(self):
        self.ensure_one()
        label = _('Salaires %s') % (self.payslip_run_id.name or self.line_ids[:1].payslip_id.number
                                    or self.line_ids[:1].payslip_id.name or self.name)
        payment_account = self._payment_account()
        move_lines = []
        for line in self.line_ids:
            slip = line.payslip_id
            move_lines.append((0, 0, {
                'name': _('Salaire %(emp)s - %(slip)s') % {
                    'emp': slip.employee_id.name, 'slip': slip.number or slip.name},
                'account_id': slip._mf_net_line().account_id.id,
                'debit': line.amount, 'credit': 0.0,
            }))
        credits = [(label, self.amount_total)]
        if self.split_bank_lines:
            credits = [(_('Salaire %s') % line.payslip_id.employee_id.name, line.amount) for line in self.line_ids]
        for name, amount in credits:
            move_lines.append((0, 0, {
                'name': name, 'account_id': payment_account.id, 'debit': 0.0, 'credit': amount}))
        return {
            'move_type': 'entry', 'date': self.date, 'journal_id': self.journal_id.id,
            'ref': '%s - %s' % (self.name, label), 'mf_salary_payment_id': self.id, 'line_ids': move_lines,
        }

    def action_validate(self):
        """Passe l'écriture en transit, lettre les lignes « rémunérations dues » et met les bulletins à « Paid »."""
        _check_pay_rights(self.env)
        for payment in self:
            payment._check_ready()
            company = payment.company_id
            Move = self.env['account.move'].sudo().with_company(company).with_context(allowed_company_ids=[company.id])
            move = Move.create(payment._move_vals())
            move.action_post()
            debits = move.line_ids.sorted('id').filtered(lambda l: l.debit > 0)
            credits = move.line_ids.sorted('id').filtered(lambda l: l.credit > 0)
            for index, line in enumerate(payment.line_ids):
                debit_line = debits[index]
                bank_line = credits[index] if payment.split_bank_lines else credits[0]
                line.sudo().write({'debit_line_id': debit_line.id, 'bank_line_id': bank_line.id})
                (line.payslip_id._mf_net_line() | debit_line).reconcile()
            payment.sudo().write({'move_id': move.id, 'state': 'posted'})
            payment.line_ids.payslip_id.sudo().write({'state': 'paid', 'paid': True})
            payment._mf_trace_posted()
        return True

    # ------------------------------------------------------------------ annulation
    def _bank_matched_amount(self, bank_line):
        """Part de la ligne 139500 soldée par une ligne de relevé bancaire (un lettrage avec une extourne n'en est
        jamais une)."""
        return sum(partial.amount for partial in bank_line.sudo().matched_debit_ids
                   if partial.debit_move_id.move_id.statement_line_id)

    def action_cancel(self):
        """Annule un paiement en transit par extourne, tant que 139500 n'est pas rapproché par un relevé. Les
        bulletins reviennent à « Validé » et leur ligne « rémunérations dues » est délettrée."""
        _check_pay_rights(self.env)
        for payment in self:
            if payment.state == 'draft':
                payment.write({'state': 'cancelled'})
                continue
            if payment.state != 'posted':
                raise UserError(_("Ce paiement est déjà annulé."))
            bank_lines = payment.line_ids.bank_line_id
            if any(payment._bank_matched_amount(line) for line in bank_lines):
                raise UserError(_(
                    "Annulation impossible : la ligne en transit (139500) du paiement %s est déjà rapprochée par un "
                    "relevé bancaire. Annulez d'abord le rapprochement du relevé.") % payment.name)
            move = payment.move_id.sudo()
            company = payment.company_id
            move.line_ids.filtered('debit').remove_move_reconcile()
            reversal = move.with_company(company).with_context(allowed_company_ids=[company.id])._reverse_moves(
                [{'date': fields.Date.context_today(payment), 'ref': _('Extourne %s') % (move.ref or move.name),
                  'mf_salary_payment_id': payment.id}], cancel=True)
            payment.sudo().write({'state': 'cancelled', 'reversal_move_id': reversal.id})
            payment.line_ids.payslip_id.sudo().write({'state': 'done', 'paid': False})
            payment._mf_trace_cancelled(reversal)
        return True

    # ------------------------------------------------------------------ traces (chatter)
    @mf_safe
    def _mf_trace_posted(self):
        Trace = self.env['mf.trace']
        for payment in self:
            move = payment.move_id
            details = [
                (_('Montant'), mf_amount(payment.amount_total)), (_('Banque'), payment.bank_id.name),
                (_('Journal'), payment.journal_id.display_name), (_('Pièce créée'), move.name),
            ]
            ref = payment.payslip_run_id.name
            Trace.mf_trace(payment, _('Paiement de salaires validé (en transit)'),
                           details + [(_('Bulletins'), [l.payslip_id.display_name for l in payment.line_ids])],
                           [move])
            if payment.payslip_run_id:
                Trace.mf_trace(payment.payslip_run_id, _('Paiement de salaires en transit'),
                               details + [(_('Lot'), ref)], [payment, move])
            for line in payment.line_ids:
                Trace.mf_trace(line.payslip_id, _('Net payé en transit'),
                               [(_('Montant'), mf_amount(line.amount)), (_('Banque'), payment.bank_id.name),
                                (_('Journal'), payment.journal_id.display_name),
                                (_('Référence'), line.payslip_id.number or line.payslip_id.name),
                                (_('Pièce créée'), move.name)], [payment, move])

    @mf_safe
    def _mf_trace_cancelled(self, reversal):
        Trace = self.env['mf.trace']
        for payment in self:
            details = [(_('Montant'), mf_amount(payment.amount_total)), (_('Banque'), payment.bank_id.name),
                       (_('Journal'), payment.journal_id.display_name), (_("Pièce d'extourne"), reversal.name)]
            Trace.mf_trace(payment, _('Paiement de salaires annulé (extourne)'), details, [reversal])
            if payment.payslip_run_id:
                Trace.mf_trace(payment.payslip_run_id, _('Paiement de salaires annulé (extourne)'), details,
                               [payment, reversal])
            for line in payment.line_ids:
                Trace.mf_trace(line.payslip_id, _('Paiement du net annulé (extourne)'),
                               [(_('Montant'), mf_amount(line.amount)), (_('Banque'), payment.bank_id.name),
                                (_('Journal'), payment.journal_id.display_name),
                                (_('Référence'), line.payslip_id.number or line.payslip_id.name),
                                (_("Pièce d'extourne"), reversal.name)], [payment, reversal])


class HrPayslipPaymentLine(models.Model):
    _name = 'hr.payslip.payment.line'
    _description = 'Ligne de paiement de salaire (un bulletin)'
    _order = 'payment_id, id'

    payment_id = fields.Many2one('hr.payslip.payment', string='Paiement', required=True, ondelete='cascade',
                                 index=True)
    company_id = fields.Many2one(related='payment_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='payment_id.currency_id')
    payment_state = fields.Selection(related='payment_id.state', store=True, string='État du paiement')
    payslip_id = fields.Many2one('hr.payslip', string='Bulletin', required=True, ondelete='restrict', index=True)
    employee_id = fields.Many2one(related='payslip_id.employee_id', string='Employé')
    amount = fields.Monetary(string='Net payé', required=True, currency_field='currency_id')
    debit_line_id = fields.Many2one('account.move.line', string='Ligne « rémunérations dues »', readonly=True,
                                    copy=False, check_company=False)
    bank_line_id = fields.Many2one('account.move.line', string='Ligne en transit (139500)', readonly=True,
                                   copy=False, check_company=False)

    def _check_amount(self):
        for line in self:
            currency = line.currency_id
            slip = line.payslip_id
            if currency.compare_amounts(line.amount, 0.0) <= 0:
                raise ValidationError(_("Le net du bulletin %s est nul ou négatif : il n'y a rien à payer.")
                                      % slip.display_name)
            if currency.compare_amounts(line.amount, slip._mf_net_amount()) > 0:
                raise ValidationError(_("Le paiement du bulletin %(slip)s (%(montant)s) dépasse son net dû (%(net)s).")
                                      % {'slip': slip.display_name, 'montant': mf_amount(line.amount),
                                         'net': mf_amount(slip._mf_net_amount())})

    @api.constrains('amount', 'payslip_id')
    def _check_line(self):
        for line in self:
            line._check_amount()
            if line.payslip_id.company_id != line.payment_id.company_id:
                raise ValidationError(_("Le bulletin %s n'appartient pas à la société du paiement.")
                                      % line.payslip_id.display_name)

    @api.constrains('payslip_id', 'payment_state')
    def _check_single_active_payment(self):
        for line in self.filtered(lambda l: l.payment_state != 'cancelled'):
            if self.search_count([('payslip_id', '=', line.payslip_id.id), ('id', '!=', line.id),
                                  ('payment_state', '!=', 'cancelled')]):
                raise ValidationError(_("Le bulletin %s a déjà un paiement actif : il ne peut pas être payé deux fois.")
                                      % line.payslip_id.display_name)


class AccountMove(models.Model):
    _inherit = 'account.move'

    mf_salary_payment_id = fields.Many2one('hr.payslip.payment', string='Paiement de salaires', index='btree_not_null',
                                           copy=False, check_company=False)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    payment_line_ids = fields.One2many('hr.payslip.payment.line', 'payslip_id', string='Paiements du net')
    mf_payment_id = fields.Many2one('hr.payslip.payment', string='Paiement du net', compute='_compute_mf_bank_status')
    mf_bank_status = fields.Selection(STATUS, string='Statut bancaire', compute='_compute_mf_bank_status',
                                      help="Non payé : aucun paiement actif. En transit : écriture créée, ligne 139500 "
                                           "non rapprochée. Confirmé en banque : ligne 139500 lettrée avec une ligne "
                                           "de relevé. L'état « Paid » garde sa signification (paiement émis).")

    @api.depends('payment_line_ids.payment_state', 'payment_line_ids.bank_line_id.matched_debit_ids',
                 'payment_line_ids.bank_line_id.reconciled')
    def _compute_mf_bank_status(self):
        for slip in self:
            line = slip.sudo().payment_line_ids.filtered(lambda l: l.payment_state == 'posted')[:1]
            slip.mf_payment_id = line.payment_id
            status = 'unpaid'
            if line:
                bank_line = line.bank_line_id
                matched = line.payment_id._bank_matched_amount(bank_line) if bank_line else 0.0
                done = bank_line and line.currency_id.compare_amounts(matched, bank_line.credit) >= 0
                status = 'confirmed' if done else 'transit'
            slip.mf_bank_status = status

    # ------------------------------------------------------------------ net à payer
    def _mf_net_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.category_id.code == 'NET')

    def _mf_net_amount(self):
        """Net du bulletin, arrondi à la précision de la devise de la société (jamais de décimale parasite)."""
        self.ensure_one()
        return self.company_id.currency_id.round(sum(self._mf_net_lines().mapped('total')))

    def _mf_net_line(self):
        """Ligne créditrice « Personnel, rémunérations dues » de l'écriture du bulletin (celle du compte de crédit de
        la règle NET)."""
        self.ensure_one()
        company = self.company_id
        accounts = self._mf_net_lines().mapped('salary_rule_id').with_company(company).mapped('credit_account_id')
        return self.sudo().move_id.line_ids.filtered(lambda l: l.account_id in accounts and l.credit > 0)

    def _mf_check_payable(self, exclude=None):
        """Refus clairs (en français) avant tout paiement du net."""
        self.ensure_one()
        name = self.display_name
        if self.state != 'done':
            raise UserError(_("Seul un bulletin 'Validé' peut être payé (bulletin %s).") % name)
        active = self.sudo().payment_line_ids.filtered(
            lambda l: l.payment_state != 'cancelled' and l.payment_id != exclude)
        if active:
            raise UserError(_("Le bulletin %(slip)s a déjà un paiement actif (%(pay)s) : il ne peut pas être payé deux "
                              "fois.") % {'slip': name, 'pay': active[0].payment_id.name})
        if self.company_id.currency_id.compare_amounts(self._mf_net_amount(), 0.0) <= 0:
            raise UserError(_("Le net du bulletin %s est nul ou négatif : il n'y a rien à payer.") % name)
        move = self.sudo().move_id
        if not move or move.state != 'posted':
            raise UserError(_("Le bulletin %s n'a pas d'écriture comptabilisée : validez-le avec les écritures de paie "
                              "activées avant de le payer.") % name)
        net_line = self._mf_net_line()
        if len(net_line) != 1 or net_line.reconciled:
            raise UserError(_("Le bulletin %s n'a pas de ligne « Personnel, rémunérations dues » à régler (net "
                              "absent de l'écriture ou déjà lettré).") % name)
        if self.company_id.currency_id.compare_amounts(self._mf_net_amount(), abs(net_line.amount_residual)) > 0:
            raise UserError(_("Le net du bulletin %s dépasse le reste dû en comptabilité.") % name)

    # ------------------------------------------------------------------ actions
    def action_payslip_paid(self):
        """« Marquer Payé » : prépare le paiement du NET en transit (un bulletin = un lot d'un bulletin) et ouvre
        sa fiche (journal modifiable, avertissement de solde) ; l'état passe à « Paid » à sa validation."""
        _check_pay_rights(self.env)
        if any(slip.state != 'done' for slip in self):
            raise UserError(_("Seul un bulletin 'Validé' peut être marqué comme payé."))
        draft = self.sudo().payment_line_ids.filtered(lambda l: l.payment_state == 'draft').payment_id
        payment = draft if len(draft) == 1 and draft.line_ids.payslip_id == self else \
            self.env['hr.payslip.payment']._create_from_payslips(self)
        return payment._get_form_action()

    def action_open_payment(self):
        self.ensure_one()
        return self.sudo().payment_line_ids.sorted('id')[-1:].payment_id._get_form_action()

    def action_cancel_payment(self):
        self.ensure_one()
        _check_pay_rights(self.env)
        payment = self.sudo().mf_payment_id
        if not payment:
            raise UserError(_("Ce bulletin n'a pas de paiement en transit à annuler."))
        return payment.action_cancel()


class HrPayslipRun(models.Model):
    _name = 'hr.payslip.run'
    _inherit = ['hr.payslip.run', 'mail.thread']

    payment_ids = fields.One2many('hr.payslip.payment', 'payslip_run_id', string='Paiements de salaires')

    def action_payslip_paid(self):
        """« Marquer Payé » du lot : UNE écriture groupée pour le total, une ligne de détail par employé."""
        self.ensure_one()
        _check_pay_rights(self.env)
        slips = self.slip_ids.filtered(lambda s: s.state == 'done')
        if not slips:
            raise UserError(_("Ce lot ne contient aucun bulletin validé à payer."))
        payment = self.env['hr.payslip.payment']._create_from_payslips(slips, run=self)
        return payment._get_form_action()

    def action_open_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Paiements de salaires'), 'res_model': 'hr.payslip.payment',
            'view_mode': 'tree,form', 'domain': [('payslip_run_id', '=', self.id)],
        }
