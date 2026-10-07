# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinancePayrollAdvanceWizard(models.TransientModel):
    _name = 'microfinance.payroll.advance.wizard'
    _description = 'Avance spéciale employé (rattachement au portefeuille d\'un agent)'

    employee_id = fields.Many2one('hr.employee', string='Employé', required=True, readonly=True)
    company_id = fields.Many2one(related='employee_id.company_id', string='Société (agence)', readonly=True)
    available_officer_ids = fields.Many2many(
        'res.users', compute='_compute_available_officer_ids',
        help="Agents ayant un portefeuille dans la société de l'employé — sert uniquement de "
             "domaine pour le champ Agent de crédit.",
    )
    officer_id = fields.Many2one(
        'res.users', string='Agent de crédit (CCL)', required=True,
        domain="[('id', 'in', available_officer_ids)]",
        help="Agent dont le portefeuille recevra ce client. C'est ensuite TOUJOURS cet "
             "agent qui lance la demande de crédit depuis la fiche client.",
    )
    note = fields.Text(string='Note')
    candidate_partner_ids = fields.Many2many(
        'res.partner', compute='_compute_candidate_partner_ids',
        string='Clients existants correspondants',
        help="Candidats détectés par la fonction partagée hr.employee."
             "microfinance_match_candidates (CIN exact, ou à défaut nom/e-mail — jamais "
             "les deux en même temps : le CIN exact est prioritaire et exclusif). Recalculé "
             "à chaque réouverture, jamais stocké.",
    )
    selected_partner_id = fields.Many2one(
        'res.partner', string='Client existant à choisir',
        domain="[('id', 'in', candidate_partner_ids)]",
        help="Obligatoire si plusieurs clients existants correspondent : aucune réutilisation "
             "ni création automatique n'est faite dans ce cas, le choix doit être explicite.",
    )

    @api.depends('employee_id')
    def _compute_candidate_partner_ids(self):
        for wizard in self:
            wizard.candidate_partner_ids = wizard._microfinance_find_candidate_partners()

    def _microfinance_find_candidate_partners(self):
        """Candidats de rapprochement (C) pour l'employé du wizard, via la fonction partagée
        hr.employee.microfinance_match_candidates (même fonction que B/D/E). Recordset vide
        si l'employé est déjà lié, ou si son CIN n'est pas renseigné (le CIN est requis pour
        tenter un rapprochement, cf. action_validate) et qu'aucun nom/e-mail ne correspond."""
        self.ensure_one()
        employee = self.employee_id
        if not employee or employee.microfinance_partner_id or not employee.identification_id:
            return self.env['res.partner']
        result = self.env['hr.employee'].microfinance_match_candidates(employee=employee)
        return result['candidates']

    @api.depends('company_id')
    def _compute_available_officer_ids(self):
        Portfolio = self.env['microfinance.portfolio']
        for wizard in self:
            portfolios = Portfolio.search([('company_id', '=', wizard.company_id.id)])
            wizard.available_officer_ids = portfolios.mapped('agent_id')

    def _check_preconditions(self):
        self.ensure_one()
        employee = self.employee_id
        if not employee.contract_id or employee.contract_id.state != 'open':
            raise UserError(_(
                "%(employee)s n'a pas de contrat actif : impossible d'enregistrer une avance "
                "spéciale."
            ) % {'employee': employee.name})
        if not self.env['microfinance.portfolio'].search_count([('company_id', '=', self.company_id.id)]):
            raise UserError(_(
                "%(company)s n'est pas une agence microfinance (aucun portefeuille agent "
                "configuré)."
            ) % {'company': self.company_id.display_name})
        portfolio = self.env['microfinance.portfolio'].search([
            ('agent_id', '=', self.officer_id.id), ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not portfolio:
            raise UserError(_(
                "%(agent)s n'a pas de portefeuille dans l'agence %(company)s."
            ) % {'agent': self.officer_id.display_name, 'company': self.company_id.display_name})

    def _prepare_partner_vals(self):
        self.ensure_one()
        employee = self.employee_id
        vals = {
            'name': employee.name,
            'company_id': self.company_id.id,
            'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
            'is_company': False,
            'phone': employee.work_phone or employee.mobile_phone or False,
            'email': employee.work_email or False,
            'street': employee.private_street or False,
            'street2': employee.private_street2 or False,
            'city': employee.private_city or False,
            'zip': employee.private_zip or False,
            'country_id': employee.private_country_id.id or False,
        }
        cin_digits = re.sub(r'\D', '', employee.identification_id or '')
        if cin_digits:
            vals.update({
                'microfinance_id_type': 'cin',
                'microfinance_id_number_display': cin_digits,
            })
        return vals

    def action_validate(self):
        self.ensure_one()
        self._check_preconditions()
        employee = self.employee_id
        # Capture AVANT toute ecriture : sert a rendre action_validate idempotent au
        # 2e passage (audit 2026-10-05, cas bosta) - le rattachement employe<->client est
        # deja idempotent (on reutilise employee.microfinance_partner_id), mais le message de
        # chatter et l'activite "Traiter l'avance speciale" etaient reposes a chaque appel,
        # dupliquant l'activite a chaque revalidation du wizard.
        already_linked = bool(employee.microfinance_partner_id)

        if employee.microfinance_partner_id:
            partner = employee.microfinance_partner_id
        else:
            if not employee.identification_id:
                raise UserError(_(
                    "Le CIN de %(employee)s n'est pas renseigné sur sa fiche employé : "
                    "complétez-le pour permettre le rapprochement avec un client existant "
                    "(ou la création d'un nouveau client avec ce CIN), puis relancez "
                    "l'avance spéciale."
                ) % {'employee': employee.display_name})
            candidates = self.candidate_partner_ids
            if len(candidates) > 1:
                if not self.selected_partner_id or self.selected_partner_id not in candidates:
                    raise UserError(_(
                        "Plusieurs clients existants correspondent à %(employee)s "
                        "(%(names)s) : choisissez le bon dans « Client existant à choisir » "
                        "avant de valider. Aucune création ni réutilisation automatique "
                        "n'est faite dans ce cas."
                    ) % {'employee': employee.display_name,
                         'names': ', '.join(candidates.mapped('display_name'))})
                partner = self.selected_partner_id
            elif len(candidates) == 1:
                partner = candidates
            else:
                partner = self.env['res.partner']

        if partner and partner.microfinance_officer_id and partner.microfinance_officer_id != self.officer_id:
            raise UserError(_(
                "Ce client (%(partner)s) est déjà rattaché au portefeuille de %(agent)s : "
                "impossible de le réaffecter silencieusement. Contactez un gestionnaire si un "
                "transfert est réellement nécessaire."
            ) % {'partner': partner.display_name, 'agent': partner.microfinance_officer_id.display_name})
        if partner and partner.company_id != self.company_id:
            raise UserError(_(
                "Ce client (%(partner)s) est déjà rattaché à l'agence %(agency)s : impossible "
                "de le rattacher aussi à %(company)s."
            ) % {'partner': partner.display_name, 'agency': partner.company_id.display_name,
                 'company': self.company_id.display_name})

        if not partner:
            vals = self._prepare_partner_vals()
            try:
                with self.env.cr.savepoint():
                    partner = self.env['res.partner'].with_context(
                        microfinance_context=True).create(vals)
            except (ValidationError, UserError):
                return self._open_partner_prefill_form(vals)

        if not partner.microfinance_officer_id:
            partner.microfinance_officer_id = self.officer_id.id

        employee.microfinance_partner_id = partner.id
        if not already_linked:
            # Lien etabli POUR LA PREMIERE FOIS par CET appel : trace chatter + activite,
            # une seule fois. Un 2e passage du wizard (ex. reparation d'un rattachement
            # incomplet) retrouve le meme partner ci-dessus sans rien recreer ici.
            employee.message_post(body=_(
                "Avance spéciale : client microfinance %(partner)s rattaché au portefeuille de "
                "%(agent)s."
            ) % {'partner': partner.display_name, 'agent': self.officer_id.display_name})
            partner.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Traiter l\'avance spéciale de %s') % employee.name,
                user_id=self.officer_id.id,
                note=self.note or '',
            )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': partner.id,
            'target': 'current',
        }

    def _open_partner_prefill_form(self, vals):
        """Des champs obligatoires du client manquent (ex. situation matrimoniale + conjoint
        pour un employé marié) : plutôt que de créer un client incomplet, on ouvre une fiche
        client pré-remplie (non enregistrée) pour que l'agent la complète lui-même. Le
        rattachement employé<->client ne se fait qu'au prochain passage du wizard, une fois le
        client effectivement enregistré."""
        self.ensure_one()
        context = {('default_%s' % key): value for key, value in vals.items() if value is not False}
        context['microfinance_context'] = True
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compléter la fiche client avant rattachement'),
            'res_model': 'res.partner',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }
