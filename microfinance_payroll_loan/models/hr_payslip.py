# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

RSAL_JOURNAL_CODE = 'RSAL'
TRANSIT_ACCOUNT_CODE = '315000'

MICROFINANCE_LOAN_WARNING_REASON_LABELS = {
    'lien_manquant': _("lien employé-client manquant"),
    'flag_absent': _("retenue sur salaire non activée sur ce prêt"),
    'net_insuffisant': _("net insuffisant ce mois-ci pour retenir l'échéance due"),
}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    microfinance_loan_warning = fields.Text(
        string='Alerte prêt employé', compute='_compute_microfinance_loan_warning',
        help="Non vide si un prêt employé décaissé n'est pas (ou pas entièrement) retenu sur "
             "ce bulletin — lien manquant, retenue non activée sur le prêt, ou net "
             "insuffisant. Calculé via la même fonction de rapprochement partagée que le "
             "wizard Avance spéciale et la vue de contrôle (hr.employee."
             "microfinance_match_candidates), donc visible même SANS lien employé-client "
             "posé, tant qu'un homonyme de la même société porte un prêt décaissé. Vide pour "
             "un employé sans prêt — jamais d'avertissement dans ce cas.",
    )

    @api.depends('employee_id', 'company_id', 'date_to', 'line_ids.total')
    def _compute_microfinance_loan_warning(self):
        for payslip in self:
            payslip.microfinance_loan_warning = payslip._microfinance_build_loan_warning_text()

    def _microfinance_unretained_disbursed_loans(self):
        """Cœur de D : prêts décaissés de l'employé de ce bulletin (via son lien, OU — s'il
        n'a pas de lien — via les candidats de la fonction partagée, cf. hr_employee.py) qui
        ne sont pas (ou pas entièrement) retenus sur CE bulletin. Retourne une liste de
        couples (microfinance.loan, code_raison). Ne dépend PAS du lien employé-client :
        c'est tout l'enjeu de D (un homonyme qui porte un prêt décaissé doit alerter même
        sans lien posé)."""
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            return []
        Loan = self.env['microfinance.loan'].sudo()
        if employee.microfinance_partner_id:
            partners = employee.microfinance_partner_id
            no_link = False
        else:
            match = self.env['hr.employee'].microfinance_match_candidates(employee=employee)
            partners = match['candidates']
            no_link = True
        if not partners:
            return []
        disbursed = Loan.search([
            ('partner_id', 'in', partners.ids), ('company_id', '=', self.company_id.id),
            ('disbursement_date', '!=', False), ('state', 'in', ('active', 'defaulted')),
        ])
        results = []
        total_due_all = self._get_microfinance_loan_due_amount() if not no_link else 0.0
        loan_line = self.line_ids.filtered(lambda l: l.code == 'LOAN')
        total_retained = abs(loan_line.total) if loan_line else 0.0
        for loan in disbursed:
            if no_link:
                results.append((loan, 'lien_manquant'))
                continue
            if not loan.salary_deduction:
                results.append((loan, 'flag_absent'))
                continue
            due = self._microfinance_loan_due_amount(loan)
            if due <= 0.01:
                continue
            if total_retained + 0.01 < total_due_all:
                results.append((loan, 'net_insuffisant'))
        return results

    def _microfinance_build_loan_warning_text(self):
        self.ensure_one()
        pairs = self._microfinance_unretained_disbursed_loans()
        if not pairs:
            return False
        return '\n'.join(
            _("Prêt %(ref)s décaissé non retenu (%(reason)s).") % {
                'ref': loan.name,
                'reason': MICROFINANCE_LOAN_WARNING_REASON_LABELS.get(reason, reason),
            }
            for loan, reason in pairs
        )

    def _microfinance_salary_deduction_loans(self):
        """Prêts « Retenue sur salaire » éligibles sur ce bulletin : décaissés, actifs (ou en
        défaut), de la société du bulletin, rattachés au client lié à cet employé. sudo() :
        l'utilisateur qui calcule/valide un bulletin (groupe paie) n'a normalement pas accès
        à microfinance.loan — lecture seule, scopée à cette recherche."""
        self.ensure_one()
        partner = self.employee_id.microfinance_partner_id
        if not partner:
            return self.env['microfinance.loan']
        return self.env['microfinance.loan'].sudo().search([
            ('partner_id', '=', partner.id),
            ('company_id', '=', self.company_id.id),
            ('salary_deduction', '=', True),
            ('disbursement_date', '!=', False),
            ('state', 'in', ('active', 'defaulted')),
        ])

    def _microfinance_loan_due_amount(self, loan):
        """Somme des échéances impayées (résiduel > 0) dont la date d'échéance <= date_to de
        ce bulletin — une échéance non retenue ce mois-ci (pas de bulletin, ou net
        insuffisant) reste donc due et est naturellement reprise au bulletin suivant, sans
        logique de report dédiée."""
        self.ensure_one()
        installments = loan.sudo().installment_ids.filtered(
            lambda installment: installment.due_date and installment.due_date <= self.date_to
            and installment.residual_amount > 0.01
        )
        return sum(installments.mapped('residual_amount'))

    def _get_microfinance_loan_due_amount(self):
        """Point d'entrée appelé depuis le code python de la règle LOAN (via `payslip.dict`,
        cf. models/hr_salary_rule.py) : somme, tous prêts éligibles confondus, des échéances
        dues à la date de ce bulletin."""
        self.ensure_one()
        return sum(
            self._microfinance_loan_due_amount(loan)
            for loan in self._microfinance_salary_deduction_loans()
        )

    @api.model
    def _microfinance_get_or_create_rsal_journal(self, company):
        """Journal général « Retenues sur salaire » (RSAL), créé seulement s'il manque — jamais
        d'écrasement d'un journal existant. Son compte par défaut est le compte de transit 315
        « Créditeurs divers » de la société : la ligne LOAN du bulletin crédite ce même compte
        (cf. hr_salary_rule.py), donc le débit du remboursement microfinance posté sur ce
        journal annule exactement ce crédit — le transit revient à zéro."""
        Journal = self.env['account.journal'].sudo()
        journal = Journal.search([
            ('code', '=', RSAL_JOURNAL_CODE), ('company_id', '=', company.id),
        ], limit=1)
        if journal:
            return journal
        account = self.env['account.account'].sudo().search([
            ('code', '=', TRANSIT_ACCOUNT_CODE), ('company_id', '=', company.id),
        ], limit=1)
        if not account:
            raise UserError(_(
                "Compte %(code)s (Créditeurs divers) introuvable pour %(company)s : "
                "impossible de créer le journal « Retenues sur salaire »."
            ) % {'code': TRANSIT_ACCOUNT_CODE, 'company': company.display_name})
        return Journal.create({
            'name': 'Retenues sur salaire',
            'code': RSAL_JOURNAL_CODE,
            'type': 'general',
            'company_id': company.id,
            'default_account_id': account.id,
        })

    def _microfinance_run_payment_posting_sudo(self, loan, vals):
        """Exécute EN SUDO la création + comptabilisation d'UN remboursement de retenue sur
        salaire — l'unique chemin autorisé en dehors du Guichet Caisse (exception étroite aux
        verrous Correctifs A/B/C : ir.model.access.csv ne donne toujours ni create ni write sur
        microfinance.loan.payment au groupe paie). Même patron que
        microfinance_caisse_mouvement._run_posting_sudo : re-vérifie ICI, au plus près du
        bypass, que le prêt appartient bien à la société de CE bulletin, sur le prêt passé non
        sudo par l'appelant — seule la création/comptabilisation passe en sudo."""
        self.ensure_one()
        if loan.company_id != self.company_id:
            raise UserError(_(
                "Ce prêt n'appartient pas à la société de ce bulletin : retenue sur salaire "
                "refusée."
            ))
        Payment = self.env['microfinance.loan.payment'].sudo()
        payment = Payment.create(vals)
        payment.action_post()
        return payment

    def _microfinance_apply_salary_deduction(self):
        """Appelé après la validation comptable du bulletin (action_payslip_done) : crée le
        remboursement microfinance correspondant exactement au montant de la ligne LOAN déjà
        comptabilisée sur CE bulletin — jamais recalculé indépendamment, pour garantir que le
        compte de transit revient toujours à zéro même si plusieurs prêts se partagent le
        plafond. Idempotent par (payslip_id, loan_id) : ne double jamais sur une revalidation."""
        self.ensure_one()
        loan_line = self.line_ids.filtered(lambda line: line.code == 'LOAN')
        total_retained = abs(loan_line.total) if loan_line else 0.0
        if total_retained <= 0.01:
            return
        loans = self._microfinance_salary_deduction_loans().sorted('id')
        if not loans:
            return
        journal = self._microfinance_get_or_create_rsal_journal(self.company_id)
        Payment = self.env['microfinance.loan.payment'].sudo()
        remaining = total_retained
        for loan in loans:
            if remaining <= 0.01:
                break
            existing = Payment.search([
                ('payslip_id', '=', self.id), ('loan_id', '=', loan.id),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if existing:
                remaining -= existing.amount
                continue
            due = self._microfinance_loan_due_amount(loan)
            amount = min(remaining, due)
            if amount <= 0.01:
                continue
            self._microfinance_run_payment_posting_sudo(loan, {
                'loan_id': loan.id,
                'amount': amount,
                'journal_id': journal.id,
                'payment_date': self.date_to,
                'payslip_id': self.id,
            })
            remaining -= amount

    def _microfinance_reverse_salary_deduction(self):
        """Extourne le(s) remboursement(s) de retenue sur salaire liés à ce bulletin, si le
        mécanisme de contre-passation de microfinance.loan.payment le permet (cas normal).
        S'il le refuse (ex. période comptable verrouillée), l'exception remonte telle quelle et
        bloque l'annulation/remise en brouillon du bulletin — même mécanisme dans les deux cas,
        pas de branche séparée."""
        self.ensure_one()
        payments = self.env['microfinance.loan.payment'].sudo().search([
            ('payslip_id', '=', self.id), ('state', '=', 'posted'),
        ])
        for payment in payments:
            payment.action_cancel(reason=_(
                "Annulation ou remise en brouillon du bulletin %s."
            ) % self.name)

    def action_payslip_done(self):
        result = super().action_payslip_done()
        for payslip in self:
            payslip._microfinance_apply_salary_deduction()
            if payslip.microfinance_loan_warning:
                payslip.message_post(body=_(
                    "Avertissement retenue prêt employé :<br/>%s"
                ) % payslip.microfinance_loan_warning.replace('\n', '<br/>'))
        return result

    def action_payslip_cancel(self):
        for payslip in self:
            payslip._microfinance_reverse_salary_deduction()
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        for payslip in self:
            payslip._microfinance_reverse_salary_deduction()
        return super().action_payslip_draft()
