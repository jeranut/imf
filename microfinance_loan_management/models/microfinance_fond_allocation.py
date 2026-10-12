# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Clé de contexte posée par le partage (microfinance.fond.partage) : seule voie autorisée pour
# créer, modifier ou supprimer une allocation.
ALLOCATION_TECHNICAL_CONTEXT = 'fond_partage_technique'


def format_ariary(amount):
    """Montant entier lisible (« 30 000 000 »), pour les messages de refus."""
    return '{:,.0f}'.format(amount).replace(',', ' ')


def check_whole_amounts(currency, amounts):
    """Refuse un montant décimal : l'unité est celle de la monnaie (res.currency), au moins 1 Ariary."""
    unit = max(currency.rounding, 1.0)
    for amount in amounts:
        ratio = amount / unit
        if abs(ratio - round(ratio)) > 1e-6:
            raise ValidationError(_(
                "Les montants doivent être des Ariary entiers : %s n'est pas un montant valide.") % amount)


class MicrofinanceFondAllocation(models.Model):
    """Part d'un fonds partagé (scope='multi_company') mise à disposition d'une agence.

    Point d'extension : le futur partage par portefeuille d'agent de crédit se greffe sous cette
    allocation via officer_id (agent crédit du prêt, microfinance.loan.officer_id)."""
    _name = 'microfinance.fond.allocation'
    _description = 'Allocation de fonds par agence'
    _order = 'fond_id, company_id'

    fond_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit', required=True, index=True,
        ondelete='restrict', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, index=True, ondelete='restrict', readonly=True,
    )
    currency_id = fields.Many2one(related='fond_id.currency_id', store=True, readonly=True)
    amount_allocated = fields.Monetary(
        string='Montant alloué', readonly=True,
        help="Somme des parts des partages validés de ce fonds pour cette agence.",
    )
    montant_utilise = fields.Monetary(
        string='Montant utilisé', compute='_compute_allocation_totals', store=True,
        help="Principal restant dû des crédits 'approved'/'active' de cette agence rattachés à ce "
             "fonds (même définition que l'encours de microfinance.fond.credit.solde_disponible). "
             "Agrégation en sudo : indépendante des ir.rule société.",
    )
    solde_disponible = fields.Monetary(
        string='Solde disponible', compute='_compute_allocation_totals', store=True,
        help="Montant alloué diminué du montant utilisé : plafond de décaissement de l'agence sur ce fonds.",
    )

    _sql_constraints = [
        ('fond_company_unique', 'unique(fond_id, company_id)',
         'Une seule allocation par fonds et par agence.'),
    ]

    @api.depends('amount_allocated', 'fond_id.loan_ids.state', 'fond_id.loan_ids.company_id',
                 'fond_id.loan_ids.loan_amount', 'fond_id.loan_ids.installment_ids.principal_amount',
                 'fond_id.loan_ids.installment_ids.paid_principal')
    def _compute_allocation_totals(self):
        # Mêmes états et même boucle Python explicite que MicrofinanceFondCredit._compute_fond_totals
        # (cf. son commentaire sur mapped(lambda) et ensure_one() de _get_principal_outstanding).
        outstanding_states = ('approved', 'active')
        for allocation in self:
            loans = allocation.fond_id.sudo().loan_ids.filtered(
                lambda l: l.company_id == allocation.company_id and l.state in outstanding_states)
            utilise = sum(loan._get_principal_outstanding() for loan in loans)
            allocation.montant_utilise = utilise
            allocation.solde_disponible = allocation.amount_allocated - utilise

    def _check_technical_context(self):
        if not self.env.context.get(ALLOCATION_TECHNICAL_CONTEXT):
            raise UserError(_(
                "Une allocation ne se modifie pas directement : passez par « Partage des fonds »."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_technical_context()
        return super().create(vals_list)

    def write(self, vals):
        self._check_technical_context()
        return super().write(vals)

    def unlink(self):
        self._check_technical_context()
        return super().unlink()
