# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanPayment(models.Model):
    _inherit = 'microfinance.loan.payment'

    payment_origin = fields.Selection([
        ('manual', 'Manuel'),
        ('savings_auto_debit', 'Prélèvement automatique sur épargne'),
    ], string='Origine du paiement', default='manual', required=True, tracking=True)

    # ------------------------------------------------------------------
    # Sous-lot A — détection de la situation avant comptabilisation
    # (docs_dev/guichet_caisse/AUDIT_cascade_remboursement.md)
    # ------------------------------------------------------------------
    @api.model
    def analyze_repayment_situation(self, loan_id, amount):
        """Analyse — SANS RIEN ÉCRIRE — un projet de remboursement guichet, pour décider si
        une confirmation par assistant est nécessaire avant d'appliquer la cascade
        d'allocation normale (``_allocation_plan``). Aucune comptabilisation, aucun ``create``,
        aucune écriture sur les échéances.

        Vit dans ``microfinance_savings_management`` (et non sur le modèle de base de
        ``microfinance_loan_management``) parce qu'elle a besoin de ``loan.savings_account_id``,
        champ ajouté par ce module ; ``_allocation_plan`` reste hérité du modèle de base et
        n'est pas dupliqué.

        « En retard » est évalué **à la volée** : ``due_date < aujourd'hui`` ET
        ``residual_amount > 0.01``. On ne se fie pas au champ ``state`` stocké, dont le
        passage à ``overdue`` dépend du cron quotidien
        ``cron_update_overdue_and_penalties`` et peut donc être périmé en cours de journée
        (cf. AUDIT §10). Ce critère couvre aussi bien une échéance entièrement impayée et
        échue qu'une échéance partiellement soldée et échue (``state == 'partial'``).

        « Obligation immédiate » (``base_due``) = **toutes** les échéances en retard cumulées
        s'il y en a ; **sinon la prochaine échéance non soldée** (échéancier à jour). C'est le
        montant que l'appelant impute au crédit sur le chemin « épargne » de l'assistant 2,
        le reste (``surplus``) partant sur le compte d'épargne.

        Retour : un dict décrivant la situation. ``situation`` vaut :

        - ``'direct'``  : aucune confirmation. L'appelant enchaîne sur ``register_operation``
          exactement comme aujourd'hui. Cas : le montant ne couvre (même partiellement) que
          l'obligation immédiate, sans déborder au-delà.
        - ``'cascade'`` : le montant solde la première échéance en retard ET déborde sur au
          moins une deuxième échéance en retard, **sans surplus** au-delà des retards.
          → assistant de confirmation de cascade (sous-lot B, assistant 1).
        - ``'surplus'`` : l'obligation immédiate est **intégralement soldée** par ce montant
          et il **reste un surplus**. Concerne aussi bien « toutes les échéances en retard
          soldées + surplus » que « aucune échéance en retard, montant supérieur à la
          prochaine échéance ». → assistant anticipation / épargne (sous-lot B, assistant 2).

        Le sous-lot A s'arrête ici : ce retour est de la donnée brute. Le sous-lot B fera
        dériver de ``situation`` l'``ir.actions.act_window`` de l'assistant concerné.
        """
        loan = self.env['microfinance.loan'].browse(loan_id)
        today = fields.Date.context_today(self)

        unpaid = loan.installment_ids.filtered(
            lambda i: i.residual_amount > 0.01
        ).sorted(lambda i: (i.due_date, i.sequence))
        overdue = unpaid.filtered(lambda i: i.due_date and i.due_date < today)
        future = unpaid - overdue

        overdue_total = sum(overdue.mapped('residual_amount'))
        future_total = sum(future.mapped('residual_amount'))
        balance_total = loan.balance_total
        # Résolution du compte épargne cible du surplus : loan.savings_account_id
        # (prélèvement) OU, à défaut, un compte dont « Crédit lié » pointe ce crédit — les
        # deux rattachements ne sont pas synchronisés (cf. helper).
        surplus_account = loan._get_repayment_surplus_savings_account()

        base = {
            'loan_id': loan.id,
            'amount': amount,
            'overdue_total': overdue_total,
            'future_total': future_total,
            'balance_total': balance_total,
            'base_due': 0.0,
            'surplus': 0.0,
            'future_anticipable': False,
            'exceeds_balance_total': amount > balance_total + 0.01,
            'has_savings_account': bool(surplus_account),
            'savings_account_name': surplus_account.display_name or '',
            'overdue_lines': [],
        }

        # Montant nul/négatif ou aucune échéance non soldée : rien à confirmer, on laisse la
        # validation de fond (montant > 0, garde « Surpaiement interdit », état du crédit) au
        # chemin de comptabilisation existant, inchangé.
        if amount <= 0.01 or not unpaid:
            return dict(base, situation='direct')

        def _lines(plan):
            return [{
                'id': inst.id,
                'sequence': inst.sequence,
                'due_date': inst.due_date,
                'residual_amount': inst.residual_amount,
                'allocated': i + p + pen,
            } for (inst, i, p, pen) in plan]

        if overdue:
            # Simulation de l'allocation du montant sur les seules échéances EN RETARD, via
            # le générateur partagé (pur, ne mute rien). `remaining` = ce qui n'a pas pu être
            # absorbé par les retards.
            plan = list(self._allocation_plan(overdue, amount))
            allocated_to_overdue = sum(i + p + pen for (_inst, i, p, pen) in plan)
            remaining = amount - allocated_to_overdue

            if remaining > 0.01:
                # Toutes les échéances en retard sont soldées par ce montant, et il reste un
                # surplus. « Rien à anticiper » si ce surplus dépasse le résiduel total des
                # échéances futures (le montant atteint/dépasse balance_total) : seule
                # l'option épargne a un sens côté assistant 2.
                return dict(
                    base,
                    situation='surplus',
                    base_due=overdue_total,
                    surplus=remaining,
                    future_anticipable=(future_total > 0.01 and remaining <= future_total + 0.01),
                    overdue_lines=_lines(plan),
                )

            # `remaining` <= 0.01 : le montant est intégralement absorbé par les échéances en
            # retard.
            if len(plan) >= 2:
                # Débordement de la première échéance en retard sur au moins une deuxième.
                return dict(base, situation='cascade', base_due=overdue_total, overdue_lines=_lines(plan))

            # Une seule échéance en retard touchée (soldée ou passée en partiel), rien au-delà.
            return dict(base, situation='direct', base_due=overdue_total)

        # --- Aucune échéance en retard ---------------------------------------------------
        # L'obligation immédiate est la prochaine échéance non soldée. Tout ce qui la dépasse
        # est un surplus : on présente l'assistant anticipation / épargne (choix explicite du
        # caissier), y compris en l'absence de tout retard.
        next_residual = future[:1].residual_amount
        if amount <= next_residual + 0.01:
            return dict(base, situation='direct', base_due=next_residual)

        anticipatable = future_total - next_residual  # résiduel des échéances au-delà de la prochaine
        return dict(
            base,
            situation='surplus',
            base_due=next_residual,
            surplus=amount - next_residual,
            future_anticipable=(anticipatable > 0.01 and (amount - next_residual) <= anticipatable + 0.01),
            overdue_lines=[],
        )
