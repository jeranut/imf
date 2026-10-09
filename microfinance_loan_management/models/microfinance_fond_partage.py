# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
from decimal import Decimal, ROUND_FLOOR

from odoo.tools import float_compare, float_is_zero, float_round

from .microfinance_fond_allocation import ALLOCATION_TECHNICAL_CONTEXT

# Champs techniques de liaison comptable d'une part, écrits par la validation/génération même d'un partage
# déjà validé (microfinance_fond_liaison.py) : exemptés du verrou « partage en brouillon ».
LIAISON_TECHNICAL_FIELDS = {'hq_move_id', 'agency_move_id', 'liaison_note'}


def largest_remainder(total, weights, rounding, priority=None):
    """Répartit `total` au prorata de `weights` par la méthode du plus fort reste, à la précision `rounding`
    de la devise : chaque part est arrondie par défaut, puis les unités restantes vont aux plus grosses
    parties fractionnaires. La somme des parts est EXACTEMENT `total`. `priority` (liste de nombres, plus petit
    d'abord) départage les restes égaux. Retourne une liste de montants alignée sur `weights`."""
    if not weights:
        return []
    unit = Decimal(str(rounding))
    units = int((Decimal(str(total)) / unit).to_integral_value())
    weights = [Decimal(str(max(w, 0.0))) for w in weights]
    sum_w = sum(weights)
    if sum_w <= 0:
        weights, sum_w = [Decimal(1)] * len(weights), Decimal(len(weights))
    quotas = [Decimal(units) * w / sum_w for w in weights]
    floors = [int(q.to_integral_value(rounding=ROUND_FLOOR)) for q in quotas]
    left = units - sum(floors)
    priority = priority or list(range(len(weights)))
    order = sorted(range(len(weights)), key=lambda i: (-(quotas[i] - floors[i]), priority[i], i))
    for i in order[:left]:
        floors[i] += 1
    return [float(Decimal(f) * unit) for f in floors]


class MicrofinanceFondPartage(models.Model):
    """Partage d'un fonds multi-agences entre les agences (société mère incluse). Cumulatif : un
    partage validé ajoute à l'allocation existante de chaque agence, jamais de re-partage
    destructif. La validation génère aussi les écritures de liaison siège/agence (voir
    microfinance_fond_liaison.py)."""
    _name = 'microfinance.fond.partage'
    _description = 'Partage de fonds entre agences'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'microfinance.fond.parent.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    fond_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit', required=True, tracking=True,
        ondelete='restrict', domain="[('scope', '=', 'multi_company'), ('active', '=', True)]",
    )
    company_id = fields.Many2one(
        'res.company', string='Société mère', required=True, readonly=True, copy=False, index=True,
        default=lambda self: self.env['res.company']._get_microfinance_parent() or self.env.company,
        help="Société qui a établi le partage (la mère). Cloisonne la visibilité : les agences ne "
             "voient pas les partages, seulement leur allocation.",
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    currency_id = fields.Many2one(related='fond_id.currency_id', store=True, readonly=True)
    base_amount = fields.Monetary(
        string='Montant à partager', required=True, tracking=True,
        help="Pré-rempli avec le reste partageable du fonds ; ne peut pas le dépasser.",
    )
    reste_partageable = fields.Monetary(
        string='Reste partageable du fonds', related='fond_id.reste_partageable', readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('validated', 'Validé'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', required=True, copy=False, tracking=True)
    line_ids = fields.One2many('microfinance.fond.partage.line', 'partage_id', string='Parts par agence', copy=True)
    total_percent = fields.Float(string='Total %', compute='_compute_totals', digits=(16, 4))
    total_amount = fields.Monetary(string='Total réparti', compute='_compute_totals')
    reste_a_partager = fields.Monetary(string='Reste à répartir', compute='_compute_totals')

    @api.depends('base_amount', 'line_ids.percent', 'line_ids.amount')
    def _compute_totals(self):
        for partage in self:
            partage.total_percent = sum(partage.line_ids.mapped('percent'))
            partage.total_amount = sum(partage.line_ids.mapped('amount'))
            partage.reste_a_partager = partage.base_amount - partage.total_amount

    @api.model
    def _default_line_vals(self):
        """Une ligne à 0 par agence (toute société avec un code agence), mère incluse."""
        companies = self.env['res.company'].sudo().search([('agency_code', '!=', False)], order='name')
        return [{'company_id': company.id, 'percent': 0.0, 'amount': 0.0} for company in companies]

    @api.onchange('fond_id')
    def _onchange_fond_id(self):
        if self.fond_id:
            self.base_amount = self.fond_id.reste_partageable
        if not self.line_ids:
            self.line_ids = [Command.create(vals) for vals in self._default_line_vals()]
        self._onchange_base_amount()

    @api.onchange('base_amount')
    def _onchange_base_amount(self):
        # Le pourcentage reste la référence : un changement de base recalcule les montants.
        for line in self.line_ids:
            line.amount = line._amount_from_percent(self.base_amount, line.percent)
            line.percent_ref, line.amount_ref = line.percent, line.amount

    @api.onchange('line_ids')
    def _onchange_line_ids_rebalance(self):
        """Équilibrage automatique : un @api.onchange sur la ligne ne peut pas modifier ses
        lignes sœurs, on le fait donc ici, sur le parent. La ligne éditée est celle dont
        percent/amount diffère de sa référence (percent_ref/amount_ref = dernières valeurs
        équilibrées). Se déclenche à la sortie de la cellule/ligne, pas à chaque frappe."""
        self._rebalance_lines()

    def _rebalance_lines(self):
        self.ensure_one()
        lines = self.line_ids
        if not lines or self.state != 'draft':
            return
        currency = self.currency_id or self.env.company.currency_id
        currency_rounding = currency.rounding
        base = self.base_amount or 0.0
        rounding = self._share_rounding(base)
        edited = amount_edited = None
        for line in lines:
            a_changed = float_compare(line.amount, line.amount_ref, precision_rounding=currency_rounding) != 0
            p_changed = float_compare(line.percent, line.percent_ref, precision_digits=4) != 0
            if a_changed or p_changed:
                # les deux ont changé : le montant prime
                edited, amount_edited = line, a_changed
                break
        if not edited:
            return
        others = lines - edited
        if amount_edited and base > 0:
            amount = min(max(edited.amount, 0.0), base)
            percent = min(float_round(amount / base * 100.0, precision_digits=4), 100.0)
        elif amount_edited:
            # base = 0 : le calcul se fait en pourcentages, les montants restent à 0
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
            amounts = largest_remainder(remaining_amount, weights, rounding, self._hq_priority(others))
            pcts = largest_remainder(remaining_pct, weights, 0.0001)
            for other, other_pct, other_amount in zip(others, pcts, amounts):
                other.percent = other_pct
                other.amount = other_amount
        for line in lines:
            line.percent_ref, line.amount_ref = line.percent, line.amount

    def _share_rounding(self, total=None):
        """Pas des parts : l'unité d'arrondi des virements de la société mère (1 = Ariary entier) si le montant
        partagé en est un multiple, sinon la précision de la monnaie (la somme des parts doit rester exacte)."""
        currency_rounding = (self.currency_id or self.env.company.currency_id).rounding
        unit = self.company_id.microfinance_transfer_rounding_unit or 0.0
        total = self.base_amount if total is None else total
        if unit > currency_rounding and float_is_zero(total - unit * round(total / unit),
                                                      precision_rounding=currency_rounding):
            return unit
        return currency_rounding

    def _hq_priority(self, lines):
        """Départage des restes égaux : la part du siège d'abord, puis l'ordre des lignes."""
        hq = self.company_id
        return [0 if line.company_id == hq else 1 for line in lines]

    def _normalize_amounts(self):
        """Ramène la somme des parts à EXACTEMENT le montant partagé (plus fort reste, au prorata des montants
        saisis). Écart toléré : un quantum monétaire par ligne ; au-delà, la répartition est incomplète."""
        self.ensure_one()
        rounding = self._share_rounding()
        lines = self.line_ids
        gap = self.base_amount - sum(lines.mapped('amount'))
        if float_is_zero(gap, precision_rounding=rounding):
            return
        if abs(gap) > rounding * len(lines) + rounding / 2.0:
            raise UserError(_(
                'La répartition est incomplète : %(reparti)s réparti sur %(base)s à partager (écart de %(ecart)s).'
            ) % {'reparti': sum(lines.mapped('amount')), 'base': self.base_amount, 'ecart': float_round(gap, precision_rounding=rounding)})
        amounts = largest_remainder(self.base_amount, lines.mapped('amount'), rounding, self._hq_priority(lines))
        for line, amount in zip(lines, amounts):
            line.with_context(fond_partage_defer_check=True).write({'amount': amount})

    @api.constrains('base_amount')
    def _check_base_amount(self):
        for partage in self:
            if partage.base_amount <= 0:
                raise ValidationError(_('Le montant à partager doit être strictement positif.'))

    @api.constrains('base_amount', 'line_ids')
    def _check_total_within_base(self):
        # Contrôle au niveau du partage (et non de chaque ligne) : lors d'un enregistrement du
        # formulaire, les lignes sont écrites une à une et le total intermédiaire peut dépasser
        # la base avant que les autres lignes ne soient rééquilibrées.
        for partage in self:
            if float_compare(sum(partage.line_ids.mapped('amount')), partage.base_amount,
                             precision_rounding=partage.currency_id.rounding) > 0:
                raise ValidationError(_('Le total réparti dépasse le montant à partager.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_parent_only()
        for vals in vals_list:
            if vals.get('name', 'Nouveau') in (False, '', 'Nouveau'):
                vals['name'] = self.env['ir.sequence'].next_by_code('microfinance.fond.partage') or 'Nouveau'
            if not vals.get('line_ids'):
                vals['line_ids'] = [Command.create(v) for v in self._default_line_vals()]
        partages = super(MicrofinanceFondPartage, self.with_context(fond_partage_defer_check=True)).create(vals_list)
        return partages.with_context(fond_partage_defer_check=False)

    def write(self, vals):
        self._check_parent_only()
        if set(vals) - {'state'} and any(p.state != 'draft' for p in self):
            raise UserError(_('Seul un partage en brouillon peut être modifié.'))
        if 'base_amount' in vals and 'line_ids' not in vals:
            # Le pourcentage reste la référence : les montants sont recalculés dans la même
            # écriture (commandes), pour que le contrôle du total voie la base et les lignes à jour.
            for partage in self:
                percents = partage.line_ids.mapped('percent')
                rounding = partage._share_rounding(vals['base_amount'])
                # Les pourcentages ne totalisent pas forcément 100 (brouillon en cours de saisie) : on répartit
                # la part de la base qu'ils représentent, exactement (plus fort reste).
                share = float_round(vals['base_amount'] * sum(percents) / 100.0, precision_rounding=rounding)
                new_amounts = (largest_remainder(share, percents, rounding, partage._hq_priority(partage.line_ids))
                               if sum(percents) > 0 else [0.0] * len(percents))
                line_updates = [Command.update(line.id, {'amount': amount, 'percent': line.percent})
                                for line, amount in zip(partage.line_ids, new_amounts)]
                super(MicrofinanceFondPartage, partage.with_context(fond_partage_defer_check=True)).write(
                    dict(vals, line_ids=line_updates))
            return True
        return super(MicrofinanceFondPartage, self.with_context(fond_partage_defer_check=True)).write(vals)

    def unlink(self):
        self._check_parent_only()
        if any(p.state == 'validated' for p in self):
            raise UserError(_('Un partage validé ne peut pas être supprimé : annulez-le d\'abord.'))
        return super().unlink()

    def action_partager_egalement(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Seul un partage en brouillon peut être modifié.'))
        if self.base_amount <= 0:
            raise UserError(_('Renseignez d\'abord un montant à partager supérieur à zéro.'))
        lines = self.line_ids
        if not lines:
            raise UserError(_('Aucune agence à répartir.'))
        rounding = self._share_rounding()
        amounts = largest_remainder(self.base_amount, [1.0] * len(lines), rounding, self._hq_priority(lines))
        pcts = largest_remainder(100.0, [1.0] * len(lines), 0.0001, self._hq_priority(lines))
        for line, amount, pct in zip(lines, amounts, pcts):
            line.write({'percent': pct, 'amount': amount})
        return True

    def _percent_total_ok(self):
        self.ensure_one()
        if not self.base_amount:
            return False
        # Tolérance : 0,01 point + quantum d'arrondi monétaire de chaque ligne.
        tolerance = 0.01 + 100.0 * self._share_rounding() * len(self.line_ids) / self.base_amount
        return abs(self.total_percent - 100.0) <= tolerance

    def action_validate(self):
        self._check_parent_only()
        Allocation = self.env['microfinance.fond.allocation'].sudo().with_context(**{ALLOCATION_TECHNICAL_CONTEXT: True})
        for partage in self:
            if partage.state != 'draft':
                raise UserError(_('Seul un partage en brouillon peut être validé.'))
            rounding = partage.currency_id.rounding
            if float_compare(partage.base_amount, partage.fond_id.reste_partageable, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'Le montant à partager (%(base)s) dépasse le reste partageable du fonds « %(fond)s » (%(reste)s).'
                ) % {'base': partage.base_amount, 'fond': partage.fond_id.name, 'reste': partage.fond_id.reste_partageable})
            partage._normalize_amounts()
            if not partage._percent_total_ok():
                raise UserError(_(
                    'La répartition doit totaliser 100 %% du montant à partager (actuellement %.4f %%).'
                ) % partage.total_percent)
            details = []
            for line in partage.line_ids.filtered(lambda l: not float_is_zero(l.amount, precision_rounding=rounding)):
                allocation = Allocation.search([
                    ('fond_id', '=', partage.fond_id.id), ('company_id', '=', line.company_id.id)], limit=1)
                if allocation:
                    allocation.amount_allocated += line.amount
                else:
                    Allocation.create({
                        'fond_id': partage.fond_id.id, 'company_id': line.company_id.id,
                        'amount_allocated': line.amount,
                    })
                details.append('%s : %s (%.4f %%)' % (line.company_id.name, line.amount, line.percent))
            partage.fond_id.allocation_required = True
            partage.state = 'validated'
            partage.message_post(body=_('Partage validé : %s') % ' ; '.join(details))
        return True

    def action_cancel(self):
        self._check_parent_only()
        Allocation = self.env['microfinance.fond.allocation'].sudo().with_context(**{ALLOCATION_TECHNICAL_CONTEXT: True})
        for partage in self:
            if partage.state == 'cancelled':
                continue
            if partage.state == 'validated':
                rounding = partage.currency_id.rounding
                updates = []
                for line in partage.line_ids.filtered(lambda l: not float_is_zero(l.amount, precision_rounding=rounding)):
                    allocation = Allocation.search([
                        ('fond_id', '=', partage.fond_id.id), ('company_id', '=', line.company_id.id)], limit=1)
                    remaining = (allocation.amount_allocated if allocation else 0.0) - line.amount
                    if not allocation or float_compare(remaining, allocation.montant_utilise, precision_rounding=rounding) < 0:
                        raise UserError(_(
                            "Annulation impossible : l'agence « %(agence)s » a déjà utilisé %(utilise)s sur ce fonds "
                            "(allocation %(alloc)s, part à retirer %(part)s)."
                        ) % {
                            'agence': line.company_id.name,
                            'utilise': allocation.montant_utilise if allocation else 0.0,
                            'alloc': allocation.amount_allocated if allocation else 0.0,
                            'part': line.amount,
                        })
                    updates.append((allocation, remaining))
                for allocation, remaining in updates:
                    if float_is_zero(remaining, precision_rounding=rounding):
                        allocation.unlink()
                    else:
                        allocation.amount_allocated = remaining
            partage.state = 'cancelled'
            partage.message_post(body=_('Partage annulé.'))
        return True


class MicrofinanceFondPartageLine(models.Model):
    _name = 'microfinance.fond.partage.line'
    _description = 'Part d\'agence dans un partage de fonds'
    _inherit = ['microfinance.fond.parent.mixin']
    _order = 'partage_id, company_id'

    partage_id = fields.Many2one('microfinance.fond.partage', string='Partage', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, ondelete='restrict',
        domain="[('agency_code', '!=', False)]",
    )
    currency_id = fields.Many2one(related='partage_id.currency_id', readonly=True)
    percent = fields.Float(string='Part (%)', digits=(16, 4))
    amount = fields.Monetary(string='Montant')
    # Champs techniques (invisibles) : dernières valeurs équilibrées, servent à repérer la ligne
    # éditée dans MicrofinanceFondPartage._rebalance_lines().
    percent_ref = fields.Float(string='Part (%) de référence', digits=(16, 4), copy=True)
    amount_ref = fields.Monetary(string='Montant de référence', copy=True)

    _sql_constraints = [
        ('partage_company_unique', 'unique(partage_id, company_id)', 'Une seule ligne par agence dans un partage.'),
        ('percent_positive', 'check(percent >= 0)', 'La part (%) ne peut pas être négative.'),
        ('amount_positive', 'check(amount >= 0)', 'Le montant ne peut pas être négatif.'),
    ]

    @api.model
    def _amount_from_percent(self, base_amount, percent):
        partage = self.partage_id
        currency = partage.currency_id or self.env.company.currency_id
        rounding = partage._share_rounding(base_amount) if partage else currency.rounding
        return float_round(base_amount * percent / 100.0, precision_rounding=rounding)

    @api.model
    def _percent_from_amount(self, base_amount, amount):
        return (amount / base_amount * 100.0) if base_amount else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        self._check_parent_only()
        for vals in vals_list:
            # Un seul des deux fourni (API, import) : on dérive l'autre. Les deux fournis (retour
            # d'onchange du formulaire) sont déjà cohérents.
            partage = self.env['microfinance.fond.partage'].browse(vals.get('partage_id'))
            if 'amount' in vals and 'percent' not in vals:
                vals['percent'] = self._percent_from_amount(partage.base_amount, vals['amount'])
            elif 'percent' in vals and 'amount' not in vals:
                vals['amount'] = self._amount_from_percent(partage.base_amount, vals['percent'])
            # références alignées sur les valeurs finales
            vals['percent_ref'] = vals.get('percent', 0.0)
            vals['amount_ref'] = vals.get('amount', 0.0)
        lines = super().create(vals_list)
        lines._check_partage_draft()
        lines._check_total_if_direct()
        return lines

    def write(self, vals):
        if set(vals) <= LIAISON_TECHNICAL_FIELDS:
            return super().write(vals)
        self._check_parent_only()
        self._check_partage_draft()
        if 'amount' in vals or 'percent' in vals:
            for line in self:
                line_vals = dict(vals)
                if 'percent' not in vals:
                    line_vals['percent'] = self._percent_from_amount(line.partage_id.base_amount, vals['amount'])
                elif 'amount' not in vals:
                    line_vals['amount'] = self._amount_from_percent(line.partage_id.base_amount, vals['percent'])
                line_vals['percent_ref'] = line_vals['percent']
                line_vals['amount_ref'] = line_vals['amount']
                super(MicrofinanceFondPartageLine, line).write(line_vals)
            self._check_total_if_direct()
            return True
        return super().write(vals)

    def _check_total_if_direct(self):
        # Écriture Python directe : contrôle immédiat. Depuis l'enregistrement du partage, le
        # contrôle est différé à la fin de son write/create (MicrofinanceFondPartage._check_total_within_base).
        if not self.env.context.get('fond_partage_defer_check'):
            self.mapped('partage_id')._check_total_within_base()

    def unlink(self):
        self._check_parent_only()
        self._check_partage_draft()
        return super().unlink()

    def _check_partage_draft(self):
        # Contournement volontaire pour la validation du partage elle-même : seule l'en-tête
        # change d'état, jamais les lignes.
        if any(line.partage_id.state != 'draft' for line in self):
            raise UserError(_('Les parts d\'un partage validé ou annulé ne sont plus modifiables.'))
