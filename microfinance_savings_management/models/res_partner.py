# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# États de crédit qui bloquent un changement d'agence ou l'archivage du client.
LOAN_STATES_OPEN = ('approved', 'active', 'defaulted')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_savings_account_ids = fields.One2many(
        'microfinance.savings.account', 'partner_id', string="Produits d'épargne",
        domain=[('account_id', '!=', False)])
    microfinance_savings_holder_account_ids = fields.One2many(
        'microfinance.savings.holder.account', 'partner_id', string='Comptes épargne')
    microfinance_savings_count = fields.Integer(compute='_compute_microfinance_savings_count')

    @api.depends('microfinance_savings_account_ids')
    def _compute_microfinance_savings_count(self):
        for partner in self:
            partner.microfinance_savings_count = len(partner.microfinance_savings_account_ids)

    @api.model_create_multi
    def create(self, vals_list):
        # super() (microfinance_loan_management) attribue le numéro permanent et crée le compte
        # crédit ; le compte épargne est créé juste après, dans la même transaction : une erreur
        # ici annule aussi le client et son compte crédit.
        partners = super().create(vals_list)
        if self.env.context.get('microfinance_context'):
            for partner in partners:
                if partner.microfinance_partner_type == 'client':
                    partner._get_or_create_microfinance_savings_container()
        return partners

    def _get_or_create_microfinance_savings_container(self):
        """Compte épargne du client dans son agence (créé avec le compte crédit s'il manque)."""
        self.ensure_one()
        return self.env['microfinance.savings.holder.account']._get_or_create_for(
            self, self.company_id or self.env.company)

    def write(self, vals):
        if {'company_id', 'active'} & set(vals):
            self._check_microfinance_accounts_lifecycle(vals)
        return super().write(vals)

    def _check_microfinance_accounts_lifecycle(self, vals):
        """Compte crédit et compte épargne suivent le client : on refuse un changement d'agence
        (leur N appartient à l'agence d'origine) et un archivage tant qu'il reste de l'activité."""
        Holder = self.env['microfinance.savings.holder.account'].sudo()
        LoanAccount = self.env['microfinance.loan.account'].sudo()
        Loan = self.env['microfinance.loan'].sudo()
        for partner in self:
            holders = Holder.search([('partner_id', '=', partner.id)])
            loan_accounts = LoanAccount.search([('partner_id', '=', partner.id)])
            if 'company_id' in vals and vals['company_id'] != partner.company_id.id and partner.company_id \
                    and (holders or loan_accounts):
                raise UserError(_(
                    "Impossible de changer l'agence de %(partner)s : son compte crédit et son compte "
                    "épargne appartiennent à l'agence %(company)s (même numéro). Un transfert de client "
                    "entre agences doit passer par une procédure dédiée."
                ) % {'partner': partner.display_name, 'company': partner.company_id.display_name})
            if 'active' in vals and not vals['active'] and partner.active:
                open_products = holders.mapped('product_ids').filtered(lambda p: p.state in ('active', 'dormant'))
                if any(abs(h.balance_total) > 0.005 for h in holders) or open_products or Loan.search_count([
                        ('partner_id', '=', partner.id), ('state', 'in', LOAN_STATES_OPEN)]):
                    raise UserError(_(
                        "Impossible d'archiver %s : son compte épargne a un solde ou un produit actif, "
                        "ou il a un crédit en cours."
                    ) % partner.display_name)

    def action_view_microfinance_savings(self):
        """Smart button « Épargne » : seule entrée d'attribution d'un produit d'épargne
        (docs_dev/attribution_epargne_client/) - ouvre directement les PRODUITS du client (plus
        le compte/titulaire, consultable séparément via le menu « Comptes épargne »), avec
        `microfinance_savings_count` (ci-dessus) comme compteur : même domaine que cette liste.
        Titulaire et agence préremplis et lecture seule (view_microfinance_savings_account_
        form_attribution) : l'agent ne choisit que le produit d'épargne à attribuer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Produits d'épargne"),
            'res_model': 'microfinance.savings.account',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('microfinance_savings_management.view_microfinance_savings_account_tree').id, 'tree'),
                (self.env.ref('microfinance_savings_management.view_microfinance_savings_account_form_attribution').id, 'form'),
            ],
            'domain': [('partner_id', '=', self.id), ('account_id', '!=', False)],
            'context': {
                'microfinance_context': True,
                'default_partner_id': self.id,
                'default_company_id': self.company_id.id,
                'microfinance_savings_attribution': True,
            },
        }

    # --- Backend interface caisse (Lot 3) ---
    # Placées ici (microfinance_savings_management, pas microfinance_loan_management) pour la
    # même raison que microfinance.caisse.mouvement (cf. ce modèle) : ce module voit à la fois
    # microfinance_savings_account_ids (défini ici) et microfinance_loan_ids (défini dans
    # microfinance_loan_management, dont ce module dépend) sans dépendance circulaire.

    @api.model
    def search_caisse_clients(self, query, company_id):
        """Recherche client pour le guichet : par nom OU par numéro de compte permanent
        (microfinance_account_number, format AGENCE/NNNNNN). Méthode dédiée plutôt qu'une
        surcharge de name_search, pour ne pas modifier le comportement de recherche partenaire
        des autres modules partagés (EAT/MIIA) sur ce même res.partner."""
        domain = [('microfinance_partner_type', '=', 'client'), ('company_id', '=', company_id)]
        if query:
            domain += ['|', ('name', 'ilike', query), ('microfinance_account_number', 'ilike', query)]
        partners = self.search(domain, limit=20)
        return [{
            'id': partner.id,
            'name': partner.name,
            'account_number': partner.microfinance_account_number,
            'savings_account_name': partner.microfinance_savings_holder_account_ids.filtered(
                lambda h: h.company_id.id == company_id)[:1].name or False,
        } for partner in partners]

    @api.model
    def search_other_agency_clients(self, query, company_id):
        """Recherche client CROSS-AGENCE pour le guichet — uniquement pour détecter un
        client rattaché à une AUTRE agence en vue d'un transfert de remboursement
        inter-agences (module microfinance_transfert_inter_agence).

        Distincte de search_caisse_clients (qui reste strictement mono-agence, cf.
        docs_dev/guichet_caisse/AUDIT_transfert_inter_agence.md §6) : exécutée en sudo()
        ciblé pour franchir base.res_partner_rule — un client d'une autre agence est sinon
        totalement invisible au caissier — mais ne renvoie QUE {id, name, account_number,
        agency_name}. Aucun accès élargi aux crédits / comptes / historique du client :
        c'est get_other_agency_client_loans (module de transfert) qui expose ensuite, sous
        sudo lui aussi et de façon minimale, la liste des crédits actionnables.

        Exclut l'agence de la session (company_id) : ce sont les « autres » agences.
        """
        if not query or len(query) < 2:
            return []
        domain = [
            ('microfinance_partner_type', '=', 'client'),
            ('company_id', '!=', False),
            ('company_id', '!=', company_id),
            '|', ('name', 'ilike', query), ('microfinance_account_number', 'ilike', query),
        ]
        partners = self.sudo().search(domain, limit=20)
        return [{
            'id': partner.id,
            'name': partner.name,
            'account_number': partner.microfinance_account_number,
            'agency_name': partner.company_id.name,
        } for partner in partners]

    @api.model
    def get_client_accounts_summary(self, partner_id, company_id):
        """Agrège en un seul appel les comptes épargne actifs et les crédits actionnables au
        guichet (approuvé en attente de décaissement, actif ou en défaut pour remboursement) —
        formaté directement pour consommation par le composant Owl.js du guichet (Lot 4)."""
        partner = self.browse(partner_id)
        holder = partner.microfinance_savings_holder_account_ids.filtered(lambda h: h.company_id.id == company_id)[:1]
        savings_accounts = holder.product_ids.filtered(lambda a: a.state == 'active')
        loans = partner.microfinance_loan_ids.filtered(
            lambda l: l.company_id.id == company_id and l.state in ('approved', 'active', 'defaulted')
        )
        loan_data = []
        for loan in loans:
            next_installment = loan.installment_ids.filtered(lambda i: i.residual_amount > 0.01).sorted(
                lambda i: (i.due_date, i.sequence)
            )[:1]
            loan_data.append({
                'id': loan.id,
                'name': loan.name,
                'state': loan.state,
                'balance_total': loan.balance_total,
                'next_due_date': next_installment.due_date if next_installment else False,
                'next_due_amount': next_installment.residual_amount if next_installment else 0.0,
                # Onglet « Frais de dossier » du guichet : sélectionne les crédits dont les
                # frais ont été envoyés en caisse et restent à encaisser, montant figé.
                'fee_sent_to_cashier': loan.fee_sent_to_cashier,
                'fee_paid': loan.fee_paid,
                'fee_amount_due': loan.fee_amount_due,
            })
        return {
            'savings_holder_account': {
                'id': holder.id, 'name': holder.name, 'balance_total': holder.balance_total,
            } if holder else False,
            'savings_accounts': [{
                'id': account.id,
                'name': account.name,
                'account_name': holder.name,
                'product': account.product_id.name,
                'balance': account.balance,
            } for account in savings_accounts],
            'loans': loan_data,
        }
