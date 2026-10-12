# -*- coding: utf-8 -*-
"""Montants d'un fonds partagé vus par une agence.

Trois montants calculés (jamais saisis) par allocation d'agence :
  - Alloué            : total des parts de l'agence sur le fonds (allocation) ;
  - En transit        : parts dont l'écriture miroir est passée mais dont la ligne en suspens (139100) n'est pas
                        lettrée avec une ligne de relevé bancaire ;
  - Reçu en banque    : parts dont cette ligne est lettrée avec une ligne de relevé.
  - Non reçu          : parts sans écriture miroir (côté agence pas encore généré).
L'état de rapprochement se lit sur le lettrage de la ligne, jamais sur un champ saisi.

Deux niveaux, jamais mélangés (la société mère est à la fois le siège et une agence) :
  - N1 « Fonds reçus à répartir (siège) » : contributions bailleur → banque du siège (Dr 139100 du journal de fonds).
        Contribué = dépôts validés − retraits ; reçu en banque = part lettrée avec un relevé ; en transit =
        contribué − reçu en banque (faits bancaires bruts, non nets du partagé) ; reste à répartir = reste_partageable.
        Calculés pour la société mère seulement ; 0 pour une agence.
  - N2 « Part allouée à l'agence » : partages siège → agences (ci-dessus), part gardée du siège comprise (elle reste
        en transit tant que le relevé du journal crédit n'a pas lettré sa 139100).

Une agence ne voit que sa part : pour une société qui n'est pas la société mère, la lecture du fonds (_read_format)
remplace les montants consolidés (100 % du fonds) par ceux de sa propre allocation.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError

# Montants consolidés d'un fonds (toutes agences) : jamais montrés tels quels à une agence.
CONSOLIDATED_FIELDS = ('total_contributions', 'total_decaisse', 'total_rembourse', 'solde_disponible',
                       'reste_partageable')


class ResCompany(models.Model):
    _inherit = 'res.company'

    microfinance_fond_require_received = fields.Boolean(
        string='Décaisser seulement sur les fonds reçus en banque', default=False,
        help="Désactivé par défaut : le contrôle de disponibilité d'un fonds partagé se fait sur la part allouée à "
             "l'agence moins l'utilisé. Activé, il se fait sur le montant reçu en banque (ligne en suspens lettrée "
             "avec un relevé) moins l'utilisé : l'agence ne décaisse pas un fonds encore en transit.",
    )
    microfinance_transfer_rounding_unit = fields.Float(
        string="Unité d'arrondi des virements", default=1.0, digits=(16, 4),
        help="Les parts d'un partage de fonds sont des multiples de cette unité (1 = Ariary entier, la plus petite "
             "unité des virements), la somme des parts restant exactement égale au montant partagé. Indépendant de "
             "la précision de la monnaie. Lue sur la société mère du partage ; 0 = précision de la monnaie.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    microfinance_transfer_rounding_unit = fields.Float(
        related='company_id.microfinance_transfer_rounding_unit', readonly=False, digits=(16, 4),
        string="Unité d'arrondi des virements",
    )

    microfinance_fond_require_received = fields.Boolean(
        related='company_id.microfinance_fond_require_received', readonly=False,
        string='Décaisser seulement sur les fonds reçus en banque',
    )


class MicrofinanceFondAllocation(models.Model):
    _inherit = 'microfinance.fond.allocation'

    amount_in_transit = fields.Monetary(
        string='En transit', compute='_compute_bank_amounts',
        help="Part dont l'écriture miroir est passée mais dont la ligne en suspens n'est pas lettrée avec un relevé.")
    amount_received = fields.Monetary(
        string='Reçu en banque', compute='_compute_bank_amounts',
        help="Part dont la ligne en suspens est lettrée avec une ligne de relevé bancaire.")
    amount_not_received = fields.Monetary(
        string='Non reçu', compute='_compute_bank_amounts',
        help="Part sans écriture miroir côté agence (écriture à générer).")

    def _compute_bank_amounts(self):
        Line = self.env['microfinance.fond.partage.line'].sudo()
        for allocation in self:
            transit = received = missing = 0.0
            if allocation.fond_id.sudo().passer_gl:
                lines = Line.search([
                    ('partage_id.fond_id', '=', allocation.fond_id.id), ('partage_id.state', '=', 'validated'),
                    ('company_id', '=', allocation.company_id.id), ('amount', '>', 0)])
                for line in lines:
                    # Même lecture du lettrage que la mention de la banque (microfinance_fond_transit_banque.py).
                    banked, in_transit, not_received, _journal = line._bank_state()
                    received += banked
                    transit += in_transit
                    missing += not_received
            allocation.amount_in_transit = transit
            allocation.amount_received = received
            allocation.amount_not_received = missing

    def _portfolio_bank_amounts(self, exclude=None):
        """(reçu en banque de l'agence, déjà alloué aux portefeuilles, allouable) pour ce fonds : seule la part de
        l'agence soldée par un relevé compte. `exclude` : répartition à ne pas compter dans le déjà alloué."""
        self.ensure_one()
        self.invalidate_recordset(['amount_in_transit', 'amount_received', 'amount_not_received'])
        received = self.amount_received
        done = self.env['microfinance.portfolio.allocation'].sudo().search([
            ('fond_id', '=', self.fond_id.id), ('company_id', '=', self.company_id.id),
            ('state', '=', 'validated')]) - (exclude or self.env['microfinance.portfolio.allocation'])
        allocated = sum(done.mapped('base_amount'))
        return received, allocated, received - allocated

    def _available_for_disbursement(self):
        """Plafond de décaissement de l'agence sur ce fonds. Par défaut : alloué moins utilisé (inchangé).
        Si la société a activé « décaisser seulement sur les fonds reçus en banque » : reçu en banque moins utilisé."""
        self.ensure_one()
        if self.company_id.sudo().microfinance_fond_require_received:
            return self.amount_received - self.montant_utilise
        return self.solde_disponible


class MicrofinanceFondCredit(models.Model):
    _inherit = 'microfinance.fond.credit'

    agency_allocated = fields.Monetary(
        string='Alloué (ma part)', compute='_compute_agency_amounts', compute_sudo=True,
        help="Total des parts allouées à la société courante sur ce fonds.")
    agency_in_transit = fields.Monetary(
        string='En transit', compute='_compute_agency_amounts', compute_sudo=True,
        help="Parts de la société courante dont la ligne en suspens (139100) n'est pas lettrée avec un relevé.")
    agency_received = fields.Monetary(
        string='Reçu en banque', compute='_compute_agency_amounts', compute_sudo=True,
        help="Parts de la société courante dont la ligne en suspens est lettrée avec un relevé bancaire.")
    agency_not_received = fields.Monetary(
        string='Non reçu', compute='_compute_agency_amounts', compute_sudo=True,
        help="Parts de la société courante sans écriture miroir (à générer).")

    siege_view = fields.Boolean(
        string='Vue siège', compute='_compute_siege_amounts', compute_sudo=True,
        help="Vrai quand la société courante est la société mère : seule elle voit les contributions du fonds (N1).")
    siege_contribue = fields.Monetary(
        string='Contribué (siège)', compute='_compute_siege_amounts', compute_sudo=True,
        help="Dépôts bailleur validés moins retraits, sur le journal de fonds du siège.")
    siege_recu_banque = fields.Monetary(
        string='Reçu en banque (siège)', compute='_compute_siege_amounts', compute_sudo=True,
        help="Part des contributions dont la ligne en suspens est lettrée avec une ligne de relevé du siège.")
    siege_en_transit = fields.Monetary(
        string='En transit (siège)', compute='_compute_siege_amounts', compute_sudo=True,
        help="Contribué moins reçu en banque : contributions comptabilisées, pas encore rapprochées d'un relevé. "
             "Brut : non diminué de ce qui a déjà été partagé aux agences.")

    @api.depends_context('company')
    @api.depends('destination', 'passer_gl', 'company_id', 'contribution_ids.amount',
                 'contribution_ids.type_mouvement', 'contribution_ids.state', 'contribution_ids.move_id')
    def _compute_siege_amounts(self):
        parent = self.env['res.company']._get_microfinance_parent()
        is_parent = bool(parent) and self.env.company == parent
        for fond in self:
            contribue = banked = 0.0
            if is_parent and fond.destination == 'credit' and fond.passer_gl and fond._fund_company() == parent:
                for contrib in fond.contribution_ids.filtered(lambda c: c.state == 'posted' and c.move_id):
                    sign = 1.0 if contrib.type_mouvement == 'depot' else -1.0
                    contribue += sign * contrib.amount
                    banked += sign * contrib._bank_received_amount()
            fond.siege_view = is_parent
            fond.siege_contribue = contribue
            fond.siege_recu_banque = banked
            fond.siege_en_transit = contribue - banked

    @api.model
    def _get_siege_fund_amounts(self, company_id, funds):
        """Totaux N1 de la tuile « Fonds reçus à répartir (siège) » : mêmes champs que la liste."""
        funds = funds.with_company(company_id)
        return {
            'contribue': sum(funds.mapped('siege_contribue')),
            'en_transit': sum(funds.mapped('siege_en_transit')),
            'recu_banque': sum(funds.mapped('siege_recu_banque')),
            'reste': sum(funds.mapped('reste_partageable')) if funds else 0.0,
        }

    def _partage_bank_amounts(self, company, exclude=None):
        """(reçu en banque, déjà réparti, reste à répartir) du fonds pour un partage aux agences, calculé sur le reçu
        en banque de la société mère : le calcul du siège (siege_recu_banque) pour un fonds de crédit, celui de la
        liste (exploitation_recu_banque) pour un fonds d'exploitation. `exclude` : partage à ne pas compter."""
        self.ensure_one()
        fond = self.sudo().with_company(company)
        field = 'exploitation_recu_banque' if fond.destination == 'exploitation' else 'siege_recu_banque'
        fond.invalidate_recordset([field])
        received = fond[field]
        done = fond.partage_ids.filtered(lambda p: p.state == 'validated') - (exclude or fond.partage_ids.browse())
        shared = sum(done.mapped('base_amount'))
        return received, shared, received - shared

    # ------------------------------------------------------------------ montants de l'agence
    def _agency_allocation(self, company):
        self.ensure_one()
        return self.sudo().allocation_ids.filtered(lambda a: a.company_id == company)

    @api.depends_context('company')
    @api.depends('allocation_ids.amount_allocated')
    def _compute_agency_amounts(self):
        for fond in self:
            allocation = fond._agency_allocation(self.env.company)
            fond.agency_allocated = allocation.amount_allocated
            fond.agency_in_transit = allocation.amount_in_transit
            fond.agency_received = allocation.amount_received
            fond.agency_not_received = allocation.amount_not_received

    @api.model
    def _get_agency_fund_amounts(self, company_id, funds=None):
        """Totaux alloué / en transit / reçu en banque / non reçu de l'agence sur les fonds donnés (par défaut
        tous ses fonds partagés alloués). Lecture en sudo : une agence ne lit que sa propre allocation."""
        allocations = self.env['microfinance.fond.allocation'].sudo().search(
            [('company_id', '=', company_id)] + ([('fond_id', 'in', funds.ids)] if funds is not None else []))
        return {
            'allocated': sum(allocations.mapped('amount_allocated')),
            'in_transit': sum(allocations.mapped('amount_in_transit')),
            'received': sum(allocations.mapped('amount_received')),
            'not_received': sum(allocations.mapped('amount_not_received')),
        }

    # ------------------------------------------------------------------ cloisonnement à la source
    def _agency_view(self):
        """Vrai pour un utilisateur (non superutilisateur) dont la société courante n'est pas la société mère."""
        if self.env.su:
            return False
        parent = self.env['res.company']._get_microfinance_parent()
        return bool(parent) and self.env.company != parent

    def _agency_consolidated_values(self, fond):
        """Montants consolidés remplacés, pour la société courante, par ceux de sa propre part."""
        company = self.env.company
        allocation = fond._agency_allocation(company)
        loans = fond.sudo().loan_ids.filtered(
            lambda l: l.company_id == company and l.state in ('active', 'closed', 'defaulted', 'written_off')
            and l.disbursement_date)
        return {
            'total_contributions': allocation.amount_allocated,
            'total_decaisse': sum(loans.mapped('loan_amount')),
            'total_rembourse': sum(
                sum(loan.installment_ids.mapped('paid_principal')) + sum(loan.installment_ids.mapped('paid_interest'))
                + sum(loan.installment_ids.mapped('paid_penalty')) for loan in loans),
            'solde_disponible': allocation.solde_disponible,
            'reste_partageable': 0.0,
        }

    def _read_format(self, fnames, load='_classic_read'):
        # Point commun de read(), web_read() et search_read() : le filtre ne peut pas être contourné par l'un d'eux.
        result = super()._read_format(fnames, load)
        if not self._agency_view():
            return result
        by_id = {values['id']: values for values in result}
        for fond in self:
            values = by_id.get(fond.id)
            if not values or fond.scope != 'multi_company' or not fond.allocation_required:
                continue
            replacement = self._agency_consolidated_values(fond)
            for name in CONSOLIDATED_FIELDS:
                if name in values:
                    values[name] = replacement[name]
        return result

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        if self._agency_view() and any(str(agg).split(':')[0] in CONSOLIDATED_FIELDS for agg in aggregates):
            raise AccessError(_("Les totaux consolidés d'un fonds ne sont pas accessibles depuis une agence."))
        return super()._read_group(domain, groupby, aggregates, having, offset, limit, order)

    def export_data(self, fields_to_export):
        if self._agency_view() and any(str(path).split('/')[0] in CONSOLIDATED_FIELDS for path in fields_to_export):
            raise AccessError(_("Les totaux consolidés d'un fonds ne sont pas accessibles depuis une agence."))
        return super().export_data(fields_to_export)

    # Les totaux stockés doivent être identiques quel que soit l'utilisateur qui déclenche le calcul : les
    # contributions d'un fonds partagé ne sont plus lisibles par les agences, donc calcul en sudo.
    @api.depends('contribution_ids.amount', 'contribution_ids.type_mouvement', 'contribution_ids.state',
                 'loan_ids.state', 'loan_ids.loan_amount', 'loan_ids.disbursement_date',
                 'loan_ids.installment_ids.principal_amount', 'loan_ids.installment_ids.paid_principal',
                 'loan_ids.installment_ids.paid_interest', 'loan_ids.installment_ids.paid_penalty')
    def _compute_fond_totals(self):
        return super(MicrofinanceFondCredit, self.sudo())._compute_fond_totals()
