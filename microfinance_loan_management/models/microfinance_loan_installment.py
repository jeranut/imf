# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanInstallment(models.Model):
    _name = 'microfinance.loan.installment'
    _description = 'Échéance de crédit microfinance'
    _order = 'loan_id, sequence, due_date'

    loan_id = fields.Many2one('microfinance.loan', string='Crédit', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Séquence', required=True, default=1)
    due_date = fields.Date(string="Date d'échéance", required=True, index=True)
    principal_amount = fields.Monetary(string='Montant principal', default=0.0)
    interest_amount = fields.Monetary(string='Montant intérêt', default=0.0)
    penalty_amount = fields.Monetary(string='Montant pénalité', default=0.0)
    total_amount = fields.Monetary(string='Montant total', compute='_compute_amounts', store=True)
    paid_principal = fields.Monetary(string='Principal payé', default=0.0)
    paid_interest = fields.Monetary(string='Intérêt payé', default=0.0)
    paid_penalty = fields.Monetary(string='Pénalité payée', default=0.0)
    residual_amount = fields.Monetary(string='Montant résiduel', compute='_compute_amounts', store=True)
    state = fields.Selection([
        ('pending', 'À payer'),
        ('partial', 'Partiel'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
    ], string='État', compute='_compute_state', store=True, readonly=False, default='pending')
    penalty_applied = fields.Boolean(string='Pénalité appliquée', default=False)
    arrears_onset_date = fields.Date(
        string='Date de premier impayé', readonly=True, copy=False, index=True,
        help="Date à laquelle cette échéance est passée en retard pour la première fois "
             '(egale à due_date, posée une seule fois). Alimente le graphique "Évolution des '
             'impayés" du tableau de bord.',
    )
    arrears_cured_date = fields.Date(
        string='Date de régularisation', readonly=True, copy=False,
        help="Date à laquelle cette échéance, précédemment en retard, a été soldée. Vide tant "
             "que l'échéance reste en retard ; effacée si un remboursement qui la soldait est "
             'annulé.',
    )
    payment_ids = fields.Many2many('microfinance.loan.payment', 'microfinance_installment_payment_rel', 'installment_id', 'payment_id', string='Paiements')
    partner_id = fields.Many2one(related='loan_id.partner_id', store=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', store=True, readonly=True)
    # Stocké pour les agrégats read_group par agent du dashboard portefeuille (Lot 1).
    officer_id = fields.Many2one(related='loan_id.officer_id', store=True, readonly=True, index=True, string='Agent crédit')

    @api.depends('principal_amount', 'interest_amount', 'penalty_amount', 'paid_principal', 'paid_interest', 'paid_penalty')
    def _compute_amounts(self):
        for line in self:
            line.total_amount = line.principal_amount + line.interest_amount + line.penalty_amount
            paid = line.paid_principal + line.paid_interest + line.paid_penalty
            line.residual_amount = max(line.total_amount - paid, 0.0)

    @api.depends('residual_amount', 'total_amount', 'due_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.total_amount and line.residual_amount <= 0.01:
                line.state = 'paid'
            elif line.residual_amount < line.total_amount:
                line.state = 'partial'
            elif line.due_date and line.due_date < today:
                line.state = 'overdue'
            else:
                line.state = 'pending'

    def _sync_arrears_state(self):
        """Rafraîchit `state` (dont le passage à 'overdue' au fil des jours n'est pas déclenché
        automatiquement : aucun @api.depends ne référence "aujourd'hui") puis journalise les
        transitions de retard sur arrears_onset_date/arrears_cured_date, sans recréer de logique
        de détection différente de celle déjà utilisée par _compute_state. Appelé quotidiennement
        par microfinance.loan.cron_update_overdue_and_penalties."""
        self._compute_state()
        today = fields.Date.context_today(self)
        for inst in self:
            if inst.state == 'overdue' and not inst.arrears_onset_date:
                inst.arrears_onset_date = inst.due_date
                inst.arrears_cured_date = False
            elif inst.state == 'paid' and inst.arrears_onset_date and not inst.arrears_cured_date:
                inst.arrears_cured_date = today
            elif inst.state in ('pending', 'partial', 'overdue') and inst.arrears_cured_date:
                inst.arrears_cured_date = False

    @api.model
    def get_due_today(self, company_id):
        """Échéances non soldées dont la date d'échéance est aujourd'hui, pour le panneau
        "Échéances du jour" du tableau de bord. Bornée par l'index existant sur due_date (pas de
        scan de microfinance.loan), extraite en méthode de modèle pour rester testable
        directement, comme microfinance.loan.get_par_buckets."""
        today = fields.Date.context_today(self)
        return self.search([
            ('company_id', '=', company_id),
            ('due_date', '=', today),
            ('state', '!=', 'paid'),
        ], order='due_date, loan_id')

    @api.model
    def get_pending_or_late(self, company_id):
        """Échéances attendues aujourd'hui OU en retard, pour l'onglet « Échéances du jour »
        du guichet (Lot 1.2). Périmètre acté avec Micka :
        due_date <= aujourd'hui AND state != 'paid' AND loan_id.state in ('active','defaulted').

        - `state != 'paid'` : inclut donc les échéances 'partial' en retard (partiellement
          soldées mais échues), voulu.
        - `loan_id.state in ('active','defaulted')` : OBLIGATOIRE — exclut les échéances
          d'un crédit non décaissé dont un échéancier a été généré en phase d'aperçu (cf.
          docs_dev/guichet_caisse/AUDIT.md §3.3 et docs_dev/dashboard_portefeuille_agent/
          AUDIT.md anomalie A1). Ne pas l'omettre.
        - `loan_id.disbursement_date != False` : depuis le découplage activation / décaissement
          (docs_dev/guichet_caisse/AUDIT_decaissement.md §2), l'état 'active' ne prouve plus
          que les fonds sont sortis — un crédit activé mais pas encore décaissé a un échéancier
          (recalé au décaissement) mais ne doit pas remonter comme échéance à encaisser.

        Méthode dédiée (get_due_today reste inchangée, consommée par le dashboard avec un
        périmètre plus restrictif : due_date == aujourd'hui seulement)."""
        today = fields.Date.context_today(self)
        installments = self.search([
            ('company_id', '=', company_id),
            ('due_date', '<=', today),
            ('state', '!=', 'paid'),
            ('loan_id.state', 'in', ('active', 'defaulted')),
            ('loan_id.disbursement_date', '!=', False),
        ], order='due_date asc, loan_id asc')
        return [{
            'id': inst.id,
            'partner_id': inst.partner_id.id,
            'partner_name': inst.partner_id.name,
            'dossier': inst.loan_id.name,
            'due_date': inst.due_date,
            'amount': inst.residual_amount,
            'state': inst.state,
            'is_late': inst.due_date < today,
            'company_name': inst.company_id.name,
        } for inst in installments]

    @api.model
    def get_loan_schedule(self, loan_id, company_id):
        """Échéancier complet d'un crédit, pour le panneau de l'onglet « Décaissements en
        attente » du guichet : la ligne cliquée identifie déjà précisément le crédit à
        décaisser, on affiche donc directement son calendrier (aucun choix à faire).
        Lecture seule, aucun impact comptable. `company_id` vérifié en défense en profondeur
        (loan_id scope déjà, mais on refuse un crédit d'une autre agence que la session,
        comme les autres méthodes de ce chantier). Renvoie [] si le crédit n'existe pas ou
        n'appartient pas à l'agence."""
        loan = self.env['microfinance.loan'].browse(loan_id)
        if not loan.exists() or (company_id and loan.company_id.id != company_id):
            return []
        state_labels = dict(self._fields['state'].selection)
        return [{
            'id': inst.id,
            'sequence': inst.sequence,
            'due_date': inst.due_date,
            'total_amount': inst.total_amount,
            'residual_amount': inst.residual_amount,
            'state': inst.state,
            'state_label': state_labels.get(inst.state, inst.state),
        } for inst in loan.installment_ids.sorted(lambda i: (i.sequence, i.due_date))]

    def action_apply_penalty(self):
        for inst in self.filtered(lambda x: not x.penalty_applied and x.state in ('pending', 'partial', 'overdue')):
            product = inst.loan_id.product_id
            if not product:
                continue
            penalty_date = fields.Date.add(inst.due_date, days=product.grace_period_days or 0)
            if penalty_date >= fields.Date.context_today(inst):
                continue
            amount = product.penalty_amount if product.penalty_type == 'fixed' else inst.residual_amount * product.penalty_rate / 100.0
            inst.write({'penalty_amount': inst.penalty_amount + amount, 'penalty_applied': True})
        return True
