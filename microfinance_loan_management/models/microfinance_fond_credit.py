# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MicrofinanceFondCredit(models.Model):
    _name = 'microfinance.fond.credit'
    _description = 'Fonds de crédit rotatif bailleur'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'microfinance.fond.parent.mixin']
    _order = 'name'

    name = fields.Char(string='Nom du fonds', required=True, tracking=True)
    bailleur_id = fields.Many2one(
        'microfinance.bailleur.fonds', string='Bailleur de fonds', required=True, tracking=True,
        ondelete='restrict',
    )
    code = fields.Char(
        string='Code', default='Nouveau', copy=False, readonly=True, tracking=True,
        help="Généré automatiquement à la création via la séquence 'microfinance.fond.credit', "
             "jamais saisi manuellement.",
    )
    scope = fields.Selection([
        ('single_company', 'Agence unique'),
        ('multi_company', 'Multi-agences (partagé)'),
    ], string='Portée du fonds', required=True, default='single_company', tracking=True,
        help="Choix figé après la première sauvegarde : « Agence unique » rattache le fonds à "
             "une société précise (company_id requis) ; « Multi-agences » laisse company_id vide "
             "et rend le fonds visible/exploitable depuis toutes les agences (solde et historique "
             "consolidés, alimentés par des contributions/crédits de plusieurs agences). Défaut "
             "modèle inchangé ('single_company', y compris pour un create() direct sans le "
             "préciser - import/API) : le formulaire de création préselectionne 'multi_company' "
             "via default_scope dans le contexte de l'action (microfinance_fond_credit_views.xml), "
             "sans toucher à ce comportement ORM par défaut - reste librement modifiable avant la "
             "première sauvegarde, comme avant.")
    company_id = fields.Many2one(
        'res.company', string='Société', default=lambda self: self.env.company, tracking=True,
        help="Requis et figé sur la société courante si le fonds est « Agence unique » ; forcé "
             "vide si « Multi-agences ». Figé après la première sauvegarde, comme la portée.",
    )
    date_debut = fields.Date(string='Date de début', required=True, default=fields.Date.context_today)
    date_cloture = fields.Date(string='Date de clôture')
    passer_gl = fields.Boolean(
        string='Passer au grand livre', default=True,
        help="Si désactivé, les contributions sur ce fonds ne génèrent aucune écriture comptable "
             "(cas mutualiste) : seul l'historique du mouvement est conservé.",
    )
    account_id = fields.Many2one(
        'account.account', string='Compte comptable bailleur',
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current', 'equity'))]",
        default=lambda self: self._default_account_id(),
        help="Compte de contrepartie GL du fonds (dette envers le bailleur ou fonds propres "
             "assimilés selon le montage retenu). Requis si « Passer au grand livre » est actif. "
             "Domaine basé sur account_type (et non un préfixe de code) : le PCEC Madagascar 2005 "
             "ne suit pas la convention classe 2 = Dettes / classe 3 = Fonds propres (classe 2 = "
             "opérations clientèle mixtes actif/passif, classe 3 = comptes divers mixtes ; les "
             "vrais fonds propres sont en classe 5). Pré-rempli à la création avec "
             "res.company.microfinance_fond_account_default_id de la société courante (simple "
             "aide à la saisie, aucun effet rétroactif sur les fonds existants) - reste librement "
             "modifiable, y compris juste après la création.",
    )
    verification_disponibilite = fields.Selection([
        ('never', 'Jamais'),
        ('at_request', 'À la demande de crédit'),
        ('at_disbursement', 'Au décaissement'),
    ], string='Vérifier la disponibilité des fonds', required=True, default='at_disbursement',
        help="« À la demande de crédit » n'a aucun effet observable tant que "
             "microfinance.loan.application reste hors-périmètre (absent de models/__init__.py, "
             "non câblé au module) : seule la valeur « Au décaissement » (action_disburse sur "
             "microfinance.loan) déclenche réellement un contrôle pour l'instant.")
    currency_id = fields.Many2one(
        'res.currency', string='Devise', default=lambda self: self.env.company.currency_id,
    )
    contribution_ids = fields.One2many('microfinance.fond.contribution', 'fond_id', string='Contributions')
    loan_ids = fields.One2many('microfinance.loan', 'fond_credit_id', string='Crédits rattachés')
    total_contributions = fields.Monetary(
        string='Total contributions (net)', compute='_compute_fond_totals', store=True,
        help="Somme des contributions validées (dépôts - retraits), pour le rapport « Utilisation "
             "des fonds ».",
    )
    total_decaisse = fields.Monetary(
        string='Total décaissé', compute='_compute_fond_totals', store=True,
        help="Somme des montants (loan_amount) des crédits rattachés à ce fonds ayant dépassé "
             "l'étape de décaissement (état 'active', 'closed', 'defaulted' ou 'written_off').",
    )
    total_rembourse = fields.Monetary(
        string='Total remboursé', compute='_compute_fond_totals', store=True,
        help="Somme des montants payés (principal + intérêts + pénalités) sur les échéances des "
             "crédits décaissés rattachés à ce fonds.",
    )
    solde_disponible = fields.Monetary(
        string='Solde disponible', compute='_compute_fond_totals', store=True,
        help="total_contributions diminué de l'encours actif (principal restant dû uniquement, "
             "intérêts et pénalités exclus) des crédits en statut 'approved'/'active' rattachés à "
             "ce fonds. Agrégation volontairement en sudo (bypass des ir.rule société sur "
             "microfinance.loan) : pour un fonds « Multi-agences », le solde et les totaux "
             "ci-dessus doivent rester identiques quelle que soit l'agence depuis laquelle on les "
             "consulte, y compris pour un utilisateur qui n'a pas accès à toutes les sociétés "
             "ayant contribué au fonds ou décaissé dessus.",
    )
    allocation_required = fields.Boolean(
        string='Usage par allocation', default=lambda self: bool(self.env['res.company']._get_microfinance_parent()),
        copy=False, readonly=True,
        help="Vrai pour un fonds partagé géré par allocation : une agence ne peut alors utiliser "
             "que sa propre allocation (jamais le solde global). Posé à la création si une société "
             "mère est désignée, et à la première validation d'un partage. Faux = comportement "
             "d'origine (solde global du fonds), conservé pour les fonds existants. Champ stocké "
             "(et non déduit de allocation_ids) : une agence ne voit que sa propre allocation, un "
             "fonds alloué aux autres agences ne doit pas lui apparaître comme « non alloué ».",
    )
    allocation_ids = fields.One2many('microfinance.fond.allocation', 'fond_id', string='Allocations par agence')
    partage_ids = fields.One2many('microfinance.fond.partage', 'fond_id', string='Partages')
    reste_partageable = fields.Monetary(
        string='Reste partageable', compute='_compute_reste_partageable', store=True,
        help="Total des contributions nettes (dépôts − retraits validés) diminué du montant des "
             "partages validés. Pertinent pour un fonds « Multi-agences » ; pré-remplit le "
             "montant d'un nouveau partage. Lecture des partages en sudo : les agences ne les "
             "voient pas (ir.rule), mais le calcul doit rester identique pour tous.",
    )
    active = fields.Boolean(string='Actif', default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Le code du fonds de crédit doit être unique (séquence globale multi-société).'),
    ]

    def _default_account_id(self):
        # sudo() : lecture seule d'un champ société pour préremplir un defaut de formulaire,
        # jamais d'écriture - un utilisateur non-manager (group_microfinance_user) n'a pas
        # forcément accès en lecture à res.company depuis ce contexte, ce défaut ne doit
        # jamais lui bloquer la création d'un fonds (cf. même raisonnement que
        # microfinance_fond_credit_default_id sur res.company, qui n'a pas non plus de
        # groups= au niveau champ).
        return self.env.company.sudo().microfinance_fond_account_default_id

    @api.model
    def _get_default_account_id(self, company):
        # Variante utilisable depuis create() avec une société explicite (vals.get('company_id')),
        # distincte de _default_account_id() (utilisée par le champ Many2one, toujours sur
        # env.company). Retombe sur env.company si aucune société n'est fournie dans vals -
        # même repli que les autres défauts de ce modèle (ex. currency_id).
        company = company or self.env.company
        return company.sudo().microfinance_fond_account_default_id

    @api.model_create_multi
    def create(self, vals_list):
        # Société mère uniquement (sans effet si aucune mère n'est désignée).
        self._check_parent_only()
        for vals in vals_list:
            if vals.get('code', 'Nouveau') in (False, '', 'Nouveau'):
                vals['code'] = self.env['ir.sequence'].next_by_code('microfinance.fond.credit') or 'Nouveau'
            if vals.get('scope') == 'multi_company':
                # company_id a un défaut (société courante) : un fonds partagé n'a pas de société propre.
                vals['company_id'] = False
            if not vals.get('account_id'):
                # Couvre import/API (create() direct sans passer par le formulaire, donc sans le
                # default= du champ ni l'onchange ci-dessous) : même règle de préremplissage,
                # sur la société de vals plutôt que env.company. Ne force rien si un account_id
                # est déjà fourni.
                company = self.env['res.company'].browse(vals.get('company_id')) if vals.get('company_id') else False
                default_account = self._get_default_account_id(company)
                if default_account:
                    vals['account_id'] = default_account.id
        return super().create(vals_list)

    def write(self, vals):
        # Fonds legacy (agence unique) exemptés : seule l'écriture d'un fonds partagé est réservée.
        if any(fond.scope == 'multi_company' for fond in self):
            self._check_parent_only()
        if self.ids and ('scope' in vals or 'company_id' in vals):
            for fond in self:
                if 'scope' in vals and vals['scope'] != fond.scope:
                    raise UserError(_(
                        'La portée (scope) du fonds "%s" ne peut plus être modifiée après sa création.'
                    ) % fond.name)
                if 'company_id' in vals and vals['company_id'] != fond.company_id.id:
                    raise UserError(_(
                        'La société du fonds "%s" ne peut plus être modifiée après sa création.'
                    ) % fond.name)
        return super().write(vals)

    def unlink(self):
        self._check_parent_only()
        return super().unlink()

    @api.onchange('scope')
    def _onchange_scope(self):
        if self.scope == 'multi_company':
            self.company_id = False
        elif self.scope == 'single_company' and not self.company_id:
            self.company_id = self.env.company

    @api.onchange('scope', 'company_id')
    def _onchange_scope_account_domain(self):
        # Domaine dynamique non exprimable en attribut statique du champ : filtre account_type
        # toujours, filtre company_id en plus uniquement pour un fonds "Agence unique" (un fonds
        # "Multi-agences" n'a pas de société propre, donc pas de filtre société pertinent).
        account_type_domain = [('account_type', 'in', ('liability_current', 'liability_non_current', 'equity'))]
        if self.scope == 'single_company' and self.company_id:
            domain = account_type_domain + [('company_id', '=', self.company_id.id)]
        else:
            domain = account_type_domain

        # Préremplissage du compte bailleur (étend cet onchange plutôt que d'en dupliquer un
        # second sur les mêmes champs) : "Multi-agences" n'a pas de société propre (company_id
        # vide), on retombe alors sur env.company - même règle que create()/_get_default_account_id
        # (vals.get('company_id') ou env.company). Ne touche jamais un compte déjà choisi qui
        # appartient bien à cette société : seuls un champ vide ou un compte d'une AUTRE société
        # (résidu d'un changement de portée/société précédent) sont remplacés.
        target_company = self.company_id if self.scope == 'single_company' else self.env.company
        if not self.account_id or (self.account_id.company_id and self.account_id.company_id != target_company):
            self.account_id = target_company.sudo().microfinance_fond_account_default_id if target_company else False

        return {'domain': {'account_id': domain}}

    @api.constrains('scope', 'company_id')
    def _check_scope_company(self):
        for fond in self:
            if fond.scope == 'single_company' and not fond.company_id:
                raise ValidationError(_(
                    'Un fonds à portée "Agence unique" doit être rattaché à une société.'
                ))
            if fond.scope == 'multi_company' and fond.company_id:
                raise ValidationError(_(
                    'Un fonds à portée "Multi-agences" ne doit pas être rattaché à une société spécifique.'
                ))

    @api.constrains('date_debut', 'date_cloture')
    def _check_dates(self):
        for fond in self:
            if fond.date_cloture and fond.date_cloture < fond.date_debut:
                raise ValidationError(_(
                    'La date de clôture doit être postérieure ou égale à la date de début.'
                ))

    @api.constrains('passer_gl', 'account_id')
    def _check_account_required(self):
        for fond in self:
            if fond.passer_gl and not fond.account_id:
                raise ValidationError(_(
                    'Le compte comptable bailleur est requis lorsque "Passer au grand livre" est actif.'
                ))

    @api.constrains('account_id')
    def _check_account_type(self):
        # Défense en profondeur : le domaine du champ account_id (UI) exclut déjà ces comptes,
        # mais un create()/write() direct (import, API) doit être bloqué aussi, pas seulement
        # masqué dans le widget de sélection.
        allowed_types = ('liability_current', 'liability_non_current', 'equity')
        for fond in self:
            if fond.account_id and fond.account_id.account_type not in allowed_types:
                raise ValidationError(_(
                    'Le compte comptable bailleur doit être un compte de type dette ou fonds '
                    'propres (liability_current, liability_non_current ou equity).'
                ))

    @api.depends('contribution_ids.amount', 'contribution_ids.type_mouvement', 'contribution_ids.state',
                 'loan_ids.state', 'loan_ids.loan_amount', 'loan_ids.disbursement_date',
                 'loan_ids.installment_ids.principal_amount', 'loan_ids.installment_ids.paid_principal',
                 'loan_ids.installment_ids.paid_interest', 'loan_ids.installment_ids.paid_penalty')
    def _compute_fond_totals(self):
        # sudo() sur loan_ids : un fonds "multi_company" doit exposer les mêmes totaux/solde
        # consolidés quelle que soit l'agence consultante, y compris pour un utilisateur qui n'a
        # pas accès à toutes les sociétés ayant décaissé sur ce fonds (cf. ir.rule stricte sur
        # microfinance.loan, qui ne connaît pas la clause de partage optionnel des fonds).
        # 'active' ne suffit plus à prouver qu'un crédit a été décaissé : depuis le découplage
        # activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md), un crédit
        # peut être 'active' sans écriture de sortie ni disbursement_date. Les totaux
        # « décaissé » / « remboursé » exigent donc disbursement_date renseigné en plus de
        # l'état. solde_disponible (outstanding_states) reste inchangé : un 'approved' et un
        # 'active' non décaissé pèsent identiquement dans l'encours réservé du fonds.
        disbursed_states = ('active', 'closed', 'defaulted', 'written_off')
        outstanding_states = ('approved', 'active')
        for fond in self:
            contributions = fond.contribution_ids.filtered(lambda c: c.state == 'posted')
            deposits = sum(contributions.filtered(lambda c: c.type_mouvement == 'depot').mapped('amount'))
            withdrawals = sum(contributions.filtered(lambda c: c.type_mouvement == 'retrait').mapped('amount'))
            fond.total_contributions = deposits - withdrawals

            loans = fond.sudo().loan_ids
            disbursed_loans = loans.filtered(lambda l: l.state in disbursed_states and l.disbursement_date)
            fond.total_decaisse = sum(disbursed_loans.mapped('loan_amount'))
            fond.total_rembourse = sum(
                sum(loan.installment_ids.mapped('paid_principal'))
                + sum(loan.installment_ids.mapped('paid_interest'))
                + sum(loan.installment_ids.mapped('paid_penalty'))
                for loan in disbursed_loans
            )

            outstanding_loans = loans.filtered(lambda l: l.state in outstanding_states)
            # Boucle Python explicite plutôt que .mapped(lambda ...) : sur un recordset vide,
            # mapped() avec un callable appelle func(self) une seule fois sur le recordset vide
            # lui-même (au lieu de renvoyer une liste vide), ce qui casse ensure_one() dans
            # _get_principal_outstanding(). L'itération Python directe n'a pas ce piège.
            principal_outstanding = sum(loan._get_principal_outstanding() for loan in outstanding_loans)
            fond.solde_disponible = fond.total_contributions - principal_outstanding

    @api.depends('total_contributions', 'partage_ids.state', 'partage_ids.base_amount')
    def _compute_reste_partageable(self):
        for fond in self:
            partages = fond.sudo().partage_ids.filtered(lambda p: p.state == 'validated')
            fond.reste_partageable = fond.total_contributions - sum(partages.mapped('base_amount'))

    def action_view_contributions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contributions'),
            'res_model': 'microfinance.fond.contribution',
            'view_mode': 'tree,form',
            'domain': [('fond_id', '=', self.id)],
            'context': {'default_fond_id': self.id},
        }

    def action_view_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crédits rattachés'),
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('fond_credit_id', '=', self.id)],
        }

    def action_view_portfolio_allocation_history(self):
        """Historique par fonds (M4) : lignes de répartition agence -> portefeuilles validées pour
        ce fonds, par agence et par portefeuille - lecture seule (voir la vue
        view_microfinance_portfolio_allocation_line_history_tree)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Historique des allocations'),
            'res_model': 'microfinance.portfolio.allocation.line',
            'view_mode': 'tree',
            'views': [(self.env.ref(
                'microfinance_loan_management.view_microfinance_portfolio_allocation_line_history_tree').id, 'tree')],
            'domain': [('fond_id', '=', self.id), ('state', '=', 'validated')],
        }

    @api.model
    def get_dashboard_kpi(self, company_id):
        """Solde total et nombre de fonds actifs visibles pour la société company_id, pour la
        tuile KPI "Fonds bailleurs" du dashboard : les fonds 'single_company' de cette société +
        tous les fonds 'multi_company' (visibles de toutes les agences par nature). Recherche ORM
        standard, sans sudo() : le domaine explicite ci-dessous ET l'ir.rule de partage optionnel
        déjà en place s'appliquent tous les deux, un fonds single_company d'une autre agence
        n'apparaît donc jamais dans ce total."""
        funds, total = self._get_agency_accessible_funds(company_id)
        return {'total': total, 'count': len(funds)}

    @api.model
    def _get_agency_accessible_funds(self, company_id):
        """(fonds, part disponible pour l'agence) : fonds actifs de l'agence + fonds partagés, un
        fonds partagé géré par allocation n'étant retenu que s'il a une allocation pour l'agence.
        Les fonds sont lus avec les droits de l'utilisateur ; seul le montant de l'allocation est lu
        en sudo (l'agence ne voit par ir.rule que sa propre allocation, lecture déterministe)."""
        candidates = self.search([
            ('active', '=', True), ('destination', '=', 'credit'),
            '|', ('company_id', '=', company_id), ('scope', '=', 'multi_company'),
        ])
        funds = self.browse()
        total = 0.0
        for fund in candidates:
            if fund.scope == 'multi_company' and fund.allocation_required:
                allocation = fund.sudo().allocation_ids.filtered(lambda a: a.company_id.id == company_id)
                if not allocation:
                    continue
                total += allocation.solde_disponible
            else:
                total += fund.solde_disponible
            funds |= fund
        return funds, total

    @api.model
    def get_multi_company_usage_chart(self):
        """Utilisation des fonds partagés (scope='multi_company', tous confondus dans cette
        première version — pas de ventilation par fonds individuel, cf. ecarts_lpf.md) par
        agence : contributions nettes (dépôts - retraits, groupées par saisie_company_id) et
        décaissements (groupés par company_id du crédit, pas celle du fonds puisqu'un fonds
        multi_company n'a pas de société propre).

        sudo() sur microfinance.loan : son ir.rule reste strict, sans la clause de partage
        optionnel des fonds/contributions, donc nécessaire pour consolider entre agences.
        sudo() sur microfinance.fond.contribution : nécessaire pour une raison différente —
        group_microfinance_user (accès de base au dashboard) n'a AUCUN droit ir.model.access sur
        ce modèle (choix volontaire du Lot 1 : lecture seule sur fonds/bailleurs, aucun accès
        contribution pour ce groupe). Sans sudo() ici, un simple agent crédit consultant son
        dashboard obtiendrait un AccessError sur toute cette section dès qu'un fonds partagé
        existe. Ce sudo() ne fuite que des montants agrégés par agence, jamais les
        enregistrements de contribution individuels au frontend."""
        multi_funds = self.search([
            ('active', '=', True), ('scope', '=', 'multi_company'), ('destination', '=', 'credit')])
        result = {
            'visible': bool(multi_funds), 'labels': [], 'contributions': [], 'decaissements': [],
            'allocations': [],
        }
        if not multi_funds:
            return result

        contributions = self.env['microfinance.fond.contribution'].sudo().search([
            ('fond_id', 'in', multi_funds.ids), ('state', '=', 'posted'),
        ])
        contrib_by_company = defaultdict(float)
        for contribution in contributions:
            sign = 1.0 if contribution.type_mouvement == 'depot' else -1.0
            contrib_by_company[contribution.saisie_company_id] += sign * contribution.amount

        # disbursement_date en plus de l'état : un 'active' non décaissé n'est pas un
        # décaissement réel (découplage activation / décaissement, AUDIT_decaissement.md).
        disbursed_states = ('active', 'closed', 'defaulted', 'written_off')
        loans = self.env['microfinance.loan'].sudo().search([
            ('fond_credit_id', 'in', multi_funds.ids), ('state', 'in', disbursed_states),
            ('disbursement_date', '!=', False),
        ])
        disbursed_by_company = defaultdict(float)
        for loan in loans:
            disbursed_by_company[loan.company_id] += loan.loan_amount

        # Parts allouées par agence (fonds partagés gérés par allocation), sudo pour la même
        # raison que ci-dessus : le graphique consolide toutes les agences.
        allocated_by_company = defaultdict(float)
        for allocation in multi_funds.filtered('allocation_required').sudo().allocation_ids:
            allocated_by_company[allocation.company_id] += allocation.amount_allocated

        companies = sorted(
            set(contrib_by_company) | set(disbursed_by_company) | set(allocated_by_company),
            key=lambda c: c.name)
        result['labels'] = [company.name for company in companies]
        result['contributions'] = [contrib_by_company.get(company, 0.0) for company in companies]
        result['decaissements'] = [disbursed_by_company.get(company, 0.0) for company in companies]
        result['allocations'] = [allocated_by_company.get(company, 0.0) for company in companies]
        return result

    @api.model
    def get_fond_matrix(self, company_ids):
        """Matrice fonds x agences (visuel dédié du dashboard, distinct de get_dashboard_kpi/
        get_multi_company_usage_chart/get_single_company_chart ci-dessus) : une ligne par fonds
        visible depuis au moins une des sociétés de company_ids (fonds 'single_company' de ces
        sociétés + tous les fonds 'multi_company'), une colonne par société, le montant décaissé
        sur ce fonds par cette société en cellule. Individualise chaque fonds 'multi_company'
        (contrairement à get_multi_company_usage_chart, qui les agrège tous ensemble - limitation
        déjà signalée dans ecarts_lpf.md, résolue ici en même temps).

        Portée volontairement plus large que les autres méthodes ci-dessus : company_ids est
        censé être TOUTES les sociétés auxquelles l'utilisateur courant a accès
        (self.env.user.company_ids), pas seulement celles actuellement cochées dans le sélecteur
        de société (self.env.companies/allowed_company_ids) - hypothèse confirmée avant
        implémentation. Nécessite donc sudo() jusque sur la recherche des fonds elle-même : le
        domain_force de microfinance_fond_credit_company_rule utilise la variable 'company_ids'
        fournie par le moteur ir.rule, qui reflète allowed_company_ids (le sélecteur), pas
        user.company_ids - sans sudo() ici, un fonds d'une société autorisée mais non cochée dans
        le sélecteur serait filtré à tort par la règle, malgré le domaine explicite ci-dessous.
        Même sudo() que get_multi_company_usage_chart sur microfinance.loan, pour la même raison
        (ir.rule stricte sans clause de partage propre aux fonds) plus la nécessité de consolider
        au-delà de la société active."""
        companies = self.env['res.company'].sudo().browse(company_ids).exists()
        if not companies:
            return {'companies': [], 'funds': []}

        funds = self.sudo().search([
            ('active', '=', True), ('destination', '=', 'credit'),
            '|', ('company_id', 'in', companies.ids), ('scope', '=', 'multi_company'),
        ])
        if not funds:
            return {'companies': [{'id': c.id, 'name': c.name} for c in companies.sorted('name')], 'funds': []}

        # disbursement_date en plus de l'état : cf. _compute_fond_totals / AUDIT_decaissement.md.
        disbursed_states = ('active', 'closed', 'defaulted', 'written_off')
        loans = self.env['microfinance.loan'].sudo().search([
            ('fond_credit_id', 'in', funds.ids),
            ('company_id', 'in', companies.ids),
            ('state', 'in', disbursed_states),
            ('disbursement_date', '!=', False),
        ])
        amount_by_fund_company = defaultdict(float)
        for loan in loans:
            amount_by_fund_company[(loan.fond_credit_id.id, loan.company_id.id)] += loan.loan_amount

        default_fond_by_company = {
            company.id: company.microfinance_fond_credit_default_id.id
            for company in companies
        }
        sorted_companies = companies.sorted('name')
        return {
            'companies': [{'id': company.id, 'name': company.name} for company in sorted_companies],
            'funds': [{
                'id': fund.id,
                'name': fund.name,
                'amounts': {
                    company.id: amount_by_fund_company.get((fund.id, company.id), 0.0)
                    for company in sorted_companies
                },
                'is_default_for': [
                    company.id for company in sorted_companies
                    if default_fond_by_company.get(company.id) == fund.id
                ],
            } for fund in funds.sorted('name')],
        }

    @api.model
    def get_single_company_chart(self, company_id):
        """Solde disponible de chaque fonds 'single_company' de la société company_id : une
        agence peut avoir plusieurs fonds propres, ce graphique liste donc chaque fonds
        individuellement plutôt qu'un agrégat unique. Naturellement filtré à la société courante
        par le domaine explicite ci-dessous (les fonds single_company d'une autre agence
        n'apparaissent jamais)."""
        funds = self.search([
            ('active', '=', True), ('scope', '=', 'single_company'), ('company_id', '=', company_id),
            ('destination', '=', 'credit'),
        ])
        labels = funds.mapped('name')
        values = funds.mapped('solde_disponible')
        # Parts de fonds partagés allouées à cette agence (solde propre à l'agence).
        allocations = self.env['microfinance.fond.allocation'].sudo().search([
            ('company_id', '=', company_id), ('fond_id.active', '=', True), ('fond_id.destination', '=', 'credit'),
        ])
        for allocation in allocations:
            labels.append(allocation.fond_id.name)
            values.append(allocation.solde_disponible)
        return {'labels': labels, 'values': values}
