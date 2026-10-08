# -*- coding: utf-8 -*-
"""Origine du fonds (privé / public) et compte passif dédié, créé automatiquement.

Chaque fonds a son propre compte de dette envers le bailleur, dans la société du fonds :
  privé  -> 240101, 240102, ... (classe 240xxx)
  public -> 250101, 250102, ... (classe 250xxx)
Numérotation séquentielle par société. Le compte est créé à la création du fonds (ou à l'activation du
grand livre) et reste figé dès qu'une écriture existe dessus. Plus aucun repli sur le compte par défaut
de la société : un fonds sans compte est refusé à la validation d'une contribution.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

ORIGIN_BASES = {'prive': 240100, 'public': 250100}


class MicrofinanceFondCredit(models.Model):
    _inherit = 'microfinance.fond.credit'

    origine = fields.Selection([
        ('prive', 'Privé'),
        ('public', 'Public'),
    ], string='Origine du fonds', required=True, default='prive', tracking=True,
        help="Détermine la classe du compte passif dédié au fonds : 240xxx pour un fonds privé, 250xxx pour un "
             "fonds public. Modifiable tant qu'aucune contribution validée n'existe ; le compte dédié est alors "
             "renuméroté dans l'autre classe.")
    account_id = fields.Many2one(
        default=False,
        help="Compte passif dédié au fonds (dette envers le bailleur), créé automatiquement selon l'origine du "
             "fonds, dans la société du fonds. Non modifiable dès qu'une écriture existe dessus.")
    account_auto = fields.Boolean(
        string='Compte créé automatiquement', readonly=True, copy=False,
        help="Vrai si le compte du fonds a été créé par le module (donc renumérotable tant qu'il est vide).")

    has_posted_contribution = fields.Boolean(compute='_compute_has_posted_contribution')

    def _compute_has_posted_contribution(self):
        for fond in self:
            fond.has_posted_contribution = bool(fond.id and fond._has_posted_contribution())

    # ------------------------------------------------------------------ neutralisation du repli société
    def _default_account_id(self):
        return self.env['account.account']

    @api.model
    def _get_default_account_id(self, company):
        return self.env['account.account']

    @api.onchange('scope', 'company_id')
    def _onchange_scope_account_domain(self):
        # Domaine seulement : le compte n'est plus pré-rempli depuis la société.
        domain = [('account_type', 'in', ('liability_current', 'liability_non_current', 'equity'))]
        if self.scope == 'single_company' and self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        return {'domain': {'account_id': domain}}

    # ------------------------------------------------------------------ compte dédié
    @api.model
    def _company_for_vals(self, vals):
        """Société qui portera le compte : celle du fonds, ou la société mère pour un fonds multi-agences."""
        Company = self.env['res.company']
        if vals.get('scope') == 'multi_company':
            return Company._get_microfinance_parent() or self.env.company
        if vals.get('company_id'):
            return Company.browse(vals['company_id'])
        return self.env.company

    @api.model
    def _next_origin_code(self, company, origine):
        """Prochain code libre de la classe 240xxx / 250xxx dans `company` (premier code : 240101 / 250101)."""
        base = ORIGIN_BASES[origine]
        prefix = str(base)[:3]
        self.env.cr.execute(
            "SELECT code FROM account_account WHERE company_id = %s AND code ~ %s", (company.id, '^%s[0-9]{3}$' % prefix))
        used = [int(row[0]) for row in self.env.cr.fetchall()]
        nxt = max([base] + used) + 1
        if nxt >= int(prefix) * 1000 + 1000:
            raise UserError(_("Plus de numéro disponible dans la classe %sxxx de la société « %s ».") % (prefix, company.name))
        return str(nxt)

    @api.model
    def _create_origin_account(self, company, origine, fond_code):
        company = company.sudo()
        if not company:
            raise UserError(_("Société du fonds introuvable : désignez la société mère dans les paramètres."))
        return self.env['account.account'].sudo().with_company(company).create({
            'code': self._next_origin_code(company, origine),
            'name': _('Fonds - %s') % fond_code,
            'account_type': 'liability_current',
            'reconcile': False,
            'company_id': company.id,
        })

    def _account_has_entries(self):
        self.ensure_one()
        if not self.account_id:
            return False
        return bool(self.env['account.move.line'].sudo().search_count([('account_id', '=', self.account_id.id)], limit=1))

    def _has_posted_contribution(self):
        self.ensure_one()
        return bool(self.sudo().contribution_ids.filtered(lambda c: c.state == 'posted'))

    def _ensure_origin_account(self):
        """Crée le compte dédié des fonds qui passent au grand livre sans compte (idempotent)."""
        for fond in self.filtered(lambda f: f.passer_gl and not f.account_id):
            account = self._create_origin_account(fond._fund_company(), fond.origine, fond.code)
            fond.write({'account_id': account.id, 'account_auto': True})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'Nouveau') in (False, '', 'Nouveau'):
                vals['code'] = self.env['ir.sequence'].next_by_code('microfinance.fond.credit') or 'Nouveau'
            if vals.get('passer_gl', True) and not vals.get('account_id'):
                account = self._create_origin_account(
                    self._company_for_vals(vals), vals.get('origine') or 'prive', vals['code'])
                vals['account_id'] = account.id
                vals['account_auto'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'account_id' in vals:
            for fond in self:
                if vals['account_id'] != fond.account_id.id and fond._account_has_entries():
                    raise UserError(_(
                        "Le compte du fonds « %s » ne peut plus être modifié : des écritures existent dessus."
                    ) % fond.name)
        if 'origine' in vals:
            for fond in self:
                if vals['origine'] == fond.origine:
                    continue
                if fond._has_posted_contribution() or fond._account_has_entries():
                    raise UserError(_(
                        "L'origine du fonds « %s » ne peut plus être modifiée : une contribution est déjà validée."
                    ) % fond.name)
        res = super().write(vals)
        if 'origine' in vals:
            for fond in self.filtered(lambda f: f.account_auto and f.account_id):
                # Compte vide créé par le module : on le renumérote dans la classe de la nouvelle origine.
                base = str(ORIGIN_BASES[fond.origine])[:3]
                if not fond.account_id.code.startswith(base):
                    fond.account_id.sudo().code = self._next_origin_code(fond.account_id.company_id, fond.origine)
        if vals.get('passer_gl'):
            self._ensure_origin_account()
        return res
