# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceLoanApplication(models.Model):
    _inherit = 'microfinance.loan.application'

    salary_deduction = fields.Boolean(
        string='Retenue sur salaire', copy=False, tracking=True,
        help="Posé automatiquement à la création quand le client est lié à un employé et "
             "que le produit choisi est « Autorisé pour les employés ». Jamais recalculé "
             "ensuite (ni si le produit change, ni si le lien employé change après coup) : "
             "modifiable manuellement si nécessaire.",
    )
    microfinance_employee_match_pending = fields.Boolean(
        string='Correspondance employé à confirmer', copy=False, tracking=True,
        help="Un employé actif de la même société correspond à ce client par nom ou "
             "e-mail (jamais par CIN seul : un CIN exact est lié automatiquement, cf. "
             "_microfinance_detect_employee_match). Bloque la sortie du brouillon jusqu'à "
             "résolution par l'agent : « Lier à l'employé » ou « Ce n'est pas un employé ».",
    )
    microfinance_employee_match_candidate_ids = fields.Many2many(
        'hr.employee', string='Employé(s) correspondant(s)', copy=False,
        help="Candidats détectés par microfinance_match_candidates (nom ou e-mail "
             "identique, même société) — à confirmer ou écarter par l'agent.",
    )
    microfinance_employee_match_selected_id = fields.Many2one(
        'hr.employee', string='Employé à lier',
        domain="[('id', 'in', microfinance_employee_match_candidate_ids)]", copy=False,
        help="Choisi par l'agent parmi les candidats avant de cliquer « Lier à l'employé »  "
             "— un seul candidat est présélectionné automatiquement, sinon un choix "
             "explicite est obligatoire.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        applications = super().create(vals_list)
        for application, vals in zip(applications, vals_list):
            if 'salary_deduction' not in vals and application.partner_id.microfinance_employee_ids \
                    and application.loan_product_id.employee_authorized:
                application.salary_deduction = True
            application._microfinance_detect_employee_match()
        return applications

    def write(self, vals):
        if vals.get('state') and vals['state'] != 'draft':
            for application in self:
                pending = vals.get(
                    'microfinance_employee_match_pending',
                    application.microfinance_employee_match_pending,
                )
                if pending:
                    raise UserError(_(
                        "%(application)s : une correspondance employé non résolue bloque ce "
                        "dossier — utilisez « Lier à l'employé » ou « Ce n'est pas un "
                        "employé » avant de poursuivre."
                    ) % {'application': application.display_name})
        result = super().write(vals)
        if 'partner_id' in vals:
            self._microfinance_detect_employee_match()
        return result

    def _microfinance_detect_employee_match(self):
        """Rapprochement B (demande de crédit) : si le client de ce dossier n'est PAS encore
        lié à un employé, cherche un employé actif correspondant via la fonction partagée
        hr.employee.microfinance_match_candidates. CIN exact : lien automatique posé +
        trace chatter (sur le dossier, l'employé et le client). Nom/e-mail seulement :
        avertissement bloquant (microfinance_employee_match_pending), jamais de lien
        automatique sur une simple homonymie. N'écrase jamais une correspondance déjà
        écartée par l'agent (microfinance_employee_match_dismissed via le bouton « Ce n'est
        pas un employé », cf. action_microfinance_dismiss_employee_match)."""
        for application in self:
            partner = application.partner_id
            if not partner or partner.microfinance_employee_ids:
                application.microfinance_employee_match_pending = False
                continue
            result = self.env['hr.employee'].microfinance_match_candidates(partner=partner)
            if result['match_type'] == 'cin':
                employee = result['candidates'][:1]
                if employee and not employee.microfinance_partner_id:
                    employee.microfinance_partner_id = partner.id
                    employee.message_post(body=_(
                        "Rattachement automatique au client microfinance %(partner)s (CIN "
                        "identique), détecté à la création/mise à jour de la demande de "
                        "crédit %(app)s."
                    ) % {'partner': partner.display_name, 'app': application.display_name})
                    partner.message_post(body=_(
                        "Rattaché automatiquement à l'employé %(employee)s (CIN identique)."
                    ) % {'employee': employee.display_name})
                    application.message_post(body=_(
                        "Client rattaché automatiquement à l'employé %(employee)s (CIN "
                        "identique)."
                    ) % {'employee': employee.display_name})
                application.microfinance_employee_match_pending = False
            elif result['match_type'] == 'name_or_email' and not application.microfinance_employee_match_pending:
                application.microfinance_employee_match_candidate_ids = result['candidates']
                application.microfinance_employee_match_pending = True
                application.message_post(body=_(
                    "Avertissement : le client %(partner)s correspond par nom ou e-mail à "
                    "%(employees)s (même société), sans CIN identique pour confirmer "
                    "automatiquement. Dossier bloqué jusqu'à résolution (« Lier à "
                    "l'employé » ou « Ce n'est pas un employé »)."
                ) % {
                    'partner': partner.display_name,
                    'employees': ', '.join(result['candidates'].mapped('display_name')),
                })
            elif result['match_type'] is None:
                application.microfinance_employee_match_pending = False

    def action_microfinance_link_matched_employee(self):
        self.ensure_one()
        candidates = self.microfinance_employee_match_candidate_ids
        employee = self.microfinance_employee_match_selected_id
        if not employee and len(candidates) == 1:
            employee = candidates
        if not employee or employee not in candidates:
            raise UserError(_(
                "Choisissez l'employé à lier dans « Employé à lier » (plusieurs candidats "
                "correspondent : %s)."
            ) % ', '.join(candidates.mapped('display_name')))
        if employee.microfinance_partner_id:
            raise UserError(_(
                "%(employee)s est déjà lié à un autre client (%(partner)s)."
            ) % {'employee': employee.display_name, 'partner': employee.microfinance_partner_id.display_name})
        partner = self.partner_id
        employee.microfinance_partner_id = partner.id
        self.microfinance_employee_match_pending = False
        self.message_post(body=_(
            "Correspondance confirmée par l'agent : client rattaché à l'employé %s."
        ) % employee.display_name)
        employee.message_post(body=_(
            "Rattaché au client microfinance %(partner)s, confirmé par l'agent sur la "
            "demande de crédit %(app)s."
        ) % {'partner': partner.display_name, 'app': self.display_name})

    def action_microfinance_dismiss_employee_match(self):
        self.ensure_one()
        candidates = self.microfinance_employee_match_candidate_ids
        partner = self.partner_id
        Dismissal = self.env['microfinance.employee.partner.match.dismissal']
        for employee in candidates:
            if not Dismissal.search([('employee_id', '=', employee.id), ('partner_id', '=', partner.id)]):
                Dismissal.create({
                    'employee_id': employee.id, 'partner_id': partner.id,
                    'note': _('Écarté depuis la demande de crédit %s') % self.display_name,
                })
        self.message_post(body=_(
            "Correspondance employé écartée par l'agent : ce client n'est pas %(employees)s."
        ) % {'employees': ', '.join(candidates.mapped('display_name')) or _('un employé')})
        self.microfinance_employee_match_pending = False

    @api.constrains('loan_product_id', 'partner_id')
    def _check_microfinance_employee_product_restriction(self):
        for application in self:
            if not application.partner_id.microfinance_employee_ids:
                continue
            if application.loan_product_id and not application.loan_product_id.employee_authorized:
                raise ValidationError(_(
                    "Ce client est lié à un employé : seuls les produits « Autorisés pour "
                    "les employés » peuvent lui être proposés."
                ))
