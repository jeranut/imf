# -*- coding: utf-8 -*-
import psycopg2

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_savings_account_ids = fields.One2many(
        'microfinance.savings.account', 'partner_id', string='Comptes épargne')
    microfinance_savings_count = fields.Integer(compute='_compute_microfinance_savings_count')

    @api.depends('microfinance_savings_account_ids')
    def _compute_microfinance_savings_count(self):
        for partner in self:
            partner.microfinance_savings_count = len(partner.microfinance_savings_account_ids)

    @api.model_create_multi
    def create(self, vals_list):
        # Ouverture du conteneur épargne (couple avec le conteneur crédit, même N) dès la
        # création du contact client — SEUL compte épargne créé automatiquement (correctif du
        # 2026-09-24, docs_dev/epargne_auto/AUDIT_doublons_creation_client.md §13 : abroge
        # l'« Option A » du 21/09 où un « compte principal » réel coexistait avec un conteneur
        # créé plus tard, au 1er crédit — cf. microfinance_loan_extension.py, où cette création
        # a été retirée). Un client déjà en base avant ce correctif et qui n'a pas encore de
        # conteneur n'en obtient pas automatiquement rétroactivement : cf. migration dédiée
        # (container_migration.py).
        # super().create() remonte jusqu'à res_partner.py (microfinance_loan_management), qui
        # attribue microfinance_account_number ET crée le conteneur crédit (microfinance.loan.
        # account) avant de revenir ici — condition nécessaire pour que le conteneur épargne
        # puisse reprendre le même N (cf. microfinance_savings_account.py._get_container_target_
        # name). Ordre garanti par les dépendances de module (microfinance_savings_management
        # dépend de microfinance_loan_management, donc chargé après : son create() encadre celui
        # de loan_management, qui s'exécute avant que ce code ne reprenne la main).
        partners = super().create(vals_list)
        if self.env.context.get('microfinance_context'):
            for partner in partners:
                if partner.microfinance_partner_type == 'client':
                    partner._get_or_create_microfinance_savings_container()
        return partners

    def _get_or_create_microfinance_savings_container(self):
        """Ouvre (ou réutilise) l'UNIQUE conteneur épargne de ce client pour sa société - appelée
        depuis create() ci-dessus, à l'enregistrement du client, symétrique de res.partner.
        _get_or_create_microfinance_loan_account() (microfinance_loan_management) côté crédit,
        avec lequel il partage son N. RÈGLE : un conteneur par client ET par société (pas par
        crédit ni par produit) - même cardinalité que le compte crédit
        (unique(partner_id, company_id)).

        C'est désormais le SEUL compte épargne créé automatiquement : il n'y a plus de « compte
        principal » distinct (abrogé, cf. create() ci-dessus). Tout compte épargne réel
        supplémentaire reste une création manuelle (bouton « Épargne » du crédit, menu Épargne).

        Idempotent à deux niveaux : recherche préalable (sudo() limité à cette recherche, pour
        ne pas dépendre des règles d'accès) puis index unique partiel en base
        (microfinance_savings_account_container_uniq_idx) qui couvre deux créations concurrentes."""
        self.ensure_one()
        company = self.company_id or self.env.company
        Account = self.env['microfinance.savings.account']
        domain = [('partner_id', '=', self.id), ('company_id', '=', company.id), ('is_container', '=', True)]
        existing = Account.sudo().search(domain, limit=1)
        if existing:
            return Account.browse(existing.id)
        try:
            with self.env.cr.savepoint():
                return Account.create({
                    'partner_id': self.id, 'company_id': company.id, 'is_container': True,
                })
        except psycopg2.IntegrityError:
            # Course avec une création concurrente : l'index unique a refusé la nôtre, on
            # réutilise celle qui a gagné.
            existing = Account.sudo().search(domain, limit=1)
            if existing:
                return Account.browse(existing.id)
            raise

    def action_view_microfinance_savings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Épargne',
            'res_model': 'microfinance.savings.account',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
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
        savings_accounts = partner.microfinance_savings_account_ids.filtered(
            lambda a: a.company_id.id == company_id and a.state == 'active'
        )
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
            'savings_accounts': [{
                'id': account.id,
                'name': account.name,
                'product': account.product_id.name,
                'balance': account.balance,
            } for account in savings_accounts],
            'loans': loan_data,
        }
