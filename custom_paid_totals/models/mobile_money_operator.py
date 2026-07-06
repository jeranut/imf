# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.safe_eval import safe_eval


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    paid_totals_treasury_action_id = fields.Many2one(
        'ir.actions.act_window',
        string='Action Trésorerie',
        copy=False,
        readonly=True,
        ondelete='set null',
    )
    paid_totals_treasury_menu_id = fields.Many2one(
        'ir.ui.menu',
        string='Menu Trésorerie',
        copy=False,
        readonly=True,
        ondelete='set null',
    )


class MobileMoneyOperator(models.Model):
    _name = 'mobile.money.operator'
    _description = 'Configuration d’un journal de trésorerie'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Nom', required=True)
    code = fields.Char(string='Code', required=True)
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal bancaire',
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        check_company=True,
    )
    journal_account_id = fields.Many2one(
        'account.account',
        string='Compte comptable',
        related='journal_id.default_account_id',
        store=True,
        check_company=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    treasury_action_id = fields.Many2one(
        'ir.actions.act_window',
        string='Action du journal',
        copy=False,
        readonly=True,
        ondelete='set null',
    )
    treasury_menu_id = fields.Many2one(
        'ir.ui.menu',
        string='Menu du journal',
        copy=False,
        readonly=True,
        ondelete='set null',
    )
    today_balance_state = fields.Selection(
        [
            ('no_movement', 'Aucun mouvement'),
            ('has_movement', 'Mouvement en cours'),
            ('closed', 'Clôturé'),
        ],
        string='État du jour',
        compute='_compute_today_balance_state',
        store=False,
    )

    _sql_constraints = [
        (
            'unique_code_company',
            'unique(code, company_id)',
            'Le code du journal doit être unique par société.',
        ),
        (
            'unique_journal_company',
            'unique(journal_id, company_id)',
            'Un journal bancaire ne peut être configuré qu’une seule fois par société.',
        ),
    ]

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'company_id' in fields_list:
            defaults['company_id'] = self.env.company.id
        return defaults

    @api.model
    def _resolve_for_journal(self, journal_id, company_id):
        """Résout l'opérateur Mobile Money actif correspondant à un journal
        bancaire, pour router un paiement ou une clôture vers le bon
        account.daily.balance.mobile. Source de vérité unique, réutilisée
        partout où ce lookup journal → opérateur est nécessaire."""
        return self.search([
            ('journal_id', '=', journal_id),
            ('company_id', '=', company_id),
            ('active', '=', True),
        ], limit=1)

    @api.depends()
    def _compute_today_balance_state(self):
        """Non stocké : recalculé à chaque affichage à partir de la date du
        jour (fields.Date.context_today), pas d'un champ figé — repasse donc
        naturellement à 'no_movement' le lendemain sans job ni recompute
        manuel."""
        today = fields.Date.context_today(self)
        balances = self.env['account.daily.balance.mobile'].search([
            ('operator_id', 'in', self.ids),
            ('company_id', 'in', self.company_id.ids),
            ('date', '=', today),
        ])
        balance_by_operator = {balance.operator_id.id: balance for balance in balances}
        for operator in self:
            balance = balance_by_operator.get(operator.id)
            if not balance:
                operator.today_balance_state = 'no_movement'
            elif balance.etats == 'cloturer':
                operator.today_balance_state = 'closed'
            elif balance.total_credit > 0 or balance.total_debit > 0:
                operator.today_balance_state = 'has_movement'
            else:
                operator.today_balance_state = 'no_movement'

    @api.model
    def _check_sync_treasury_menu_access(self):
        allowed_groups = (
            'custom_paid_totals.group_paid_totals_manager',
            'account.group_account_manager',
            'base.group_system',
        )
        if not any(self.env.user.has_group(group) for group in allowed_groups):
            raise AccessError(_(
                "Seuls les gestionnaires Trésorerie, les gestionnaires comptables ou les administrateurs peuvent synchroniser les menus journaux."
            ))

    @api.model
    def _get_sync_company_ids(self):
        if self.env.company.id not in self.env.user.company_ids.ids:
            return []
        return [self.env.company.id]

    @api.model
    def _is_synced_treasury_action(self, action):
        if not action or action._name != 'ir.actions.act_window':
            return False
        try:
            context = safe_eval(action.context or '{}')
        except Exception:
            context = {}
        return bool(context.get('paid_totals_journal_menu_sync'))

    @api.model
    def _is_custom_dynamic_journal_menu(self, menu):
        action = menu.action
        if not action or action._name != 'ir.actions.act_window':
            return False
        if menu.custom_paid_totals_dynamic_journal_menu or self._is_synced_treasury_action(action):
            return True
        return action.res_model in (
            'account.daily.balance.mobile',
            'account.daily.balance.mobile.line',
            'account.daily.balance.line',
        )

    @api.model
    def _cleanup_dynamic_journal_menus(self):
        parent_menu = self.env.ref('custom_paid_totals.menu_paid_totals_list')
        menus = self.env['ir.ui.menu'].sudo().with_context(active_test=False).search([
            ('parent_id', '=', parent_menu.id),
        ]).filtered(lambda menu: self._is_custom_dynamic_journal_menu(menu))
        active_menus = menus.filtered('active')
        if active_menus:
            active_menus.write({'active': False})
        self.env['ir.ui.menu'].clear_caches()
        return len(active_menus)

    @api.model
    def _sync_all_treasury_menus(self):
        self._cleanup_dynamic_journal_menus()
        return True

    @api.model
    def action_cleanup_dynamic_journal_menus(self):
        self._check_sync_treasury_menu_access()
        cleaned = self.sudo()._cleanup_dynamic_journal_menus()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Nettoyage terminé'),
                'message': _(
                    "Menus journaux dynamiques nettoyés : %(count)s désactivés.",
                    count=cleaned,
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.model
    def action_sync_treasury_journal_menus(self):
        return self.action_cleanup_dynamic_journal_menus()

    def _sync_treasury_menu(self):
        return True

    def action_open_treasury_journal(self):
        self.ensure_one()
        company = self.env.company
        journal = self.journal_id
        return {
            'type': 'ir.actions.act_window',
            'name': journal.display_name or self.display_name,
            'res_model': 'account.daily.balance.mobile',
            'view_mode': 'tree,form',
            'domain': [
                ('journal_id', '=', journal.id),
                ('company_id', '=', company.id),
            ],
            'context': {
                'default_journal_id': journal.id,
                'default_operator_id': self.id,
                'default_company_id': company.id,
                'allowed_company_ids': [company.id],
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_treasury_menu()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'journal_id', 'company_id', 'active'} & set(vals):
            self._sync_treasury_menu()
        return result

    def unlink(self):
        menus = self.mapped('treasury_menu_id').sudo()
        actions = self.mapped('treasury_action_id').sudo()
        result = super().unlink()
        menus.unlink()
        actions.unlink()
        return result
