# -*- coding: utf-8 -*-
"""Reprise de portefeuille : import (clients, crédits en cours, et épargne si le module épargne est installé) rattaché à une
balance d'ouverture en brouillon. Le détail doit seulement concorder avec la balance : AUCUNE écriture comptable, AUCUN
mouvement de caisse, AUCUNE créance de frais n'est créé (voir docs_dev/balance_ouverture/AUDIT_reprise_portefeuille.md).

Principes : simulation par défaut et sans aucune création (les séquences ne sont pas transactionnelles) ; tout ou rien
(une erreur bloque l'import de la société) ; idempotent (clé = référence client, unique par société) ; sudo() uniquement
dans _apply(), après contrôle des droits et de la société de la balance.

Points d'extension pour microfinance_savings_management (jamais d'import inverse) : _template_sheets, _validate_extra,
_apply_extra, _summary_extra."""
import base64
import re
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_round

from . import microfinance_opening_xlsx as xlsx
from .microfinance_opening_import import _amount, _clean

CLIENTS_SHEET = 'Clients'
CREDITS_SHEET = 'Crédits'
CLIENTS_HEADERS = ['Référence client', 'Nom', 'CIN', 'Téléphone', 'Agent de crédit', 'Type (individuel / société)']
CREDITS_HEADERS = ['Référence client', 'Produit de crédit', 'Principal initial', 'Principal restant',
                   'Date de décaissement', 'Périodicité', "Nombre d'échéances restantes",
                   "Date de la prochaine échéance", 'Agent de crédit']
CLIENT_TYPES = {'individuel': 'individual', 'individual': 'individual', 'particulier': 'individual',
                'société': 'company', 'societe': 'company', 'company': 'company'}
WRITE_GROUPS = ('microfinance_loan_management.group_microfinance_finance',
                'microfinance_loan_management.group_microfinance_manager')


class MicrofinanceOpeningReprise(models.TransientModel):
    _name = 'microfinance.opening.reprise'
    _description = "Reprise de portefeuille (import)"

    balance_id = fields.Many2one('microfinance.opening.balance', string="Balance d'ouverture", required=True,
                                 domain="[('state', '=', 'draft')]",
                                 help="Balance en brouillon de la société à reprendre : la date d'ouverture de la reprise "
                                      "est celle de la balance.")
    company_id = fields.Many2one(related='balance_id.company_id', string='Société')
    file = fields.Binary(string='Fichier Excel (.xlsx)')
    filename = fields.Char()
    dry_run = fields.Boolean(string='Simulation (aucune création)', default=True,
                             help="Cochée : le fichier est seulement contrôlé et le rapport affiché, rien n'est créé.")
    report = fields.Html(string="Rapport d'import", readonly=True, sanitize=False)
    has_errors = fields.Boolean(readonly=True)

    # ------------------------------------------------------------------ gabarit
    def _template_sheets(self):
        """Feuilles du gabarit (extensible : le module épargne ajoute « Épargne »)."""
        return [
            {'name': CLIENTS_SHEET, 'headers': CLIENTS_HEADERS, 'rows': [], 'text_columns': (0, 1, 2, 3, 4, 5)},
            {'name': CREDITS_SHEET, 'headers': CREDITS_HEADERS, 'rows': [], 'text_columns': (0, 1, 4, 5, 7, 8),
             'money_columns': (2, 3)},
        ]

    def _template_instructions(self):
        return [
            _("1. Une ligne par client (feuille Clients), puis ses crédits en cours et ses soldes d'épargne dans les autres feuilles."),
            _("2. « Référence client » est votre code libre (ex. CLI-001) : il relie les feuilles et évite les doublons si vous relancez l'import."),
            _("3. CIN : 12 chiffres, obligatoire pour un particulier, saisi comme TEXTE. Téléphone : texte aussi (zéros de tête)."),
            _("4. Agent de crédit : nom exact de l'utilisateur, qui doit avoir un portefeuille actif dans l'agence."),
            _("5. Type : « individuel » ou « société » (le type « groupe » n'est pas encore pris en charge)."),
            _("6. Dates au format jj/mm/aaaa. La prochaine échéance doit être postérieure ou égale à la date de la balance d'ouverture."),
            _("7. Seul le principal restant est repris : intérêts et pénalités échus ou restants sont à 0 dans cette version."),
            _("8. Importez d'abord en simulation (case cochée) : le rapport liste les erreurs ligne par ligne. Une erreur bloque tout l'import."),
        ]

    def _template_workbook(self):
        return xlsx.build_workbook(self._template_sheets(), self._template_instructions(),
                                   _("Reprise de portefeuille - mode d'emploi"))

    def action_download_template(self):
        return {'type': 'ir.actions.act_url', 'target': 'self', 'url': '/microfinance/opening_reprise/template.xlsx'}

    # ------------------------------------------------------------------ lecture
    def _sheet_rows(self, sheets, name, headers, errors):
        """Lignes de données d'une feuille : [(numéro Excel, cellules complétées)]. Une feuille absente donne []."""
        rows = []
        for number, cells in sheets.get(name, []):
            cells = list(cells) + [None] * (len(headers) - len(cells))
            if _clean(cells[0]) == headers[0] and number == 1:
                continue
            if not any(_clean(c) for c in cells[:len(headers)]):
                continue
            rows.append((number, cells))
        return rows

    def _find_agent(self, name, company):
        """(utilisateur, message d'erreur). Lecture en sudo ciblé : nom exact, portefeuille actif dans la société."""
        Users = self.env['res.users'].sudo()
        users = Users.search([('name', '=', name)])
        if not users:
            return Users, _("agent inconnu : %s") % name
        if len(users) > 1:
            return Users, _("plusieurs utilisateurs portent le nom « %s »") % name
        if not self.env['microfinance.portfolio'].sudo().search_count([
                ('agent_id', '=', users.id), ('company_id', '=', company.id), ('active', '=', True)]):
            return Users, _("l'agent « %(agent)s » n'a pas de portefeuille actif dans l'agence « %(company)s »") % {
                'agent': name, 'company': company.name}
        return users, False

    # ------------------------------------------------------------------ contrôle (aucune création)
    def _validate(self, sheets):
        """(plan, erreurs, avertissements). Aucune écriture, aucune création."""
        self.ensure_one()
        balance, company = self.balance_id, self.balance_id.company_id
        S = self.sudo()
        Partner = S.env['res.partner'].with_context(active_test=False)
        errors, warnings = [], []
        plan = {'clients': {}, 'loans': [], 'balance': balance, 'company': company}

        def err(sheet, number, message):
            errors.append((sheet, number, message))

        client_rows = self._sheet_rows(sheets, CLIENTS_SHEET, CLIENTS_HEADERS, errors)
        credit_rows = self._sheet_rows(sheets, CREDITS_SHEET, CREDITS_HEADERS, errors)
        extra_names = {spec['name'] for spec in self._template_sheets()} - {CLIENTS_SHEET, CREDITS_SHEET}
        if not client_rows and not credit_rows and not any(sheets.get(n) for n in extra_names):
            err('-', 0, _("Le fichier ne contient aucune ligne à reprendre."))
            return plan, errors, warnings

        # --- clients déjà connus dans la société (clé : référence interne)
        known = defaultdict(lambda: Partner)
        for partner in Partner.search([('company_id', '=', company.id), ('microfinance_internal_reference', '!=', False)]):
            known[partner.microfinance_internal_reference] |= partner
        # --- CIN existants, toutes sociétés (lecture ciblée en sudo : la règle multi-société masque les autres agences)
        cin_map = defaultdict(list)
        for partner in Partner.search([('microfinance_id_type', '=', 'cin'), ('microfinance_id_number', '!=', False)]):
            cin_map[re.sub(r'\D', '', partner.microfinance_id_number)].append(partner)
        seen_cin = {}

        for number, cells in client_rows:
            ref, name, cin_raw, phone, agent_name, type_raw = (_clean(c) for c in cells[:6])
            if not ref:
                err(CLIENTS_SHEET, number, _("référence client manquante"))
                continue
            if ref in plan['clients']:
                err(CLIENTS_SHEET, number, _("référence client en double dans le fichier : %s") % ref)
                continue
            problems = []
            if not name:
                problems.append(_("nom manquant"))
            ctype = CLIENT_TYPES.get(type_raw.lower()) if type_raw else 'individual'
            if not ctype:
                problems.append(_("type inconnu « %s » (individuel ou société ; le type groupe n'est pas pris en charge)")
                                % type_raw)
            existing = known.get(ref, Partner)
            if len(existing) > 1:
                problems.append(_("plusieurs clients de l'agence portent la référence %s") % ref)
            digits = re.sub(r'\D', '', cin_raw)
            if cin_raw and not digits:
                problems.append(_("CIN invalide : %s") % cin_raw)
            elif digits and len(digits) != 12:
                problems.append(_("le CIN doit contenir 12 chiffres (%s)") % cin_raw)
            elif ctype == 'individual' and not digits:
                problems.append(_("CIN obligatoire pour un client particulier"))
            if digits and len(digits) == 12:
                if digits in seen_cin:
                    problems.append(_("CIN en double dans le fichier (ligne %s)") % seen_cin[digits])
                seen_cin.setdefault(digits, number)
                others = [p for p in cin_map.get(digits, []) if p not in existing]
                if others:
                    problems.append(_("CIN déjà utilisé par un autre contact (agence %s)") % ', '.join(
                        sorted({p.company_id.name or _('sans agence') for p in others})))
                if not existing:
                    try:
                        S.env['res.partner']._check_no_active_loan_elsewhere(digits, company.id)
                    except ValidationError as error:
                        problems.append(error.args[0])
            officer = S.env['res.users']
            if existing:
                officer = existing.microfinance_officer_id
            elif not agent_name:
                problems.append(_("agent de crédit manquant"))
            if agent_name and not existing:
                officer, message = self._find_agent(agent_name, company)
                if message:
                    problems.append(message)
            if problems:
                err(CLIENTS_SHEET, number, '; '.join(problems))
                continue
            vals = {
                'name': name, 'company_id': company.id, 'microfinance_partner_type': 'client',
                'microfinance_client_type': ctype, 'is_company': ctype == 'company', 'phone': phone or False,
                'microfinance_officer_id': officer.id, 'microfinance_internal_reference': ref,
                'opening_balance_id': balance.id,
            }
            if digits:
                vals.update({'microfinance_id_type': 'cin', 'microfinance_id_number': digits})
            plan['clients'][ref] = {'row': number, 'vals': vals, 'partner': existing, 'cin': digits, 'officer': officer,
                                    'ctype': ctype}

        def client_info(ref):
            if ref in plan['clients']:
                return plan['clients'][ref]
            partner = known.get(ref, Partner)
            if len(partner) == 1:
                return {'partner': partner, 'cin': re.sub(r'\D', '', partner.microfinance_id_number or '')
                        if partner.microfinance_id_type == 'cin' else '',
                        'officer': partner.microfinance_officer_id, 'ctype': partner.microfinance_client_type}
            return None
        plan['client_info'] = client_info
        plan['known'] = known

        # --- crédits
        Product = S.env['microfinance.loan.product']
        Frequency = S.env['microfinance.repayment.frequency']
        done_refs = {}
        existing_loans = S.env['microfinance.loan'].search([('opening_balance_id', '=', balance.id)])
        currency = company.currency_id
        for number, cells in credit_rows:
            ref, product_name, initial_raw, remaining_raw, disb_raw, freq_name, count_raw, due_raw, agent_name = (
                cells[0], cells[1], cells[2], cells[3], cells[4], cells[5], cells[6], cells[7], cells[8])
            ref, product_name, freq_name, agent_name = _clean(ref), _clean(product_name), _clean(freq_name), _clean(agent_name)
            if not ref:
                err(CREDITS_SHEET, number, _("référence client manquante"))
                continue
            problems = []
            info = client_info(ref)
            if not info:
                err(CREDITS_SHEET, number, _("client inconnu : %s") % ref)
                continue
            if ref in done_refs:
                err(CREDITS_SHEET, number, _("un seul crédit repris par client (déjà ligne %s)") % done_refs[ref])
                continue
            done_refs[ref] = number
            products = Product.search([('name', '=', product_name), ('company_id', '=', company.id)])
            product = products[:1] if len(products) == 1 else Product
            if not products:
                problems.append(_("produit de crédit inconnu dans l'agence : %s") % product_name)
            elif len(products) > 1:
                problems.append(_("plusieurs produits de crédit portent le nom « %s »") % product_name)
            amounts = []
            for label, raw in ((_("principal initial"), initial_raw), (_("principal restant"), remaining_raw)):
                try:
                    value = _amount(raw)
                    if value != value or value in (float('inf'), float('-inf')):
                        raise ValueError
                except ValueError:
                    problems.append(_("montant invalide en %(col)s : « %(value)s »") % {'col': label, 'value': raw})
                    value = 0.0
                amounts.append(value)
            initial, remaining = amounts
            if initial <= 0 or remaining <= 0:
                problems.append(_("le principal initial et le principal restant doivent être positifs"))
            elif remaining > initial + 0.005:
                problems.append(_("incohérence : principal restant (%(rest)s) supérieur au principal initial (%(init)s)")
                                % {'rest': remaining, 'init': initial})
            dates = []
            for label, raw in ((_("date de décaissement"), disb_raw), (_("date de la prochaine échéance"), due_raw)):
                try:
                    value = xlsx.to_date(raw)
                except ValueError:
                    problems.append(_("%(col)s invalide : « %(value)s »") % {'col': label, 'value': raw})
                    value = None
                if value is None and not _clean(raw):
                    problems.append(_("%s manquante") % label)
                dates.append(value)
            disb_date, first_due = dates
            if disb_date and disb_date > balance.date:
                problems.append(_("la date de décaissement (%s) est postérieure à la date de la balance d'ouverture")
                                % disb_date.strftime('%d/%m/%Y'))
            if first_due and first_due < balance.date:
                problems.append(_("la première échéance (%(due)s) est antérieure à la date de la balance d'ouverture "
                                  "(%(date)s)") % {'due': first_due.strftime('%d/%m/%Y'),
                                                   'date': balance.date.strftime('%d/%m/%Y')})
            try:
                count = _amount(count_raw)
                if count != int(count) or count < 1:
                    raise ValueError
                count = int(count)
            except (ValueError, OverflowError):
                problems.append(_("nombre d'échéances restantes invalide : « %s »") % count_raw)
                count = 0
            frequency = Frequency
            if product:
                if product.repayment_frequency_mode == 'fixed':
                    frequency = product.repayment_frequency_id
                    if freq_name and freq_name.lower() != (frequency.name or '').lower():
                        problems.append(_("le produit impose la périodicité « %(imposed)s » (fichier : « %(file)s »)")
                                        % {'imposed': frequency.name, 'file': freq_name})
                else:
                    frequency = Frequency.search([('name', '=ilike', freq_name)], limit=1) if freq_name else Frequency
                    if not freq_name:
                        problems.append(_("périodicité obligatoire pour ce produit"))
                    elif not frequency:
                        problems.append(_("périodicité inconnue : %s") % freq_name)
                    elif frequency not in product.allowed_repayment_frequency_ids:
                        problems.append(_("périodicité « %(freq)s » non autorisée par le produit « %(product)s »")
                                        % {'freq': freq_name, 'product': product.name})
                if not frequency and not any('périodicité' in p for p in problems):
                    problems.append(_("le produit n'a pas de périodicité"))
            officer = info['officer']
            if agent_name:
                officer, message = self._find_agent(agent_name, company)
                if message:
                    problems.append(message)
            elif not officer:
                problems.append(_("agent de crédit manquant"))
            if info['cin']:
                try:
                    S.env['res.partner']._check_no_active_loan_elsewhere(info['cin'], company.id)
                except ValidationError as error:
                    problems.append(error.args[0])
            partner = info['partner']
            skip = bool(partner and existing_loans.filtered(lambda loan: loan.partner_id == partner))
            if problems:
                err(CREDITS_SHEET, number, '; '.join(problems))
                continue
            plan['loans'].append({
                'row': number, 'ref': ref, 'product': product, 'initial': initial, 'remaining': remaining,
                'disbursement_date': disb_date, 'frequency': frequency, 'count': count, 'first_due': first_due,
                'officer': officer, 'skip': skip,
            })
        self._validate_extra(sheets, plan, errors, warnings)
        return plan, errors, warnings

    def _validate_extra(self, sheets, plan, errors, warnings):
        """Point d'extension : contrôle des feuilles ajoutées par _template_sheets (épargne)."""

    # ------------------------------------------------------------------ application
    def _apply(self, plan):
        """Crée clients et crédits. sudo() ciblé : appelé uniquement après _check_can_import() ; la société est celle de
        la balance, vérifiée en amont (la balance est lue avec les droits et la règle de société de l'utilisateur)."""
        balance, company = plan['balance'], plan['company']
        context = {'microfinance_context': True, 'allow_microfinance_partner_create': True,
                   'mf_reprise_skip_product_limits': True}
        Partner = self.env['res.partner'].sudo().with_company(company).with_context(**context)
        Loan = self.env['microfinance.loan'].sudo().with_company(company).with_context(**context)
        created = {'clients': 0, 'crédits': 0}
        for entry in plan['clients'].values():
            if not entry['partner']:
                entry['partner'] = Partner.create(entry['vals'])
                created['clients'] += 1
        currency = company.currency_id
        for item in plan['loans']:
            if item['skip']:
                continue
            partner = plan['client_info'](item['ref'])['partner']
            vals = {
                'partner_id': partner.id, 'product_id': item['product'].id, 'company_id': company.id,
                'loan_amount': item['initial'], 'term': item['count'], 'repayment_frequency_id': item['frequency'].id,
                'officer_id': item['officer'].id, 'state': 'active', 'application_date': item['disbursement_date'],
                'approval_date': item['disbursement_date'], 'activation_date': item['disbursement_date'],
                'disbursement_date': item['disbursement_date'], 'fee_paid': True, 'opening_balance_id': balance.id,
            }
            if 'salary_deduction' in Loan._fields:
                vals['salary_deduction'] = False
            loan = Loan.create(vals)
            delta = loan._period_delta()
            count, remaining = item['count'], item['remaining']
            base = float_round(remaining / count, precision_rounding=currency.rounding, rounding_method='DOWN')
            commands = []
            for index in range(count):
                due = loan._roll_forward_to_collection_day(item['first_due'] + delta * index)
                principal = base if index < count - 1 else currency.round(remaining - base * (count - 1))
                commands.append((0, 0, {'sequence': index + 1, 'due_date': due, 'principal_amount': principal}))
            loan.write({'installment_ids': commands})
            loan.message_post(body=_("Crédit repris à l'ouverture (%(balance)s) : principal restant %(rest)s. Aucun "
                                     "décaissement, frais ni écriture comptable n'a été enregistré.") % {
                'balance': balance.name, 'rest': remaining})
            created['crédits'] += 1
        created.update(self._apply_extra(plan) or {})
        return created

    def _apply_extra(self, plan):
        """Point d'extension (épargne) : retourne des compteurs supplémentaires."""
        return {}

    # ------------------------------------------------------------------ rapport
    def _summary_extra(self, plan):
        """Point d'extension : lignes de résumé supplémentaires."""
        return []

    def _render(self, plan, errors, warnings, created=None):
        if errors:
            rows = Markup('').join(Markup('<tr><td>%s</td><td>%s</td><td>%s</td></tr>') % (sheet, number or '-', message)
                                   for sheet, number, message in errors)
            return Markup('<p class="text-danger"><strong>%s</strong></p><table class="table table-sm"><thead><tr>'
                          '<th>%s</th><th>%s</th><th>%s</th></tr></thead><tbody>%s</tbody></table>') % (
                _("Fichier refusé : %(n)s ligne(s) en erreur, rien n'a été créé.") % {'n': len(errors)},
                _("Feuille"), _("Ligne Excel"), _("Erreur"), rows)
        clients = plan['clients'].values()
        loans = [item for item in plan['loans']]
        lines = [
            _("Clients : %(new)s à créer, %(old)s déjà repris ou existants.") % {
                'new': sum(1 for c in clients if not c['partner']), 'old': sum(1 for c in clients if c['partner'])},
            _("Crédits : %(new)s à reprendre, %(old)s déjà repris (ignorés) ; principal restant à reprendre : %(total)s.") % {
                'new': sum(1 for i in loans if not i['skip']), 'old': sum(1 for i in loans if i['skip']),
                'total': sum(i['remaining'] for i in loans if not i['skip'])},
        ] + self._summary_extra(plan)
        if created is not None:
            head = _("Import terminé : %s.") % ', '.join('%s %s' % (v, k) for k, v in created.items())
        else:
            head = _("Simulation réussie : aucune erreur, rien n'a été créé. Décochez « Simulation » pour importer.")
        if created is not None:
            lines = []
        body = Markup('').join(Markup('<li>%s</li>') % line for line in lines + list(warnings))
        return Markup('<p class="text-success"><strong>%s</strong></p><ul>%s</ul>') % (head, body)

    # ------------------------------------------------------------------ action
    def _check_can_import(self):
        if not any(self.env.user.has_group(group) for group in WRITE_GROUPS):
            raise AccessError(_("Seuls les profils Finance et Manager crédit peuvent importer la reprise de portefeuille "
                                "(la simulation reste ouverte en lecture)."))

    def action_import(self):
        self.ensure_one()
        balance = self.balance_id
        if balance.state != 'draft':
            raise UserError(_("La reprise ne s'importe que dans une balance d'ouverture en brouillon."))
        if not self.file:
            raise UserError(_("Choisissez le fichier Excel à importer."))
        if not self.dry_run:
            self._check_can_import()
        try:
            sheets = xlsx.read_sheets(base64.b64decode(self.file))
        except ValueError as error:
            self.write({'report': self._render({}, [('-', 0, str(error))], []), 'has_errors': True})
            return self._reopen()
        plan, errors, warnings = self._validate(sheets)
        if errors:
            self.write({'report': self._render(plan, errors, warnings), 'has_errors': True})
        elif self.dry_run:
            self.write({'report': self._render(plan, errors, warnings), 'has_errors': False})
        else:
            created = self._apply(plan)
            balance.message_post(body=_("Reprise de portefeuille importée depuis « %(file)s » : %(detail)s.") % {
                'file': self.filename or '', 'detail': ', '.join('%s %s' % (v, k) for k, v in created.items())})
            self.write({'report': self._render(plan, errors, warnings, created), 'has_errors': False, 'dry_run': True})
        return self._reopen()

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'current', 'name': _("Reprise de portefeuille")}
