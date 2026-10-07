# -*- coding: utf-8 -*-
from odoo import _, fields, models, tools
from odoo.exceptions import UserError


class MicrofinanceLoanRegularization(models.Model):
    """Vue SQL (E) : « Prêts employés à régulariser ». Lecture seule, live (recalculée à
    chaque requête, jamais de rafraîchissement manuel). Ne liste QUE les anomalies liées à
    un prêt décaissé ou à une demande de crédit en cours — jamais un simple homonyme sans
    prêt ni demande (cf. CSV étape 1 : Jeranut Mickael / Mendrika HERINANDRIANINA en sont
    volontairement absents).

    Approximation documentée : la correspondance CIN est exacte (chiffres seuls, comme la
    fonction partagée hr.employee.microfinance_match_candidates), mais la correspondance par
    nom est ici un simple lower()/trim() SQL, SANS le retrait d'accents que fait la fonction
    Python partagée (unicodedata, non disponible en SQL nu sans l'extension `unaccent`,
    absente de cette instance). Sur les cas réels traités (ccl1, randriana : aucun accent),
    le résultat est identique ; un nom accentué pourrait en théorie ne pas matcher ici alors
    qu'il matche dans le wizard/le bandeau — à surveiller si l'écart se manifeste un jour.

    Les paires explicitement écartées (microfinance.employee.partner.match.dismissal, bouton
    « Ce n'est pas un employé ») sont exclues ici exactement comme dans la fonction Python
    partagée, par un NOT EXISTS sur la même table.
    """
    _name = 'microfinance.loan.regularization'
    _description = 'Prêts employés à régulariser'
    _auto = False
    _order = 'source_id desc'

    source = fields.Selection([
        ('loan_lien_manquant', 'Prêt décaissé — lien employé manquant'),
        ('loan_flag_absent', 'Prêt décaissé — retenue non activée'),
        ('application_pending', 'Demande de crédit — correspondance à confirmer'),
    ], string='Anomalie', readonly=True)
    company_id = fields.Many2one('res.company', string='Société', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Client', readonly=True)
    loan_id = fields.Many2one('microfinance.loan', string='Prêt', readonly=True)
    application_id = fields.Many2one('microfinance.loan.application', string='Demande', readonly=True)
    candidate_employee_id = fields.Many2one('hr.employee', string='Employé candidat', readonly=True)
    source_id = fields.Integer(string='ID source (loan/application)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                -- A) Prêt décaissé, client SANS employé lié, mais un employé actif de la
                --    même société correspond (CIN exact en priorité, sinon nom normalisé).
                SELECT
                    l.id AS id,
                    'loan_lien_manquant' AS source,
                    l.company_id AS company_id,
                    l.partner_id AS partner_id,
                    l.id AS loan_id,
                    NULL::integer AS application_id,
                    COALESCE(cin_match.id, name_match.id) AS candidate_employee_id,
                    l.id AS source_id
                FROM microfinance_loan l
                JOIN res_partner p ON p.id = l.partner_id
                LEFT JOIN LATERAL (
                    SELECT e.id FROM hr_employee e
                    WHERE e.company_id = l.company_id AND e.active
                      AND p.microfinance_id_type = 'cin' AND p.microfinance_id_number IS NOT NULL
                      AND regexp_replace(e.identification_id, '\\D', '', 'g') =
                          regexp_replace(p.microfinance_id_number, '\\D', '', 'g')
                      AND regexp_replace(e.identification_id, '\\D', '', 'g') != ''
                    LIMIT 1
                ) cin_match ON true
                LEFT JOIN LATERAL (
                    SELECT e.id FROM hr_employee e
                    WHERE e.company_id = l.company_id AND e.active
                      AND cin_match.id IS NULL
                      AND lower(trim(e.name)) = lower(trim(p.name))
                    LIMIT 1
                ) name_match ON true
                WHERE l.state IN ('active', 'defaulted')
                  -- Pas de filtre sur disbursement_date ICI (contrairement à B) : un lien
                  -- manquant se corrige toujours manuellement (jamais par A, qui ne fait que
                  -- recalculer salary_deduction une fois le lien posé) — il vaut mieux le
                  -- signaler AVANT décaissement (cas AD/000012, randriana) plutôt que
                  -- d'attendre qu'il devienne un cas de régularisation F après coup.
                  AND NOT EXISTS (
                      SELECT 1 FROM hr_employee e2
                      WHERE e2.microfinance_partner_id = p.id
                  )
                  AND COALESCE(cin_match.id, name_match.id) IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM microfinance_employee_partner_match_dismissal d
                      WHERE d.partner_id = p.id
                        AND d.employee_id = COALESCE(cin_match.id, name_match.id)
                  )

                UNION ALL

                -- B) Prêt décaissé, client DÉJÀ lié à un employé, mais salary_deduction=False
                --    alors que le produit est autorisé aux employés.
                SELECT
                    (1000000000 + l.id) AS id,
                    'loan_flag_absent' AS source,
                    l.company_id AS company_id,
                    l.partner_id AS partner_id,
                    l.id AS loan_id,
                    NULL::integer AS application_id,
                    e.id AS candidate_employee_id,
                    l.id AS source_id
                FROM microfinance_loan l
                JOIN res_partner p ON p.id = l.partner_id
                JOIN hr_employee e ON e.microfinance_partner_id = p.id
                JOIN microfinance_loan_product prod ON prod.id = l.product_id
                WHERE l.disbursement_date IS NOT NULL
                  AND l.state IN ('active', 'defaulted')
                  AND l.salary_deduction IS NOT TRUE
                  AND prod.employee_authorized IS TRUE

                UNION ALL

                -- C) Demande de crédit en cours avec correspondance employé non résolue
                --    (microfinance_employee_match_pending, posé par
                --    microfinance_loan_application._microfinance_detect_employee_match).
                SELECT
                    (2000000000 + a.id) AS id,
                    'application_pending' AS source,
                    a.company_id AS company_id,
                    a.partner_id AS partner_id,
                    NULL::integer AS loan_id,
                    a.id AS application_id,
                    -- Les candidats sont sur le Many2many de la demande elle-même
                    -- (microfinance_employee_match_candidate_ids) : non repris ici pour ne
                    -- pas dépendre du nom de table relation auto-généré par l'ORM ; ouvrir
                    -- la demande pour les consulter.
                    NULL::integer AS candidate_employee_id,
                    a.id AS source_id
                FROM microfinance_loan_application a
                WHERE a.microfinance_employee_match_pending IS TRUE
            )
        """ % {'table': self._table})

    def action_microfinance_dismiss_not_employee(self):
        """Bouton « Ce n'est pas un employé » de la vue de contrôle (E) : écarte
        définitivement la paire (employé candidat, client) via la même table de dismissal
        que B (microfinance.loan.application.action_microfinance_dismiss_employee_match) —
        la ligne disparaît ensuite de cette vue ET des candidats renvoyés par
        hr.employee.microfinance_match_candidates (bandeau D, wizard C) pour cette paire,
        puisque tous trois excluent les dismissals. Ne s'applique qu'aux lignes « lien
        manquant » (le candidat y est un homonyme non confirmé) ; une ligne « retenue non
        activée » a un employé DÉJÀ lié, rien à écarter."""
        Dismissal = self.env['microfinance.employee.partner.match.dismissal']
        for rec in self:
            if rec.source != 'loan_lien_manquant' or not rec.candidate_employee_id or not rec.partner_id:
                raise UserError(_(
                    "Cette ligne n'a pas de correspondance homonyme à écarter."
                ))
            if not Dismissal.search([
                ('employee_id', '=', rec.candidate_employee_id.id),
                ('partner_id', '=', rec.partner_id.id),
            ]):
                Dismissal.create({
                    'employee_id': rec.candidate_employee_id.id,
                    'partner_id': rec.partner_id.id,
                    'note': _("Écarté depuis la vue « Prêts employés à régulariser »."),
                })
            rec.partner_id.message_post(body=_(
                "Correspondance écartée (vue de contrôle « Prêts employés à régulariser ») "
                ": ce client n'est pas %s."
            ) % rec.candidate_employee_id.display_name)
        return True
