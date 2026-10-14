# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

# (code de règle, organisme, nature, paramètre du taux)
CONTRIBUTION_LINES = (
    ('CNAPS', 'cnaps', 'salarie', 'CNAPS_SAL'),
    ('OSTIE', 'ostie', 'salarie', 'OSTIE_SAL'),
    ('IRSA', 'irsa', 'impot', None),
    ('CNAPS_ER', 'cnaps', 'patronal', 'CNAPS_ER'),
    ('OSTIE_ER', 'ostie', 'patronal', 'OSTIE_ER'),
)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    mowgli_csoc_move_id = fields.Many2one(
        'account.move', string="Écriture Charges sociales", copy=False,
        readonly=True)
    mowgli_contribution_ids = fields.One2many(
        'mowgli.payroll.contribution', 'payslip_id', string="Cotisations",
        copy=False)

    # ------------------------------------------------------------------
    # Hooks : validation = super() puis CSOC (même transaction) ;
    # annulation / brouillon = extourne CSOC AVANT le super().
    # ------------------------------------------------------------------
    def action_payslip_done(self):
        result = super().action_payslip_done()
        for payslip in self:
            payslip._mowgli_register_contributions()
            payslip._mowgli_post_csoc()
        return result

    def action_payslip_cancel(self):
        self._mowgli_reverse_csoc()
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        self._mowgli_reverse_csoc()
        return super().action_payslip_draft()

    # ------------------------------------------------------------------
    def _mowgli_register_contributions(self):
        """Cinq lignes de registre : CNAPS, OSTIE, IRSA (lignes du bulletin)
        + CNAPS_ER, OSTIE_ER. Chaque montant est arrondi UNE fois à la devise ;
        ce même montant sert au registre et à l'écriture CSOC. Note de crédit :
        montants opposés. Idempotent."""
        self.ensure_one()
        if self.mowgli_contribution_ids:
            return
        sign = -1.0 if self.credit_note else 1.0
        currency = self.company_id.currency_id
        lines = {line.code: line for line in self.line_ids}
        gross = lines['GROSS'].total if 'GROSS' in lines else 0.0
        contribution_base = self._mowgli_contribution_base(gross)
        vals_list = []
        for code, organisme, nature, param in CONTRIBUTION_LINES:
            line = lines.get(code)
            if not line:
                continue
            amount = currency.round(abs(line.total))
            if param:
                base = currency.round(contribution_base)
                rate = self._mowgli_param(param)
            else:
                netimp = lines.get('NETIMP')
                base = currency.round(netimp.total) if netimp else 0.0
                rate = amount / base if base else 0.0
            vals_list.append({
                'payslip_id': self.id, 'employee_id': self.employee_id.id,
                'company_id': self.company_id.id, 'date': self.date_to,
                'organisme': organisme, 'nature': nature, 'rule_code': code,
                'base': base, 'taux': rate, 'montant': sign * amount,
            })
        self.env['mowgli.payroll.contribution'].sudo().create(vals_list)

    def _mowgli_csoc_accounts(self):
        """(compte de charge, compte 315000) résolus par code dans la société
        du bulletin ; UserError explicite si l'un manque."""
        self.ensure_one()
        Contribution = self.env['mowgli.payroll.contribution']
        Account = self.env['account.account'].sudo()
        accounts = []
        for code in (Contribution._charge_account_code(), '315000'):
            account = Account.search([
                ('code', '=', code), ('company_id', '=', self.company_id.id)],
                limit=1)
            if not account:
                raise UserError(_(
                    "Compte %(code)s introuvable pour la société %(company)s : "
                    "impossible de passer l'écriture des charges sociales du "
                    "bulletin %(slip)s.") % {
                        'code': code, 'company': self.company_id.name,
                        'slip': self.name})
            accounts.append(account)
        return accounts

    def _mowgli_post_csoc(self):
        """Écriture du journal CSOC pour la part patronale : débit compte de
        charge, crédit 315000 (inversé pour une note de crédit). Aucune ligne
        omise ni ajustement silencieux."""
        self.ensure_one()
        if self.mowgli_csoc_move_id:
            return
        rows = self.mowgli_contribution_ids.filtered(
            lambda r: r.nature == 'patronal' and r.montant)
        if not rows:
            return
        charge, credit = self._mowgli_csoc_accounts()
        journal = self.env['mowgli.payroll.contribution']._get_or_create_journal(
            self.company_id)
        label = _("Charges patronales %s") % (self.number or self.name)
        move_lines = []
        for row in rows:
            amount = abs(row.montant)
            debit_account, credit_account = (
                (charge, credit) if row.montant > 0 else (credit, charge))
            row_label = '%s - %s' % (label, row.organisme.upper())
            move_lines.append((0, 0, {
                'account_id': debit_account.id, 'name': row_label,
                'debit': amount, 'credit': 0.0}))
            move_lines.append((0, 0, {
                'account_id': credit_account.id, 'name': row_label,
                'debit': 0.0, 'credit': amount}))
        move = self.env['account.move'].sudo().with_company(self.company_id).create({
            'journal_id': journal.id,
            'company_id': self.company_id.id,
            'date': self.date_to,
            'ref': label,
            'line_ids': move_lines,
        })
        move._post()
        self.mowgli_csoc_move_id = move
        rows.sudo().write({'move_id': move.id})

    def _mowgli_reverse_csoc(self):
        """Extourne l'écriture CSOC et retire les lignes du registre. Bloque
        si la période est verrouillée ou si une cotisation est déjà déclarée
        ou versée."""
        for payslip in self:
            contributions = payslip.mowgli_contribution_ids
            move = payslip.mowgli_csoc_move_id
            if not contributions and not move:
                continue
            if contributions.filtered(lambda r: r.state != 'a_verser'):
                raise UserError(_(
                    "Le bulletin %s a des cotisations déjà déclarées ou "
                    "versées : annulation ou remise en brouillon refusée.")
                    % payslip.name)
            if move:
                reversal_date = fields.Date.context_today(payslip)
                lock_date = payslip.company_id._get_user_fiscal_lock_date()
                if lock_date and reversal_date <= lock_date:
                    raise UserError(_(
                        "La période de l'écriture Charges sociales du "
                        "bulletin %(slip)s est verrouillée (jusqu'au "
                        "%(lock)s) : extourne impossible.") % {
                            'slip': payslip.name, 'lock': lock_date})
                move = move.sudo()
                if move.state == 'posted':
                    move._reverse_moves([{
                        'date': reversal_date,
                        'ref': _("Extourne %s") % (move.ref or move.name)}],
                        cancel=True)
                elif move.state == 'draft':
                    move.button_cancel()
            payslip.mowgli_csoc_move_id = False
            contributions.sudo().unlink()
