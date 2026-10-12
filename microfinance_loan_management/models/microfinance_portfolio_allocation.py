# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round

from .microfinance_fond_allocation import check_whole_amounts, format_ariary
from .microfinance_portfolio import PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT


class MicrofinanceFondAllocationPortfolioExtension(models.Model):
    """Extension additive (même patron que microfinance_savings_management/models/
    microfinance_loan_payment_extension.py) : n'ajoute qu'un champ calculé, ne touche à aucune
    logique existante de microfinance.fond.allocation (gabarit mère -> agences, lecture seule)."""
    _inherit = 'microfinance.fond.allocation'

    reste_a_repartir_portefeuille = fields.Monetary(
        string='Reste à répartir (portefeuilles)', compute='_compute_reste_a_repartir_portefeuille',
        help="Fonds alloué à l'agence sur ce fonds, diminué de ce que le gestionnaire a déjà "
             "réparti (répartitions validées) entre les portefeuilles de ses agents (R2).",
    )

    @api.depends('amount_allocated')
    def _compute_reste_a_repartir_portefeuille(self):
        Repartition = self.env['microfinance.portfolio.allocation'].sudo()
        for allocation in self:
            repartitions = Repartition.search([
                ('fond_id', '=', allocation.fond_id.id),
                ('company_id', '=', allocation.company_id.id),
                ('state', '=', 'validated'),
            ])
            allocation.reste_a_repartir_portefeuille = allocation.amount_allocated - sum(repartitions.mapped('base_amount'))


class MicrofinancePortfolioAllocation(models.Model):
    """Répartition d'un fonds reçu par une agence (microfinance.fond.allocation) entre les
    portefeuilles de ses agents (R2) - même schéma que microfinance.fond.partage (partage mère ->
    agences, AUDIT_portefeuille_agent.md A5) : cumulatif, lignes % + montant rééquilibrées,
    workflow brouillon/validé/annulé, aucune écriture comptable."""
    _name = 'microfinance.portfolio.allocation'
    _description = "Répartition du fonds d'agence entre portefeuilles"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    fond_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit', required=True, tracking=True,
        ondelete='restrict', domain="[('active', '=', True), ('destination', '=', 'credit')]",
    )
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, readonly=True, copy=False, index=True,
        default=lambda self: self.env.company,
        help="Agence qui répartit : cloisonne la visibilité, un gestionnaire ne répartit que le "
             "fonds reçu par SA propre agence (R2).",
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    currency_id = fields.Many2one(related='fond_id.currency_id', store=True, readonly=True)
    base_amount = fields.Monetary(
        string='Montant à répartir', default=0.0, tracking=True,
        help="Pré-rempli avec le reste à répartir de l'allocation d'agence ; ne peut pas le dépasser. "
             "Mode partage : saisi, doit être strictement positif (_check_base_amount). Mode "
             "allocation : recalculé à partir des lignes (_sync_header_base_amount) - le default=0.0 "
             "couvre la fenêtre entre l'insertion de l'en-tête et ce recalcul (ex: création sans "
             "ligne, ou en-tête inséré avant que les lignes ne soient traitées).",
    )
    reste_a_repartir = fields.Monetary(
        string="Reste à répartir de l'allocation d'agence", compute='_compute_reste_a_repartir_agence', readonly=True,
    )
    agence_recu_banque = fields.Monetary(
        string="Reçu en banque de l'agence", compute='_compute_agence_bank_amounts',
        help="Part de l'agence sur ce fonds dont la ligne en suspens (139100) est soldée par un relevé bancaire.")
    agence_deja_alloue = fields.Monetary(
        string='Déjà alloué', compute='_compute_agence_bank_amounts',
        help="Total des autres répartitions validées de cette agence sur ce fonds.")
    agence_allouable = fields.Monetary(
        string='Allouable', compute='_compute_agence_bank_amounts',
        help="Reçu en banque de l'agence moins déjà alloué : plafond d'une allocation, appliqué à la validation.")
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('validated', 'Validé'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', required=True, copy=False, tracking=True)
    allocation_mode = fields.Selection([
        ('partage', 'Partage'),
        ('allocation', 'Allocation'),
    ], string='Mode', default='partage', required=True, tracking=True,
        help="Partage : comportement historique (montant à répartir + parts % totalisant 100%). "
             "Allocation : le gestionnaire attribue librement à chaque portefeuille, sans exigence "
             "de total (M2/M3 - un reste non réparti est autorisé, les nouveaux agents ou fonds "
             "vides sont éligibles comme les autres).",
    )
    input_type = fields.Selection([
        ('montant', 'Montant'),
        ('pourcentage', 'Pourcentage'),
    ], string='Saisie', default='montant', required=True,
        help="Mode allocation seulement : la colonne éditable des lignes (l'autre se recalcule en "
             "lecture seule à partir du reste à répartir de l'agence).",
    )
    line_ids = fields.One2many('microfinance.portfolio.allocation.line', 'allocation_id', string='Parts par portefeuille', copy=True)
    total_percent = fields.Float(string='Total %', compute='_compute_totals', digits=(16, 4))
    total_amount = fields.Monetary(string='Total réparti', compute='_compute_totals')
    reste_a_partager = fields.Monetary(string='Reste à répartir (ligne)', compute='_compute_totals')

    @api.depends('fond_id', 'company_id')
    def _compute_reste_a_repartir_agence(self):
        Allocation = self.env['microfinance.fond.allocation'].sudo()
        for repartition in self:
            allocation = Allocation.search([
                ('fond_id', '=', repartition.fond_id.id), ('company_id', '=', repartition.company_id.id),
            ], limit=1)
            repartition.reste_a_repartir = allocation.reste_a_repartir_portefeuille if allocation else 0.0

    def _bank_amounts(self):
        """(reçu en banque, déjà alloué, allouable) de l'agence de cette répartition sur son fonds ; 0 sans allocation
        d'agence. Seule la société de la répartition est lue."""
        self.ensure_one()
        allocation = self.env['microfinance.fond.allocation'].sudo().search([
            ('fond_id', '=', self.fond_id.id), ('company_id', '=', self.company_id.id)], limit=1)
        if not allocation:
            return 0.0, 0.0, 0.0
        return allocation._portfolio_bank_amounts(exclude=self)

    @api.depends('fond_id', 'company_id', 'state')
    def _compute_agence_bank_amounts(self):
        for repartition in self:
            amounts = repartition._bank_amounts() if repartition.fond_id and repartition.company_id else (0.0,) * 3
            repartition.agence_recu_banque, repartition.agence_deja_alloue, repartition.agence_allouable = amounts

    def _check_bank_received(self):
        """Contrôle permanent, sans réglage ni exception : on n'alloue que de l'argent reçu en banque. Le montant ne
        dépasse pas le reçu en banque de l'agence pour ce fonds moins le déjà alloué (une diminution, c'est-à-dire
        l'annulation d'une répartition, n'est jamais contrôlée)."""
        self.ensure_one()
        check_whole_amounts(self.currency_id, [self.base_amount] + self.line_ids.mapped('amount'))
        received, allocated, available = self._bank_amounts()
        if float_compare(self.base_amount, available, precision_rounding=self.currency_id.rounding) > 0:
            raise UserError(_(
                "Montant non disponible : reçu en banque %(recu)s, déjà alloué %(alloue)s, disponible %(dispo)s. "
                "Le relevé de l'agence n'a pas encore confirmé cette somme."
            ) % {'recu': format_ariary(received), 'alloue': format_ariary(allocated), 'dispo': format_ariary(available)})

    @api.depends('base_amount', 'line_ids.percent', 'line_ids.amount')
    def _compute_totals(self):
        for repartition in self:
            repartition.total_percent = sum(repartition.line_ids.mapped('percent'))
            repartition.total_amount = sum(repartition.line_ids.mapped('amount'))
            repartition.reste_a_partager = repartition.base_amount - repartition.total_amount

    def _check_own_agency_gestionnaire(self, company_ids=()):
        """Seul le gestionnaire d'agence peut créer/modifier/valider une répartition, et
        uniquement pour SA propre agence (R2, correction Phase 2 §3). Un manager/auditeur
        (visibilité en lecture plus large ailleurs dans le module) ne peut pas répartir.
        `company_ids` : sociétés visées par un create() (self est encore vide à ce stade)."""
        if self.env.su:
            return
        if not self.env.user.has_group('microfinance_loan_management.group_microfinance_gestionnaire'):
            raise AccessError(_("Seul le gestionnaire d'agence peut répartir le fonds entre portefeuilles."))
        for repartition in self:
            company_ids = company_ids + (repartition.company_id.id,)
        if any(company_id and company_id != self.env.company.id for company_id in company_ids):
            raise AccessError(_("Vous ne pouvez répartir que le fonds de votre propre agence."))

    @api.model
    def _default_line_vals(self, company_id):
        """Une ligne à 0 par portefeuille actif de l'agence (crée le portefeuille au besoin pour
        tout agent ayant déjà un crédit dans l'agence mais pas encore de ligne microfinance.portfolio
        - jamais pour un autre agent au hasard : réutilise exactement microfinance.loan.officer_id,
        même périmètre que le post-migrate)."""
        Portfolio = self.env['microfinance.portfolio'].sudo()
        portfolios = Portfolio.search([('company_id', '=', company_id), ('active', '=', True)])
        return [{'portfolio_id': p.id, 'percent': 0.0, 'amount': 0.0} for p in portfolios]

    @api.onchange('fond_id')
    def _onchange_fond_id(self):
        if self.fond_id:
            Allocation = self.env['microfinance.fond.allocation'].sudo()
            allocation = Allocation.search([
                ('fond_id', '=', self.fond_id.id), ('company_id', '=', self.company_id.id)], limit=1)
            reste = allocation.reste_a_repartir_portefeuille if allocation else 0.0
            if self.allocation_mode == 'partage':
                self.base_amount = reste
        if not self.line_ids:
            self.line_ids = [Command.create(vals) for vals in self._default_line_vals(self.company_id.id)]
        if self.allocation_mode == 'partage':
            self._onchange_base_amount()
        else:
            self.base_amount = sum(self.line_ids.mapped('amount'))

    @api.onchange('base_amount')
    def _onchange_base_amount(self):
        if self.allocation_mode != 'partage':
            return
        for line in self.line_ids:
            line.amount = line._amount_from_percent(self.base_amount, line.percent)
            line.percent_ref, line.amount_ref = line.percent, line.amount

    @api.onchange('allocation_mode')
    def _onchange_allocation_mode(self):
        # Changer de mode repart d'une page blanche (M1/M2 sont deux comportements distincts, pas
        # de conversion de parts de l'un vers l'autre) : lignes remises à 0, base_amount recalculée
        # selon le nouveau mode.
        for line in self.line_ids:
            line.percent = line.amount = line.percent_ref = line.amount_ref = 0.0
        self._onchange_fond_id()

    @api.onchange('input_type')
    def _onchange_input_type(self):
        if self.allocation_mode == 'allocation':
            self.line_ids._sync_from_allocation_mode()
            self.base_amount = sum(self.line_ids.mapped('amount'))

    @api.onchange('line_ids')
    def _onchange_line_ids_rebalance(self):
        if self.allocation_mode == 'allocation':
            self.line_ids._sync_from_allocation_mode()
            self.base_amount = sum(self.line_ids.mapped('amount'))
        else:
            self._rebalance_lines()

    def _rebalance_lines(self):
        # Algorithme identique à microfinance.fond.partage._rebalance_lines (même schéma, A5) :
        # la ligne éditée (montant ou %, le montant prime si les deux ont changé) est bornée à
        # [0, base], les autres sont réparties au prorata de leur dernier poids connu, avec le
        # reliquat d'arrondi sur la dernière.
        self.ensure_one()
        lines = self.line_ids
        if not lines or self.state != 'draft' or self.allocation_mode != 'partage':
            return
        currency = self.currency_id or self.env.company.currency_id
        rounding = currency.rounding
        base = self.base_amount or 0.0
        edited = amount_edited = None
        for line in lines:
            a_changed = float_compare(line.amount, line.amount_ref, precision_rounding=rounding) != 0
            p_changed = float_compare(line.percent, line.percent_ref, precision_digits=4) != 0
            if a_changed or p_changed:
                edited, amount_edited = line, a_changed
                break
        if not edited:
            return
        others = lines - edited
        if amount_edited and base > 0:
            amount = min(max(edited.amount, 0.0), base)
            percent = min(float_round(amount / base * 100.0, precision_digits=4), 100.0)
        elif amount_edited:
            amount, percent = 0.0, edited.percent_ref
        else:
            percent = min(max(edited.percent, 0.0), 100.0)
            amount = float_round(base * percent / 100.0, precision_rounding=rounding) if base > 0 else 0.0
        if not others:
            percent, amount = 100.0, (base if base > 0 else 0.0)
        edited.percent, edited.amount = percent, amount
        if others:
            remaining_pct = max(float_round(100.0 - percent, precision_digits=4), 0.0)
            remaining_amount = max(float_round(base - amount, precision_rounding=rounding), 0.0) if base > 0 else 0.0
            weights = [max(o.percent_ref, 0.0) for o in others]
            total = sum(weights)
            if total <= 0:
                weights, total = [1.0] * len(others), float(len(others))
            cum_share = prev_pct = prev_amount = 0.0
            for index, other in enumerate(others):
                cum_share += weights[index] / total
                if index == len(others) - 1:
                    cum_pct, cum_amount = remaining_pct, remaining_amount
                else:
                    cum_pct = float_round(remaining_pct * cum_share, precision_digits=4)
                    cum_amount = float_round(remaining_amount * cum_share, precision_rounding=rounding)
                other.percent = max(float_round(cum_pct - prev_pct, precision_digits=4), 0.0)
                other.amount = max(float_round(cum_amount - prev_amount, precision_rounding=rounding), 0.0)
                prev_pct, prev_amount = cum_pct, cum_amount
        for line in lines:
            line.percent_ref, line.amount_ref = line.percent, line.amount

    @api.constrains('base_amount', 'allocation_mode')
    def _check_base_amount(self):
        for repartition in self:
            # Mode allocation (M2) : base_amount est la somme des lignes, potentiellement nulle
            # tant que le gestionnaire n'a rien saisi (brouillon) - aucune exigence de total ici,
            # seule action_validate refuse une répartition sans aucune ligne non nulle (M3).
            if repartition.allocation_mode == 'partage' and repartition.base_amount <= 0:
                raise ValidationError(_('Le montant à répartir doit être strictement positif.'))

    @api.constrains('base_amount', 'line_ids')
    def _check_total_within_base(self):
        for repartition in self:
            if float_compare(sum(repartition.line_ids.mapped('amount')), repartition.base_amount,
                             precision_rounding=repartition.currency_id.rounding) > 0:
                raise ValidationError(_('Le total réparti dépasse le montant à répartir.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_own_agency_gestionnaire(
            company_ids=tuple(vals.get('company_id') for vals in vals_list))
        for vals in vals_list:
            if vals.get('name', 'Nouveau') in (False, '', 'Nouveau'):
                vals['name'] = self.env['ir.sequence'].next_by_code('microfinance.portfolio.allocation') or 'Nouveau'
            company_id = vals.get('company_id', self.env.company.id)
            if not vals.get('line_ids'):
                vals['line_ids'] = [Command.create(v) for v in self._default_line_vals(company_id)]
        repartitions = super(MicrofinancePortfolioAllocation, self.with_context(portfolio_allocation_defer_check=True)).create(vals_list)
        return repartitions.with_context(portfolio_allocation_defer_check=False)

    def write(self, vals):
        self._check_own_agency_gestionnaire()
        if set(vals) - {'state'} and any(r.state != 'draft' for r in self):
            raise UserError(_('Seule une répartition en brouillon peut être modifiée.'))
        if 'base_amount' in vals and 'line_ids' not in vals:
            # Mode partage (inchangé) : changer base_amount rééquilibre les lignes au prorata de
            # leur %. Mode allocation (M2) : base_amount est la somme des lignes (_sync_header_
            # base_amount, appelé depuis la ligne elle-même) - ici une simple écriture, sans toucher
            # aux lignes qui sont déjà, par construction, la source de cette valeur.
            partage = self.filtered(lambda r: r.allocation_mode == 'partage')
            for repartition in partage:
                line_updates = [Command.update(line.id, {
                    'amount': line._amount_from_percent(vals['base_amount'], line.percent),
                    'percent': line.percent,
                }) for line in repartition.line_ids]
                super(MicrofinancePortfolioAllocation, repartition.with_context(portfolio_allocation_defer_check=True)).write(
                    dict(vals, line_ids=line_updates))
            others = self - partage
            if others:
                super(MicrofinancePortfolioAllocation, others.with_context(portfolio_allocation_defer_check=True)).write(vals)
            return True
        return super(MicrofinancePortfolioAllocation, self.with_context(portfolio_allocation_defer_check=True)).write(vals)

    def unlink(self):
        self._check_own_agency_gestionnaire()
        if any(r.state == 'validated' for r in self):
            raise UserError(_("Une répartition validée ne peut pas être supprimée : annulez-la d'abord."))
        return super().unlink()

    def _percent_total_ok(self):
        self.ensure_one()
        if not self.base_amount:
            return False
        tolerance = 0.01 + 100.0 * self.currency_id.rounding * len(self.line_ids) / self.base_amount
        return abs(self.total_percent - 100.0) <= tolerance

    def action_repartir_egalement(self):
        self.ensure_one()
        if self.allocation_mode != 'partage':
            raise UserError(_("« Répartir également » n'existe qu'en mode partage."))
        if self.state != 'draft':
            raise UserError(_('Seule une répartition en brouillon peut être modifiée.'))
        if self.base_amount <= 0:
            raise UserError(_('Renseignez d\'abord un montant à répartir supérieur à zéro.'))
        lines = self.line_ids
        if not lines:
            raise UserError(_('Aucun portefeuille à répartir.'))
        rounding = self.currency_id.rounding
        share_pct = float_round(100.0 / len(lines), precision_digits=4)
        share_amount = float_round(self.base_amount / len(lines), precision_rounding=rounding)
        remaining_pct, remaining_amount = 100.0, self.base_amount
        for line in lines[:-1]:
            line.write({'percent': share_pct, 'amount': share_amount})
            remaining_pct -= share_pct
            remaining_amount -= share_amount
        lines[-1].write({
            'percent': float_round(remaining_pct, precision_digits=4),
            'amount': float_round(remaining_amount, precision_rounding=rounding),
        })
        return True

    def action_validate(self):
        self._check_own_agency_gestionnaire()
        Portfolio = self.env['microfinance.portfolio'].sudo().with_context(**{PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT: True})
        for repartition in self:
            if repartition.state != 'draft':
                raise UserError(_('Seule une répartition en brouillon peut être validée.'))
            rounding = repartition.currency_id.rounding
            repartition._check_bank_received()
            # Plafond non contournable (Phase 2 §3) : la somme des répartitions agence ->
            # portefeuilles ne peut jamais dépasser le fonds reçu par l'agence (mère -> agence),
            # vérifié ici au présent (reste_a_repartir_portefeuille lu en sudo, indépendant des
            # droits de l'utilisateur) - pas seulement au moment du pré-remplissage côté client.
            if float_compare(repartition.base_amount, repartition.reste_a_repartir, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Le montant à répartir (%(base)s) dépasse le reste à répartir du fonds de '
                    "l'agence (%(reste)s)."
                ) % {'base': repartition.base_amount, 'reste': repartition.reste_a_repartir})
            if repartition.allocation_mode == 'partage' and not repartition._percent_total_ok():
                raise UserError(_(
                    'La répartition doit totaliser 100 %% du montant à répartir (actuellement %.4f %%).'
                ) % repartition.total_percent)
            nonzero_lines = repartition.line_ids.filtered(lambda l: not float_is_zero(l.amount, precision_rounding=rounding))
            if repartition.allocation_mode == 'allocation' and not nonzero_lines:
                raise UserError(_("Aucune allocation à valider : renseignez au moins un portefeuille."))
            details = []
            for line in nonzero_lines:
                portfolio = Portfolio.browse(line.portfolio_id.id)
                portfolio.amount_allocated += line.amount
                details.append('%s : %s (%.4f %%)' % (portfolio.agent_id.display_name, line.amount, line.percent))
            repartition.state = 'validated'
            repartition.message_post(body=_('Répartition validée : %s') % ' ; '.join(details))
        # reste_a_repartir(_portefeuille) ne dépendent (@api.depends) que de leurs propres
        # fond_id/company_id/amount_allocated, pas de l'état des AUTRES répartitions du même
        # fond/agence : sans invalidation explicite, une répartition déjà en cache (même
        # transaction - gestionnaire qui enchaîne plusieurs validations) resterait sur un reste
        # obsolète et laisserait passer un dépassement du plafond d'agence (Phase 2 §3, M2).
        self.env['microfinance.fond.allocation'].invalidate_model(['reste_a_repartir_portefeuille'])
        self.env['microfinance.portfolio.allocation'].invalidate_model(['reste_a_repartir'])
        return True

    def action_cancel(self):
        self._check_own_agency_gestionnaire()
        Portfolio = self.env['microfinance.portfolio'].sudo().with_context(**{PORTFOLIO_ALLOCATION_TECHNICAL_CONTEXT: True})
        for repartition in self:
            if repartition.state == 'cancelled':
                continue
            if repartition.state == 'validated':
                rounding = repartition.currency_id.rounding
                updates = []
                for line in repartition.line_ids.filtered(lambda l: not float_is_zero(l.amount, precision_rounding=rounding)):
                    portfolio = line.portfolio_id
                    remaining = portfolio.amount_allocated - line.amount
                    # Une réallocation (ici : retrait via annulation) ne peut jamais descendre
                    # sous le fonds déjà utilisé par les crédits actifs de ce portefeuille
                    # (Phase 2 §3, 3e contrainte).
                    if float_compare(remaining, portfolio.montant_utilise, precision_rounding=rounding) < 0:
                        raise UserError(_(
                            "Annulation impossible : le portefeuille de « %(agent)s » a déjà "
                            "utilisé %(utilise)s (allocation %(alloc)s, part à retirer %(part)s)."
                        ) % {
                            'agent': portfolio.agent_id.display_name,
                            'utilise': portfolio.montant_utilise,
                            'alloc': portfolio.amount_allocated,
                            'part': line.amount,
                        })
                    updates.append((portfolio, remaining))
                for portfolio, remaining in updates:
                    Portfolio.browse(portfolio.id).amount_allocated = remaining
            repartition.state = 'cancelled'
            repartition.message_post(body=_('Répartition annulée.'))
        self.env['microfinance.fond.allocation'].invalidate_model(['reste_a_repartir_portefeuille'])
        self.env['microfinance.portfolio.allocation'].invalidate_model(['reste_a_repartir'])
        return True


class MicrofinancePortfolioAllocationLine(models.Model):
    """Part d'un portefeuille dans une répartition - historique en lecture seule une fois la
    répartition non brouillon (cf. _check_repartition_draft), traçable via mail.thread sur l'en-tête
    (qui/quand/combien dans le message posté par action_validate/action_cancel)."""
    _name = 'microfinance.portfolio.allocation.line'
    _description = "Part d'un portefeuille dans une répartition de fonds d'agence"
    _order = 'allocation_id, portfolio_id'

    allocation_id = fields.Many2one('microfinance.portfolio.allocation', string='Répartition', required=True, ondelete='cascade', index=True)
    portfolio_id = fields.Many2one(
        'microfinance.portfolio', string='Portefeuille', required=True, ondelete='restrict',
        domain="[('company_id', '=', parent.company_id)]",
    )
    currency_id = fields.Many2one(related='allocation_id.currency_id', readonly=True)
    percent = fields.Float(string='Part (%)', digits=(16, 4))
    amount = fields.Monetary(string='Montant')
    percent_ref = fields.Float(string='Part (%) de référence', digits=(16, 4), copy=True)
    amount_ref = fields.Monetary(string='Montant de référence', copy=True)

    # Champs d'historique (M4) : related + store=True, remplis une fois pour toutes à la création/
    # écriture de la ligne (l'en-tête devient readonly après validation, cf. _check_repartition_draft
    # - ces colonnes ne bougent donc plus), pour permettre filtres/regroupements/tri sans jointure
    # dans les vues "Historique des allocations" (section 8), sans nouveau modèle. validated_by/
    # validated_date réutilisent write_uid/write_date de l'en-tête (mis à jour par action_validate
    # au moment précis de la validation) - rien n'est inventé.
    fond_id = fields.Many2one(related='allocation_id.fond_id', store=True, readonly=True, string='Fonds de crédit')
    company_id = fields.Many2one(related='allocation_id.company_id', store=True, readonly=True, string='Agence')
    date = fields.Date(related='allocation_id.date', store=True, readonly=True, string='Date')
    state = fields.Selection(related='allocation_id.state', store=True, readonly=True, string='État')
    allocation_mode = fields.Selection(related='allocation_id.allocation_mode', store=True, readonly=True, string='Mode')
    agent_id = fields.Many2one(related='portfolio_id.agent_id', store=True, readonly=True, string='Agent')
    validated_by = fields.Many2one(related='allocation_id.write_uid', store=True, readonly=True, string='Validé par')
    validated_date = fields.Datetime(related='allocation_id.write_date', store=True, readonly=True, string='Validé le')

    _sql_constraints = [
        ('allocation_portfolio_unique', 'unique(allocation_id, portfolio_id)', 'Une seule ligne par portefeuille dans une répartition.'),
        ('percent_positive', 'check(percent >= 0)', 'La part (%) ne peut pas être négative.'),
        ('percent_max', 'check(percent <= 100)', 'La part (%) ne peut pas dépasser 100.'),
        ('amount_positive', 'check(amount >= 0)', 'Le montant ne peut pas être négatif.'),
    ]

    @api.constrains('portfolio_id', 'allocation_id')
    def _check_portfolio_company(self):
        for line in self:
            if line.portfolio_id.company_id != line.allocation_id.company_id:
                raise ValidationError(_(
                    "Le portefeuille « %(portfolio)s » n'appartient pas à l'agence de cette répartition."
                ) % {'portfolio': line.portfolio_id.display_name})

    @api.model
    def _amount_from_percent(self, base_amount, percent):
        currency = self.allocation_id.currency_id or self.env.company.currency_id
        return currency.round(base_amount * percent / 100.0)

    @api.model
    def _percent_from_amount(self, base_amount, amount):
        return (amount / base_amount * 100.0) if base_amount else 0.0

    @api.model
    def _check_percent_bound(self, allocation, portfolio, percent, amount, base):
        if float_compare(percent, 100.0, precision_digits=4) > 0:
            raise UserError(_(
                "Le montant alloué à « %(portfolio)s » (%(amount)s) dépasse à lui seul le reste à "
                "répartir du fonds de l'agence (%(base)s)."
            ) % {'portfolio': portfolio.display_name, 'amount': amount, 'base': base})

    def _percent_base(self, allocation):
        """Base du % : reste à répartir de l'agence en mode allocation (M2), montant à répartir
        de la répartition elle-même en mode partage (comportement historique inchangé)."""
        return allocation.reste_a_repartir if allocation.allocation_mode == 'allocation' else allocation.base_amount

    def _sync_from_allocation_mode(self):
        """Mode allocation (M2) seulement : recalcule, pour chaque ligne, le champ en lecture
        seule (montant ou %) à partir de l'autre selon input_type, sur la base du reste à répartir
        de l'agence - jamais de rééquilibrage entre lignes (contrairement à _rebalance_lines, propre
        au mode partage), chaque portefeuille est alloué indépendamment des autres (M2/M3)."""
        for line in self:
            allocation = line.allocation_id
            if allocation.allocation_mode != 'allocation':
                continue
            base = allocation.reste_a_repartir or 0.0
            if allocation.input_type == 'montant':
                line.percent = line._percent_from_amount(base, line.amount)
            else:
                line.amount = line._amount_from_percent(base, line.percent)
            line.percent_ref, line.amount_ref = line.percent, line.amount

    def _sync_header_base_amount(self):
        for allocation in self.mapped('allocation_id'):
            if allocation.allocation_mode == 'allocation':
                allocation.base_amount = sum(allocation.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['microfinance.portfolio.allocation']._check_own_agency_gestionnaire()
        for vals in vals_list:
            allocation = self.env['microfinance.portfolio.allocation'].browse(vals.get('allocation_id'))
            base = self._percent_base(allocation)
            if 'amount' in vals and 'percent' not in vals:
                vals['percent'] = self._percent_from_amount(base, vals['amount'])
            elif 'percent' in vals and 'amount' not in vals:
                vals['amount'] = self._amount_from_percent(base, vals['percent'])
            vals['percent_ref'] = vals.get('percent', 0.0)
            vals['amount_ref'] = vals.get('amount', 0.0)
            if allocation.allocation_mode == 'allocation':
                self._check_percent_bound(
                    allocation, self.env['microfinance.portfolio'].browse(vals.get('portfolio_id')),
                    vals['percent_ref'], vals['amount_ref'], base)
        lines = super().create(vals_list)
        lines._check_repartition_draft()
        lines._check_total_if_direct()
        lines._sync_header_base_amount()
        return lines

    def write(self, vals):
        self.env['microfinance.portfolio.allocation']._check_own_agency_gestionnaire()
        self._check_repartition_draft()
        if 'amount' in vals or 'percent' in vals:
            for line in self:
                base = self._percent_base(line.allocation_id)
                line_vals = dict(vals)
                if 'percent' not in vals:
                    line_vals['percent'] = self._percent_from_amount(base, vals['amount'])
                elif 'amount' not in vals:
                    line_vals['amount'] = self._amount_from_percent(base, vals['percent'])
                line_vals['percent_ref'] = line_vals['percent']
                line_vals['amount_ref'] = line_vals['amount']
                if line.allocation_id.allocation_mode == 'allocation':
                    self._check_percent_bound(
                        line.allocation_id, line.portfolio_id, line_vals['percent'], line_vals['amount'], base)
                super(MicrofinancePortfolioAllocationLine, line).write(line_vals)
            self._check_total_if_direct()
            self._sync_header_base_amount()
            return True
        return super().write(vals)

    def _check_total_if_direct(self):
        if not self.env.context.get('portfolio_allocation_defer_check'):
            self.mapped('allocation_id')._check_total_within_base()

    def unlink(self):
        self.env['microfinance.portfolio.allocation']._check_own_agency_gestionnaire()
        self._check_repartition_draft()
        return super().unlink()

    def _check_repartition_draft(self):
        if any(line.allocation_id.state != 'draft' for line in self):
            raise UserError(_("Les parts d'une répartition validée ou annulée ne sont plus modifiables."))
