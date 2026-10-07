# -*- coding: utf-8 -*-
import re
import unicodedata

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _microfinance_normalize_name(name):
    """Nom en minuscules, accents retirés, ponctuation réduite à un espace unique — sert
    uniquement à comparer deux noms ÉCRITS DIFFÉREMMENT (espaces, accents, casse), jamais à
    déduire une identité : une homonymie exacte sur ce critère reste un indice faible (cf.
    microfinance_match_candidates ci-dessous, type 'name_or_email', jamais auto-liée)."""
    if not name:
        return ''
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


def _microfinance_cin_digits(value):
    return re.sub(r'\D', '', value or '')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    microfinance_partner_id = fields.Many2one(
        'res.partner', string='Client microfinance', readonly=True, copy=False, tracking=True,
        help="Client microfinance créé (ou retrouvé) pour l'avance spéciale de cet employé, "
             "rattaché au portefeuille de l'agent de crédit choisi dans le wizard. Posé une "
             "seule fois ; ce n'est jamais le wizard qui crée ensuite la demande de crédit — "
             "c'est l'agent qui la lance depuis la fiche client.",
    )

    @api.constrains('microfinance_partner_id')
    def _check_microfinance_partner_unique_per_company(self):
        """Un client microfinance (avance spéciale) ne peut être l'employé-emprunteur que
        d'UN SEUL employé par société — cf. audit 2026-10-05 (bulletin ccl1, LOAN=0 à cause
        d'un lien manquant) : ce contrôle ne retrouve que les violations futures (il ne
        s'applique qu'en écriture sur CE champ), les données déjà en base ne sont jamais
        touchées par cette contrainte."""
        for employee in self:
            if not employee.microfinance_partner_id:
                continue
            others = self.search([
                ('microfinance_partner_id', '=', employee.microfinance_partner_id.id),
                ('company_id', '=', employee.company_id.id),
                ('id', '!=', employee.id),
            ])
            if others:
                raise ValidationError(_(
                    "Le client microfinance %(partner)s est déjà l'avance spéciale de "
                    "%(other)s dans %(company)s : un client ne peut être lié qu'à un seul "
                    "employé par société."
                ) % {
                    'partner': employee.microfinance_partner_id.display_name,
                    'other': others[0].display_name,
                    'company': employee.company_id.display_name,
                })

    def action_open_microfinance_payroll_advance_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Avance spéciale',
            'res_model': 'microfinance.payroll.advance.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_employee_id': self.id},
        }

    @api.model
    def microfinance_match_candidates(self, employee=None, partner=None):
        """Point d'entrée UNIQUE de rapprochement employé <-> client microfinance, partagé
        par : le wizard Avance spéciale (C), le rapprochement automatique à la demande de
        crédit (B), le bandeau d'alerte du bulletin de paie (D) et la vue de contrôle « Prêts
        employés à régulariser » (E). Donner EXACTEMENT un des deux arguments. Fonction de
        DÉTECTION PURE : ne modifie jamais rien.

        Retourne un dict :
          - company    : société de référence (employee.company_id ou partner.company_id) ;
          - linked     : le partner déjà lié (si `employee` donné et microfinance_partner_id
                         posé) ou les employé(s) déjà lié(s) (si `partner` donné, via
                         microfinance_employee_ids) — recordset vide sinon ;
          - match_type : 'cin' | 'name_or_email' | None (None si `linked` est déjà renseigné
                         ou si aucun candidat trouvé) ;
          - candidates : recordset des candidats (partners ou employés actifs, selon le sens
                         donné), MÊME SOCIÉTÉ, hors `linked`, au MEILLEUR type trouvé — le CIN
                         exact est exclusif et prioritaire ; à défaut, nom normalisé OU e-mail
                         identique, qui peuvent renvoyer plusieurs candidats (ex. deux
                         partners homonymes : cas randriana, 4493/4495).
        """
        if bool(employee) == bool(partner):
            raise ValueError(
                "microfinance_match_candidates : donner employee OU partner, pas les deux ni aucun."
            )

        if employee:
            employee.ensure_one()
            company = employee.company_id
            linked = employee.microfinance_partner_id
            if linked:
                return {
                    'company': company, 'linked': linked, 'match_type': None,
                    'candidates': self.env['res.partner'],
                }
            Partner = self.env['res.partner'].sudo()
            # microfinance_partner_type='client' exclut notamment work_contact_id : hr.employee
            # auto-cree un res.partner generique (meme nom, aucun type microfinance) pour CHAQUE
            # employe - sans ce filtre, un employe neuf matcherait systematiquement son propre
            # contact technique par nom, jamais un vrai client (bug trouve en testant ce module).
            domain = [('company_id', '=', company.id), ('microfinance_partner_type', '=', 'client')]
            cin_digits = _microfinance_cin_digits(employee.identification_id)
            if cin_digits:
                pool = Partner.search(domain + [
                    ('microfinance_id_type', '=', 'cin'), ('microfinance_id_number', '!=', False),
                ])
                cin_candidates = pool.filtered(
                    lambda p: _microfinance_cin_digits(p.microfinance_id_number) == cin_digits
                )
                if cin_candidates:
                    return {
                        'company': company, 'linked': self.env['res.partner'],
                        'match_type': 'cin', 'candidates': cin_candidates,
                    }
            name_norm = _microfinance_normalize_name(employee.name)
            email = (employee.work_email or '').strip().lower()
            name_or_email_candidates = Partner.browse()
            if name_norm or email:
                pool = Partner.search(domain)
                name_or_email_candidates = pool.filtered(
                    lambda p: (name_norm and _microfinance_normalize_name(p.name) == name_norm)
                    or (email and (p.email or '').strip().lower() == email)
                )
            dismissed_partner_ids = self.env['microfinance.employee.partner.match.dismissal'].sudo().search([
                ('employee_id', '=', employee.id),
            ]).mapped('partner_id').ids
            name_or_email_candidates = name_or_email_candidates.filtered(
                lambda p: p.id not in dismissed_partner_ids
            )
            return {
                'company': company, 'linked': self.env['res.partner'],
                'match_type': 'name_or_email' if name_or_email_candidates else None,
                'candidates': name_or_email_candidates,
            }

        # `partner` donné : on cherche des employés candidats.
        partner.ensure_one()
        company = partner.company_id
        linked = partner.microfinance_employee_ids
        if linked:
            return {
                'company': company, 'linked': linked, 'match_type': None,
                'candidates': self.browse(),
            }
        Employee = self.sudo()
        domain = [('company_id', '=', company.id), ('active', '=', True)]
        cin_digits = (
            _microfinance_cin_digits(partner.microfinance_id_number)
            if partner.microfinance_id_type == 'cin' else ''
        )
        if cin_digits:
            pool = Employee.search(domain + [('identification_id', '!=', False)])
            cin_candidates = pool.filtered(
                lambda e: _microfinance_cin_digits(e.identification_id) == cin_digits
            )
            if cin_candidates:
                return {
                    'company': company, 'linked': self.browse(),
                    'match_type': 'cin', 'candidates': cin_candidates,
                }
        name_norm = _microfinance_normalize_name(partner.name)
        email = (partner.email or '').strip().lower()
        name_or_email_candidates = Employee.browse()
        if name_norm or email:
            pool = Employee.search(domain)
            name_or_email_candidates = pool.filtered(
                lambda e: (name_norm and _microfinance_normalize_name(e.name) == name_norm)
                or (email and (e.work_email or '').strip().lower() == email)
            )
        dismissed_employee_ids = self.env['microfinance.employee.partner.match.dismissal'].sudo().search([
            ('partner_id', '=', partner.id),
        ]).mapped('employee_id').ids
        name_or_email_candidates = name_or_email_candidates.filtered(
            lambda e: e.id not in dismissed_employee_ids
        )
        return {
            'company': company, 'linked': self.browse(),
            'match_type': 'name_or_email' if name_or_email_candidates else None,
            'candidates': name_or_email_candidates,
        }
