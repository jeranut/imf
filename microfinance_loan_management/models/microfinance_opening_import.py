# -*- coding: utf-8 -*-
"""Import du classeur Excel rempli hors ligne dans une balance d'ouverture en brouillon, avec rapport d'erreurs ligne par
ligne. Tout ou rien : s'il y a la moindre erreur, aucune ligne n'est importée et le rapport liste chaque ligne fautive."""
import base64
import re

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError

from . import microfinance_opening_xlsx as xlsx


def _clean(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return ('%s' % value).strip() if value is not None else ''


def _amount(value):
    """Montant lu dans une cellule : nombre Excel ou texte (« 1 000,50 »). Lève ValueError si invalide."""
    if value is None or value == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[\s ]', '', str(value)).replace(',', '.')
    return float(text)


class MicrofinanceOpeningBalanceImport(models.TransientModel):
    _name = 'microfinance.opening.balance.import'
    _description = "Import du fichier Excel de la balance d'ouverture"

    balance_id = fields.Many2one('microfinance.opening.balance', required=True, ondelete='cascade')
    file = fields.Binary(string='Fichier Excel (.xlsx)', required=True)
    filename = fields.Char()
    report = fields.Html(string="Rapport d'import", readonly=True, sanitize=False)
    has_errors = fields.Boolean(readonly=True)

    def _parse(self):
        """Retourne (lignes valides, erreurs) ; une ligne valide = (numéro Excel, compte, partenaire, débit, crédit)."""
        self.ensure_one()
        balance = self.balance_id
        try:
            rows = xlsx.read_rows(base64.b64decode(self.file))
        except ValueError as error:
            return [], [(0, str(error))]
        accounts = {a.code: a for a in self.env['account.account'].search([
            ('company_id', '=', balance.company_id.id), ('deprecated', '=', False)])}
        valid, errors, seen = [], [], set()
        for number, cells in rows:
            cells = cells + [None] * (5 - len(cells))
            if _clean(cells[0]) == xlsx.HEADERS[0] or not any(_clean(c) for c in cells[:5]):
                continue
            code, partner_name = _clean(cells[0]), _clean(cells[2])
            problems = []
            account = accounts.get(code)
            if not code:
                problems.append(_("code du compte manquant"))
            elif not account:
                problems.append(_("compte inconnu dans la société « %(company)s » : %(code)s") % {
                    'company': balance.company_id.name, 'code': code})
            partner = self.env['res.partner']
            if partner_name:
                partner = self.env['res.partner'].search([('name', '=ilike', partner_name)])
                if not partner:
                    problems.append(_("partenaire inconnu : %s") % partner_name)
                elif len(partner) > 1:
                    problems.append(_("plusieurs partenaires portent le nom « %s »") % partner_name)
            amounts = []
            for label, cell in ((_("débit"), cells[3]), (_("crédit"), cells[4])):
                try:
                    value = _amount(cell)
                    if value != value or value in (float('inf'), float('-inf')):
                        raise ValueError
                except ValueError:
                    problems.append(_("montant invalide en %(col)s : « %(value)s »") % {'col': label, 'value': cell})
                    value = 0.0
                if value < 0:
                    problems.append(_("montant négatif en %(col)s : %(value)s") % {'col': label, 'value': value})
                amounts.append(value)
            if amounts[0] and amounts[1]:
                problems.append(_("débit et crédit renseignés ensemble"))
            key = (code, partner.id)
            if account and key in seen:
                problems.append(_("compte en double dans le fichier"))
            seen.add(key)
            if problems:
                errors.append((number, '; '.join(problems)))
            elif account:
                valid.append((number, account, partner, amounts[0], amounts[1]))
        if not rows or (not valid and not errors):
            errors.append((0, _("Le fichier ne contient aucune ligne de balance.")))
        return valid, errors

    def _render(self, valid, errors):
        if not errors:
            return Markup('<p class="text-success">%s</p>') % (_("%s ligne(s) importée(s).") % len(valid))
        rows = Markup('').join(Markup('<tr><td>%s</td><td>%s</td></tr>') % (number or '-', message)
                               for number, message in errors)
        return Markup('<p class="text-danger"><strong>%s</strong></p><table class="table table-sm">'
                      '<thead><tr><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
            _("Fichier refusé : %(n)s ligne(s) en erreur, aucune ligne importée.") % {'n': len(errors)},
            _("Ligne Excel"), _("Erreur"), rows)

    def action_import(self):
        self.ensure_one()
        balance = self.balance_id
        if balance.state != 'draft':
            raise UserError(_("L'import ne se fait que dans une balance en brouillon."))
        valid, errors = self._parse()
        self.write({'report': self._render(valid, errors), 'has_errors': bool(errors)})
        if not errors:
            commands = []
            for _number, account, partner, debit, credit in valid:
                line = balance.line_ids.filtered(lambda l: l.account_id == account and l.partner_id == partner)[:1]
                if line:
                    commands.append((1, line.id, {'debit': debit, 'credit': credit}))
                else:
                    commands.append((0, 0, {'account_id': account.id, 'partner_id': partner.id, 'debit': debit,
                                            'credit': credit}))
            balance.write({'line_ids': commands})
            balance.message_post(body=_("Import Excel : %(n)s ligne(s) importée(s) depuis « %(file)s ».") % {
                'n': len(valid), 'file': escape(self.filename or '')})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new', 'name': _("Importer le fichier Excel")}

    def action_close(self):
        return {'type': 'ir.actions.client', 'tag': 'reload'}
