# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Clé de contexte posée par microfinance.portfolio.allocation (répartition agence -> portefeuille,
# R2) : seule voie autorisée pour modifier amount_allocated. Même convention que
# microfinance_fond_allocation.ALLOCATION_TECHNICAL_CONTEXT (partage mère -> agences), dont ce
# modèle reprend le gabarit (AUDIT_portefeuille_agent.md, Phase 2 correction 1/3).
PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT = 'portfolio_allocation_technique'


class MicrofinancePortfolio(models.Model):
    """Portefeuille d'un agent de crédit dans une agence (R1 : un agent a un seul portefeuille,
    unique par (agent, agence)). Ledger d'allocation de fonds reçu par l'agence et réparti par le
    gestionnaire entre les portefeuilles de ses agents (R2) - même rôle que
    microfinance.fond.allocation (part d'agence dans un fonds multi-agences), un niveau plus bas."""
    _name = 'microfinance.portfolio'
    _description = 'Portefeuille agent de crédit'
    _order = 'company_id, agent_id'

    agent_id = fields.Many2one(
        'res.users', string='Agent crédit', required=True, index=True, ondelete='restrict',
        help="Même champ que microfinance.loan.officer_id (R1 : un agent, un portefeuille par agence).",
    )
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, index=True, ondelete='restrict',
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount_allocated = fields.Monetary(
        string='Fonds alloué', readonly=True,
        help="Somme des parts des répartitions (microfinance.portfolio.allocation) validées pour "
             "ce portefeuille. Ne se modifie que via cette répartition (ALLOCATION_TECHNICAL_CONTEXT).",
    )
    montant_utilise = fields.Monetary(
        string='Fonds utilisé', compute='_compute_portfolio_totals',
        help="Principal restant dû des crédits 'approved'/'active' de cet agent dans cette agence "
             "RATTACHÉS À UN FONDS (les crédits de reprise sans fonds n'y entrent pas) (même définition que microfinance.fond.allocation.montant_utilise). Non stocké -"
             "contrairement à fond.allocation.montant_utilise, qui a un vrai chemin de dépendance "
             "ORM (fond_id.loan_ids), aucun champ relationnel direct ne relie un portefeuille aux "
             "crédits de son agent (ceux-ci ne connaissent que officer_id + company_id) : un "
             "@api.depends ne pourrait pas suivre les changements d'état des crédits, d'où un "
             "compute toujours recalculé à la lecture plutôt qu'un stored potentiellement périmé.",
    )
    solde_disponible = fields.Monetary(
        string='Fonds disponible', compute='_compute_portfolio_totals',
        help="Fonds alloué diminué du fonds utilisé : plafond de décaissement de cet agent.",
    )

    _sql_constraints = [
        ('agent_company_unique', 'unique(agent_id, company_id)',
         "Un seul portefeuille par agent et par agence (R1)."),
    ]
    _rec_names_search = ['agent_id.name', 'company_id.name']

    @api.depends('agent_id.name', 'company_id.name')
    def _compute_display_name(self):
        for portfolio in self:
            if portfolio.agent_id:
                portfolio.display_name = "%s – %s" % (
                    portfolio.agent_id.name, portfolio.company_id.name)
            else:
                portfolio.display_name = _("Portefeuille #%s", portfolio.id)

    def _get_outstanding_fund_loans(self):
        """Crédits comptés dans le « fonds utilisé » de ces portefeuilles : 'approved'/'active',
        de l'agent ET de la société du portefeuille, rattachés à un fonds (fond_credit_id). Un
        crédit sans fonds (reprise d'historique) ou d'une autre société n'y entre pas. Source
        unique de la tuile du dashboard, de la liste Portefeuilles et du journal « Tous les
        fonds » (qui en tire aussi le détail par fonds)."""
        Loan = self.env['microfinance.loan'].sudo()
        loans = Loan
        for portfolio in self:
            loans |= Loan.search([
                ('officer_id', '=', portfolio.agent_id.id),
                ('company_id', '=', portfolio.company_id.id),
                ('fond_credit_id', '!=', False),
                ('state', 'in', ('approved', 'active')),
            ])
        return loans

    def _compute_portfolio_totals(self):
        for portfolio in self:
            utilise = sum(loan._get_principal_outstanding()
                          for loan in portfolio._get_outstanding_fund_loans())
            portfolio.montant_utilise = utilise
            portfolio.solde_disponible = portfolio.amount_allocated - utilise

    def _check_technical_context(self):
        if not self.env.context.get(PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT):
            raise UserError(_(
                "Le fonds alloué d'un portefeuille ne se modifie pas directement : passez par "
                "« Répartition du fonds d'agence »."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        # amount_allocated n'est jamais fourni à la création "normale" (menu Portefeuilles,
        # post-migrate) : seule microfinance.portfolio.allocation l'écrit ensuite, sous contexte.
        for vals in vals_list:
            if vals.get('amount_allocated'):
                self._check_technical_context()
        return super().create(vals_list)

    def write(self, vals):
        if 'amount_allocated' in vals:
            self._check_technical_context()
        return super().write(vals)

    def unlink(self):
        for portfolio in self:
            if portfolio.amount_allocated:
                raise UserError(_(
                    "Impossible de supprimer le portefeuille de « %(agent)s » : du fonds lui a "
                    "déjà été alloué. Désactivez-le plutôt."
                ) % {'agent': portfolio.agent_id.display_name})
        return super().unlink()

    def action_open_dashboard(self):
        """Ouvre le dashboard agent (action_microfinance_agent_portfolio, id 914, inchangée)
        sur CE portefeuille, depuis la liste/fiche microfinance.portfolio (menu "Portefeuille",
        ex-"Mon portefeuille"). Transmet seulement portfolio_id dans le contexte : c'est
        get_dashboard_data() côté serveur qui résout agent_id/company_id par ORM (donc re-vérifié
        par les record rules de CE modèle) - jamais un agent_id envoyé tel quel par le client."""
        self.ensure_one()
        if self.company_id != self.env.company:
            raise UserError(_(
                "Ce portefeuille appartient à l'agence « %(portfolio)s » ; l'agence active est "
                "« %(active)s ». Changez d'agence dans le sélecteur pour le consulter."
            ) % {'portfolio': self.company_id.name, 'active': self.env.company.name})
        action = self.env['ir.actions.actions']._for_xml_id(
            'microfinance_loan_management.action_microfinance_agent_portfolio')
        action['context'] = {'dashboard_topic': 'portefeuille', 'portfolio_id': self.id}
        return action

    def action_open_allocation_history(self):
        """Historique par agent (M4) : lignes de répartition validées pour CE portefeuille, triées
        par date décroissante (_order du modèle ligne : allocation_id, portfolio_id - on force ici
        le tri par date pour la vue historique, voir view_microfinance_portfolio_allocation_line_
        history_tree). Lecture seule, même portée de visibilité que le portefeuille lui-même
        (record rules microfinance_portfolio_allocation_line_*)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Historique des allocations'),
            'res_model': 'microfinance.portfolio.allocation.line',
            'view_mode': 'tree',
            'views': [(self.env.ref(
                'microfinance_loan_management.view_microfinance_portfolio_allocation_line_history_tree').id, 'tree')],
            'domain': [('portfolio_id', '=', self.id), ('state', '=', 'validated')],
        }
