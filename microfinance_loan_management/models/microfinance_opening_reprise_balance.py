# -*- coding: utf-8 -*-
"""Contrôle de concordance entre la balance d'ouverture et le détail repris (crédits ici, épargne via le point d'extension
_reprise_groups() du module épargne). Bloquant à la validation seulement si une reprise existe pour la balance ; sinon
simple avertissement dans le fil de discussion si les comptes de crédit/épargne portent un solde."""
from collections import defaultdict

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_amount

CREDIT_CODES_PARAM = 'microfinance.reprise_credit_codes'
CREDIT_CODES_DEFAULT = '203001,203002'
SAVINGS_CODES_PARAM = 'microfinance.reprise_savings_codes'
SAVINGS_CODES_DEFAULT = '213001,213002,213003'


class MicrofinanceOpeningBalance(models.Model):
    _inherit = 'microfinance.opening.balance'

    reprise_concordance_html = fields.Html(string='Concordance avec la reprise de portefeuille',
                                           compute='_compute_reprise_concordance_html', sanitize=False)

    # ------------------------------------------------------------------ données
    def _reprise_codes(self, param, default):
        value = self.env['ir.config_parameter'].sudo().get_param(param) or default
        return [code.strip() for code in value.split(',') if code.strip()]

    def _reprise_has_data(self):
        self.ensure_one()
        return bool(self.env['microfinance.loan'].sudo().search_count([('opening_balance_id', '=', self.id)]))

    def _reprise_groups(self):
        """Groupes de comptes à rapprocher : {'label', 'detail': {compte: montant}, 'codes', 'sign'} ; sign = +1 si le
        solde normal est au débit (crédits), -1 s'il est au crédit (épargne)."""
        self.ensure_one()
        detail = defaultdict(float)
        for loan in self.env['microfinance.loan'].sudo().search([('opening_balance_id', '=', self.id)]):
            account = loan.product_id._get_account('principal', loan.partner_id)
            detail[account] += loan._get_principal_outstanding()
        return [{'label': _("Principal des crédits"), 'detail': detail, 'sign': 1,
                 'codes': self._reprise_codes(CREDIT_CODES_PARAM, CREDIT_CODES_DEFAULT)}]

    def _reprise_concordance(self):
        """Lignes {groupe, compte, détail, balance, écart} ; écart = montant de la balance − détail repris."""
        self.ensure_one()
        lines = []
        for group in self._reprise_groups():
            sign = group['sign']
            balance_lines = self.line_ids.filtered(lambda l: l.account_id.code in group['codes'])
            accounts = set(group['detail']) | set(balance_lines.account_id)
            for account in sorted(accounts, key=lambda a: a.code):
                amount = self._no_negative_zero(
                    sign * sum(l.debit - l.credit for l in balance_lines if l.account_id == account))
                detail = self._no_negative_zero(group['detail'].get(account, 0.0))
                lines.append({'group': group['label'], 'account': account, 'detail': detail, 'balance': amount,
                              'gap': self._no_negative_zero(amount - detail)})
        return lines

    def _compute_reprise_concordance_html(self):
        for balance in self:
            currency = balance.company_id.currency_id
            if not balance.id or not balance._reprise_has_data():
                balance.reprise_concordance_html = False
                continue
            rows = Markup('').join(Markup(
                '<tr class="%s"><td>%s</td><td>%s</td><td class="text-end">%s</td><td class="text-end">%s</td>'
                '<td class="text-end">%s</td></tr>') % (
                '' if not line['gap'] else 'text-danger', line['group'], line['account'].display_name,
                format_amount(balance.env, line['balance'], currency), format_amount(balance.env, line['detail'], currency),
                format_amount(balance.env, line['gap'], currency))
                for line in balance._reprise_concordance())
            balance.reprise_concordance_html = Markup(
                '<table class="table table-sm"><thead><tr><th>%s</th><th>%s</th><th class="text-end">%s</th>'
                '<th class="text-end">%s</th><th class="text-end">%s</th></tr></thead><tbody>%s</tbody></table>') % (
                _("Groupe"), _("Compte"), _("Balance"), _("Détail repris"), _("Écart"), rows)

    # ------------------------------------------------------------------ validation
    def action_validate(self):
        for balance in self.filtered(lambda b: b.state == 'draft'):
            if balance._reprise_has_data():
                gaps = [line for line in balance._reprise_concordance() if line['gap']]
                if gaps:
                    raise UserError(_(
                        "La balance ne concorde pas avec la reprise de portefeuille :\n%s\n"
                        "Corrigez la balance ou la reprise avant de valider.") % '\n'.join(
                        _("- %(account)s : balance %(balance)s, détail repris %(detail)s, écart %(gap)s") % {
                            'account': line['account'].display_name, 'balance': line['balance'],
                            'detail': line['detail'], 'gap': line['gap']} for line in gaps))
        no_reprise = self.filtered(lambda b: b.state == 'draft' and not b._reprise_has_data())
        warned = no_reprise.filtered(lambda b: any(b._reprise_non_zero_lines()))
        result = super().action_validate()
        for balance in warned:
            balance.message_post(body=_(
                "Avertissement : les comptes de crédit ou d'épargne portent un solde mais aucune reprise de portefeuille "
                "n'a été importée pour cette balance : le détail clients, crédits et épargne n'a pas été contrôlé."))
        return result

    def _reprise_non_zero_lines(self):
        self.ensure_one()
        codes = set()
        for param, default in ((CREDIT_CODES_PARAM, CREDIT_CODES_DEFAULT), (SAVINGS_CODES_PARAM, SAVINGS_CODES_DEFAULT)):
            codes.update(self._reprise_codes(param, default))
        return [line for line in self.line_ids if line.account_id.code in codes
                and not self.company_id.currency_id.is_zero(line.debit - line.credit)]
