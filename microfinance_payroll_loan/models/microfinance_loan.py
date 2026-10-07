# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceLoan(models.Model):
    _inherit = 'microfinance.loan'

    product_employee_authorized = fields.Boolean(
        related='product_id.employee_authorized', string='Produit autorisé employés',
        help="Champ technique, utilisé pour la visibilité du bouton « Régulariser la "
             "retenue sur salaire » (microfinance_loan_views.xml).",
    )
    salary_deduction = fields.Boolean(
        string='Retenue sur salaire', copy=False, tracking=True,
        help="Prêt retenu automatiquement sur le bulletin de paie mensuel de l'employé "
             "jusqu'à remboursement total (Lot 2). Réévalué (cf. "
             "_microfinance_recompute_salary_deduction) à la création, au changement de "
             "client, à l'activation et juste avant le décaissement guichet, tant que le "
             "prêt n'est pas décaissé : vrai si le client est lié à un employé ET que le "
             "produit est « Autorisé pour les employés ». Verrouillé une fois décaissé — "
             "seule l'action « Régulariser la retenue sur salaire » peut encore le poser.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if 'officer_id' not in vals and partner.microfinance_officer_id:
                vals['officer_id'] = partner.microfinance_officer_id.id
        loans = super().create(vals_list)
        for loan, vals in zip(loans, vals_list):
            if 'salary_deduction' not in vals and loan.partner_id.microfinance_employee_ids \
                    and loan.product_id.employee_authorized:
                loan.salary_deduction = True
        return loans

    def write(self, vals):
        if 'salary_deduction' in vals and any(loan.disbursement_date for loan in self):
            raise UserError(_(
                "La retenue sur salaire ne peut plus être modifiée une fois le crédit "
                "décaissé."
            ))
        result = super().write(vals)
        if 'partner_id' in vals:
            # Changement de client avant décaissement (cf. _microfinance_recompute_salary_deduction) :
            # un prêt déjà décaissé est de toute façon exclu par la méthode elle-même.
            self._microfinance_recompute_salary_deduction()
        return result

    def _microfinance_recompute_salary_deduction(self):
        """Évaluation TARDIVE de salary_deduction (audit 2026-10-05 : le flag posé une seule
        fois à la création, cf. create() ci-dessus, restait figé à False quand le lien
        employé-client était posé APRÈS coup). Rappelée à la création de la demande
        (microfinance_loan_application.py), au changement de client (write() ci-dessus), à
        l'activation et juste avant le décaissement guichet (hooks dans
        microfinance_loan_management via _do_activate()/action_process_disbursement()
        ci-dessous). Règle inchangée : vrai si le partner est lié à un employé ET le produit
        est autorisé aux employés. N'écrit JAMAIS sur un prêt déjà décaissé — même garde que
        le verrou de write() ci-dessus, pour rester cohérente avec lui sans jamais le
        contourner ici (le contournement délibéré et tracé n'existe que dans
        _microfinance_regularize_salary_deduction, réservé à l'action F)."""
        for loan in self:
            if loan.disbursement_date:
                continue
            should = bool(loan.partner_id.microfinance_employee_ids) and bool(
                loan.product_id.employee_authorized
            )
            if loan.salary_deduction != should:
                super(MicrofinanceLoan, loan).write({'salary_deduction': should})

    def _do_activate(self):
        result = super()._do_activate()
        self._microfinance_recompute_salary_deduction()
        return result

    def action_process_disbursement(self):
        # Avant le décaissement effectif (qui pose disbursement_date) : dernière chance de
        # rattraper un lien employé-client posé tardivement, tant que le flag est encore
        # modifiable normalement.
        self._microfinance_recompute_salary_deduction()
        return super().action_process_disbursement()

    def _microfinance_regularize_salary_deduction(self, reason):
        """Contournement DÉLIBÉRÉ et tracé du verrou de write() ci-dessus, réservé à l'action
        « Régulariser la retenue sur salaire » (microfinance.loan.salary.deduction.regularization.wizard,
        droits : responsable paie ET gestionnaire microfinance, motif obligatoire). super()
        ciblé sur le seul champ salary_deduction : le verrou normal de write() reste intact
        pour tout le reste, y compris un futur write({'salary_deduction': ...}) fait par
        erreur ailleurs, qui restera bloqué comme avant. Même patron que
        hr_payslip.py:_microfinance_run_payment_posting_sudo (bypass étroit, re-vérifié au
        plus près de l'appel)."""
        self.ensure_one()
        if not self.disbursement_date:
            raise UserError(_(
                "Ce prêt n'est pas encore décaissé : la retenue sur salaire est encore "
                "modifiable normalement, la régularisation n'est pas nécessaire."
            ))
        if self.salary_deduction:
            raise UserError(_("La retenue sur salaire est déjà activée sur ce prêt."))
        super(MicrofinanceLoan, self.sudo()).write({'salary_deduction': True})
        self.sudo().message_post(body=_(
            "Retenue sur salaire régularisée après décaissement. Motif : %s"
        ) % reason)

    def action_microfinance_regularize_salary_deduction(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Régulariser la retenue sur salaire'),
            'res_model': 'microfinance.loan.salary.deduction.regularization.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    @api.constrains('product_id', 'partner_id')
    def _check_microfinance_employee_product_restriction(self):
        for loan in self:
            if not loan.partner_id.microfinance_employee_ids:
                continue
            if loan.product_id and not loan.product_id.employee_authorized:
                raise ValidationError(_(
                    "Ce client est lié à un employé : seuls les produits « Autorisés pour "
                    "les employés » peuvent lui être proposés."
                ))

    @api.constrains('repayment_frequency_id', 'product_id', 'salary_deduction')
    def _check_salary_deduction_requires_monthly(self):
        for loan in self:
            if not (loan.salary_deduction or loan.product_id.employee_authorized):
                continue
            if loan.repayment_frequency_id and loan.repayment_frequency_id.code != 'monthly':
                raise ValidationError(_(
                    "Un prêt « Retenue sur salaire » (ou sur un produit « Autorisé pour les "
                    "employés ») doit être remboursé selon une périodicité mensuelle."
                ))

    @api.constrains('officer_id', 'salary_deduction', 'partner_id')
    def _check_officer_matches_portfolio(self):
        for loan in self:
            owner = loan.partner_id.microfinance_officer_id
            if loan.salary_deduction and owner and loan.officer_id != owner:
                raise ValidationError(_(
                    "Ce client est rattaché au portefeuille de %(agent)s : le crédit doit "
                    "être porté par cet agent."
                ) % {'agent': owner.display_name})

    # Onglet « Clients à traiter » (décision 2026-10-05, cas bosta : un client rattaché via
    # microfinance_officer_id, mais SANS prêt, n'apparaît jamais dans « Mes clients » — cf.
    # microfinance_loan_management/models/microfinance_loan.py:1447-1461 (officer_field=
    # 'microfinance_loan_ids.officer_id', jamais vrai sans prêt) et :1536-1562
    # (get_portfolio_tab). Ajouté DEPUIS CE module passerelle, pas microfinance_loan_management
    # : microfinance_officer_id (le champ qui qualifie ce client comme "à traiter") est défini
    # ici (res_partner.py), pas dans microfinance_loan_management — ajouter la logique serveur
    # là-bas créerait une dépendance dans le mauvais sens. Le JS/XML (nav par onglets,
    # rendu générique des colonnes) reste dans microfinance_loan_management ; ce module
    # l'étend par un patch OWL (static/src/js/microfinance_loan_dashboard_patch.js), sans
    # dupliquer ni modifier le composant existant.
    @api.model
    def get_portfolio_tab(self, tab, officer_id_filter=None, offset=0, limit=20,
                           fund_id=None, flow='all', date_from=None, date_to=None):
        # @api.model est OBLIGATOIRE ici (pas que cosmetique) : odoo.api.call_kw inspecte
        # method._api sur la methode REELLEMENT resolue par le MRO (celle-ci, plus derivee
        # que celle de microfinance_loan_management) pour decider du dispatch RPC. Sans ce
        # decorateur, call_kw tombe dans _call_kw_multi, qui consomme args[0] comme des IDS
        # a browse() et decale tous les arguments suivants d'un cran - tab recevait alors
        # l'id agent (ex. 2), d'ou "Onglet de portefeuille inconnu : 2" en prod (jamais
        # reproduit par un appel Python direct en shell, qui ignore ce dispatch RPC).
        if tab == 'clients_a_traiter':
            return self._get_portfolio_clients_a_traiter_tab(officer_id_filter, offset, limit)
        return super().get_portfolio_tab(
            tab, officer_id_filter, offset, limit, fund_id, flow, date_from, date_to)

    @api.model
    def _get_portfolio_clients_a_traiter_tab(self, officer_id_filter, offset, limit):
        """Complément EXACT de « Mes clients » (jamais un domaine dupliqué/divergent) : tout
        client (microfinance_partner_type='client') rattaché à l'agent par
        microfinance_officer_id, dans le périmètre société résolu, qui n'apparaît PAS dans la
        liste que renverrait my_clients pour ce même agent/périmètre. union(my_clients,
        clients_a_traiter) = tous les clients rattachés à l'agent, sans trou ni doublon, quel
        que soit l'état du/des prêt(s) — my_clients inclut un prêt dès sa création (même
        'draft', cf. microfinance_loan_ids sans domaine restrictif), donc un client bascule
        automatiquement de cet onglet vers « Mes clients » dès qu'un prêt existe, jamais de
        trou entre la demande et l'activation."""
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        my_clients_config = self._PORTFOLIO_TAB_CONFIG['my_clients']
        my_clients_domain = [('company_id', 'in', company_ids)] + list(my_clients_config['extra_domain'])
        if officer:
            my_clients_domain.append((my_clients_config['officer_field'], '=', officer))
        my_clients_ids = self.env['res.partner'].search(my_clients_domain).ids

        Partner = self.env['res.partner']
        domain = [
            ('company_id', 'in', company_ids),
            ('microfinance_partner_type', '=', 'client'),
            ('id', 'not in', my_clients_ids),
        ]
        if officer:
            domain.append(('microfinance_officer_id', '=', officer))
        total = Partner.search_count(domain)
        partners = Partner.search(
            domain, offset=offset or 0, limit=limit or 20, order='create_date desc')
        rows = [{
            'id': p.id,
            'name': p.name,
            'microfinance_id_number': p.microfinance_id_number,
            'phone': p.phone,
            'company_id': [p.company_id.id, p.company_id.display_name] if p.company_id else False,
            'create_date': p.create_date and p.create_date.isoformat(),
        } for p in partners]
        columns = [
            {'name': 'name', 'label': 'Nom', 'type': 'char'},
            {'name': 'microfinance_id_number', 'label': 'CIN', 'type': 'char'},
            {'name': 'phone', 'label': 'Téléphone', 'type': 'char'},
            {'name': 'company_id', 'label': 'Agence', 'type': 'many2one'},
            {'name': 'create_date', 'label': 'Créé le', 'type': 'date'},
        ]
        return {'columns': columns, 'rows': rows, 'total': total, 'offset': offset or 0}
