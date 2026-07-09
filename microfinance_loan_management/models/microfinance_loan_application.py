# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

# États d'un crédit considérés comme "réalisés" pour le calcul du rang de prêt
# (loan_sequence_number) : les dossiers jamais décaissés (brouillon → approuvé, annulé)
# ne comptent pas comme un prêt antérieur du client.
PRIOR_LOAN_STATES = ('active', 'closed', 'defaulted', 'written_off')


class MicrofinanceLoanApplicationTier(models.Model):
    """Palier de prêt configurable (libellé d'affichage uniquement).

    Le libellé "Premier prêt / Prêt successif" (case PP/PS de la fiche papier) est dérivé
    du rang numérique loan_sequence_number via ce modèle de référence, jamais d'une
    Selection figée : chaque institution définit ses propres paliers et intitulés
    (ex. 1er prêt / 2e prêt / prêt confirmé) sans toucher au code."""
    _name = 'microfinance.loan.application.tier'
    _description = 'Palier de prêt (libellé du rang de crédit)'
    _order = 'sequence_number, id'

    name = fields.Char(string='Libellé', required=True, translate=True)
    sequence_number = fields.Integer(
        string='Rang de prêt minimum', required=True, default=1,
        help="Le palier s'applique à partir de ce rang : un dossier de rang N reçoit le "
             'libellé du palier au rang le plus élevé inférieur ou égal à N.',
    )
    company_id = fields.Many2one(
        'res.company', string='Société',
        help='Laisser vide pour un palier commun à toutes les sociétés.',
    )
    active = fields.Boolean(string='Actif', default=True)


class MicrofinanceLoanApplication(models.Model):
    _name = 'microfinance.loan.application'
    _description = "Dossier d'instruction de crédit microfinance"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    # Transitions autorisées du cycle de vie (un pas en avant, ou retour d'un pas pour
    # correction). Le passage vers loan_created n'est possible que via action_create_loan().
    ALLOWED_TRANSITIONS = {
        'draft': {'field_survey'},
        'field_survey': {'draft', 'analysis'},
        'analysis': {'field_survey', 'committee'},
        'committee': {'analysis', 'ca_review'},
        'ca_review': {'committee', 'cdag_review'},
        'cdag_review': {'ca_review', 'accepted', 'accepted_condition', 'refused'},
        'accepted': {'cdag_review', 'loan_created'},
        'accepted_condition': {'cdag_review', 'loan_created'},
        'refused': {'cdag_review'},
        'loan_created': set(),
    }

    # Rôle minimum requis pour amener un dossier vers chaque état (double contrôle : ordre
    # du cycle de vie ET rôle). Le manager crédit passe outre le contrôle de rôle (mais
    # jamais celui de l'ordre).
    STATE_TARGET_GROUP = {
        'draft': 'microfinance_loan_management.group_application_surveyor',
        'field_survey': 'microfinance_loan_management.group_application_surveyor',
        'analysis': 'microfinance_loan_management.group_application_surveyor',
        'committee': 'microfinance_loan_management.group_application_surveyor',
        'ca_review': 'microfinance_loan_management.group_application_ca',
        'cdag_review': 'microfinance_loan_management.group_application_cdag',
        'accepted': 'microfinance_loan_management.group_application_cdag',
        'accepted_condition': 'microfinance_loan_management.group_application_cdag',
        'refused': 'microfinance_loan_management.group_application_cdag',
        'loan_created': 'microfinance_loan_management.group_application_cdag',
    }

    # ------------------------------------------------------------------
    # En-tête
    # ------------------------------------------------------------------
    name = fields.Char(string='Référence dossier', default='Nouveau', copy=False, readonly=True, tracking=True)
    application_date = fields.Date(string='Date de la demande', default=fields.Date.context_today, required=True, tracking=True)
    surveyor_id = fields.Many2one('res.users', string='Enquêteur', default=lambda self: self.env.user, tracking=True)
    ca_responsible_id = fields.Many2one('res.users', string='Chargé de compte responsable', tracking=True)
    company_id = fields.Many2one('res.company', string='Société / Agence', default=lambda self: self.env.company, required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Devise', related='company_id.currency_id', readonly=True)
    reference = fields.Char(string='Référence libre')
    partner_id = fields.Many2one('res.partner', string='Client / Emprunteur potentiel', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('field_survey', 'Enquête terrain'),
        ('analysis', 'Analyse'),
        ('committee', 'Soumis comité'),
        ('ca_review', 'Avis CA'),
        ('cdag_review', 'Avis CDAG'),
        ('accepted', 'Accepté'),
        ('accepted_condition', 'Accepté sous condition'),
        ('refused', 'Refusé'),
        ('loan_created', 'Transformé en crédit'),
    ], string='État', default='draft', tracking=True, index=True, group_expand=True)
    kanban_color = fields.Integer(string='Couleur kanban', compute='_compute_kanban_color')
    loan_id = fields.Many2one('microfinance.loan', string='Crédit créé', readonly=True, copy=False, tracking=True)
    loan_sequence_number = fields.Integer(
        string='Rang de prêt', compute='_compute_loan_sequence_number', store=True, readonly=False,
        tracking=True,
        help='1 pour le premier crédit du client, 2 pour le suivant, etc. Calculé depuis les '
             "crédits antérieurs décaissés du client, modifiable manuellement (ex. client ayant "
             'déjà emprunté dans une autre institution).',
    )
    is_first_loan = fields.Boolean(string='Premier prêt', compute='_compute_is_first_loan')
    loan_tier_id = fields.Many2one('microfinance.loan.application.tier', string='Palier de prêt', compute='_compute_loan_tier')
    loan_tier_label = fields.Char(string='Libellé du palier', compute='_compute_loan_tier')

    # ------------------------------------------------------------------
    # Bloc A — Identité complète (KYC, figée au moment de l'enquête)
    # ------------------------------------------------------------------
    partner_surname = fields.Char(string='Nom de famille')
    partner_id_card_number = fields.Char(string='N° CIN')
    partner_id_card_issue_date = fields.Date(string='CIN délivrée le')
    partner_id_card_issue_place = fields.Char(string='CIN délivrée à')
    partner_current_address = fields.Char(string='Adresse actuelle')
    partner_fokontany = fields.Char(string='Fokontany')
    partner_address_since = fields.Date(string="À cette adresse depuis")
    partner_housing_status = fields.Selection([
        ('owner_inheritance', 'Propriétaire (héritage)'),
        ('owner_purchase', 'Propriétaire (achat)'),
        ('owner_donation', 'Propriétaire (donation)'),
        ('tenant_free', 'Locataire sans loyer'),
        ('tenant_paying', 'Locataire avec loyer'),
    ], string="Statut d'occupation du logement")
    partner_phone = fields.Char(string='Téléphone')
    partner_reference_contact_name = fields.Char(string='Personne de référence')
    partner_reference_contact_phone = fields.Char(string='Téléphone de la référence')
    partner_birth_date = fields.Date(string='Date de naissance')
    partner_birth_place = fields.Char(string='Lieu de naissance')
    partner_marital_status = fields.Selection([
        ('single', 'Célibataire'),
        ('married', 'Marié(e)'),
        ('cohabiting', 'Union libre'),
        ('divorced', 'Divorcé(e)'),
        ('widowed', 'Veuf / Veuve'),
    ], string='Situation matrimoniale')

    spouse_name = fields.Char(string='Nom du conjoint')
    spouse_id_card_number = fields.Char(string='CIN du conjoint')
    spouse_address = fields.Char(string='Adresse du conjoint')
    spouse_fokontany = fields.Char(string='Fokontany du conjoint')
    spouse_profession = fields.Char(string='Profession du conjoint')
    spouse_employer = fields.Char(string='Employeur du conjoint')
    spouse_phone = fields.Char(string='Téléphone du conjoint')
    union_duration = fields.Char(string="Durée de l'union")

    dependent_ids = fields.One2many('microfinance.loan.application.dependent', 'application_id', string='Enfants et personnes à charge')
    guarantor_line_ids = fields.One2many('microfinance.loan.application.guarantor.line', 'application_id', string='Garants')
    document_line_ids = fields.One2many('microfinance.loan.application.document.line', 'application_id', string='Documents administratifs fournis')
    surveyor_comment = fields.Text(string="Commentaire de l'enquêteur")

    # ------------------------------------------------------------------
    # Bloc B — Analyse de viabilité de l'activité
    # ------------------------------------------------------------------
    activity_description = fields.Text(string="Description de l'activité")
    activity_code = fields.Char(string="Code activité")
    activity_sector = fields.Selection([
        ('commerce', 'Commerce'),
        ('manufacturing', 'Fabrication'),
        ('service', 'Service'),
        ('other', 'Autres'),
    ], string="Secteur d'activité")
    sale_location_status = fields.Selection([
        ('owner', 'Propriétaire'),
        ('tenant', 'Locataire'),
    ], string='Lieu de vente : statut')
    sale_location_type = fields.Selection([
        ('fixed', 'Fixe'),
        ('mobile', 'Mobile'),
        ('ambulant', 'Ambulant'),
        ('delivery', 'Livraison'),
    ], string='Lieu de vente : type')
    sale_location_enclosed = fields.Selection([
        ('closed', 'Fermé'),
        ('open', 'Ouvert'),
    ], string='Lieu de vente : fermé/ouvert')
    formalization_level = fields.Selection([
        ('informal', 'Informel'),
        ('fokontany_authorization', 'Autorisation fokontany'),
        ('patente', 'Patente'),
        ('statistical_card', 'Carte statistique'),
        ('trade_register', 'Registre du commerce'),
    ], string='Niveau de formalisation')
    activity_start_date = fields.Date(string="Début de l'activité")
    activity_interruption = fields.Text(string="Interruptions de l'activité")
    is_cyclical = fields.Boolean(string='Activité cyclique')
    cyclical_period = fields.Char(string='Période du cycle')
    supply_frequency = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string="Fréquence d'approvisionnement")
    supplier_payment_mode = fields.Selection([
        ('cash', 'Comptant'),
        ('credit', 'Crédit'),
    ], string='Paiement fournisseurs')
    supplier_credit_delay_days = fields.Integer(string='Délai crédit fournisseur (jours)')
    sale_frequency = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string='Fréquence des ventes')
    customer_type = fields.Selection([
        ('passersby', 'Passants'),
        ('neighbors', 'Voisins'),
        ('on_order', 'Sur commande'),
        ('other', 'Autres'),
    ], string='Type de clientèle')
    customer_payment_mode = fields.Selection([
        ('cash', 'Comptant'),
        ('credit', 'Crédit'),
    ], string='Paiement clients')
    customer_credit_delay_days = fields.Integer(string='Délai crédit clients (jours)')
    other_income_activities = fields.Text(string='Autres activités génératrices de revenus')
    loan_request_reason = fields.Text(
        string='Pourquoi demander le prêt maintenant ?',
        help='À renseigner uniquement pour un premier prêt (PP uniquement sur la fiche papier).',
    )
    has_existing_debt = fields.Boolean(string='Dette en cours')
    debt_purpose = fields.Char(string='Objet de la dette')
    debt_amount = fields.Monetary(string='Montant de la dette')
    debt_creditor_type = fields.Selection([
        ('family', 'Famille'),
        ('friend', 'Ami'),
        ('neighbor', 'Voisin'),
        ('imf', 'IMF'),
        ('bank', 'Banque'),
        ('other', 'Autre'),
    ], string='Créancier')
    debt_repayment_mode = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string='Mode de remboursement de la dette')

    # ------------------------------------------------------------------
    # Bloc C — Analyse financière et capacité de remboursement
    # ------------------------------------------------------------------
    income_line_ids = fields.One2many('microfinance.loan.application.income.line', 'application_id', string='Lignes revenus / dépenses')
    safety_margin_current = fields.Float(
        string='Majoration dépenses actuelles (%)', default=5.0,
        help='Marge de sécurité appliquée aux dépenses familiales actuelles (fiche papier : +5%).',
    )
    safety_margin_forecast = fields.Float(
        string='Majoration dépenses prévisionnelles (%)', default=10.0,
        help='Les dépenses familiales prévisionnelles sont les dépenses actuelles majorées de ce '
             'pourcentage (fiche papier : +10%), sans ressaisie du détail.',
    )
    total_family_income_current = fields.Monetary(string='Revenus familiaux (actuel)', compute='_compute_financial_totals')
    total_family_income_forecast = fields.Monetary(string='Revenus familiaux (prévisionnel)', compute='_compute_financial_totals')
    total_activity_expense_current = fields.Monetary(string="Dépenses d'activité (actuel)", compute='_compute_financial_totals')
    total_activity_expense_forecast = fields.Monetary(string="Dépenses d'activité (prévisionnel)", compute='_compute_financial_totals')
    total_family_expense_current = fields.Monetary(string='Dépenses familiales majorées (actuel)', compute='_compute_financial_totals')
    total_family_expense_forecast = fields.Monetary(string='Dépenses familiales majorées (prévisionnel)', compute='_compute_financial_totals')
    repayment_capacity_monthly_current = fields.Monetary(string='Capacité de remboursement mensuelle (actuel)', compute='_compute_financial_totals')
    repayment_capacity_weekly_current = fields.Monetary(string='Capacité de remboursement hebdomadaire (actuel)', compute='_compute_financial_totals')
    repayment_capacity_monthly_forecast = fields.Monetary(string='Capacité de remboursement mensuelle (prévisionnel)', compute='_compute_financial_totals')
    repayment_capacity_weekly_forecast = fields.Monetary(string='Capacité de remboursement hebdomadaire (prévisionnel)', compute='_compute_financial_totals')
    income_growth_before = fields.Monetary(string='Revenu avant')
    income_growth_after = fields.Monetary(string='Revenu actuel')
    financial_analysis_comment = fields.Text(string="Commentaire d'analyse financière")
    funding_plan_current_total = fields.Monetary(string='Plan de financement (actuel)')
    funding_plan_forecast_total = fields.Monetary(string='Plan de financement (prévisionnel)')

    # ------------------------------------------------------------------
    # Bloc D — Visites terrain pré-octroi
    # ------------------------------------------------------------------
    field_visit_ids = fields.One2many('microfinance.loan.application.field.visit', 'application_id', string='Visites terrain')
    field_visit_count = fields.Integer(string='Nombre de visites', compute='_compute_counts')

    # ------------------------------------------------------------------
    # Bloc E — Avis CA / CDAG
    # ------------------------------------------------------------------
    requested_amount = fields.Monetary(string='Montant demandé', tracking=True)
    required_savings = fields.Monetary(string='Épargne exigée (demande)')
    repayment_amount = fields.Monetary(string='Remboursement (demande)')
    period = fields.Integer(string='Durée demandée (échéances)')
    available_savings = fields.Monetary(string='Épargne disponible')
    ca_amount = fields.Monetary(string='Montant avis CA', tracking=True)
    ca_required_savings = fields.Monetary(string='Épargne exigée (CA)')
    ca_repayment_amount = fields.Monetary(string='Remboursement (CA)')
    ca_period = fields.Integer(string='Durée avis CA (échéances)')
    cdag_amount = fields.Monetary(string='Montant avis CDAG', tracking=True)
    cdag_required_savings = fields.Monetary(string='Épargne exigée (CDAG)')
    cdag_repayment_amount = fields.Monetary(string='Remboursement (CDAG)')
    cdag_period = fields.Integer(string='Durée avis CDAG (échéances)')
    previous_loan_amount = fields.Monetary(string='Montant du prêt précédent')
    previous_loan_repayment_behavior = fields.Selection([
        ('early', 'En avance'),
        ('normal', 'Normal'),
        ('irregular', 'Irrégulier'),
        ('late', 'En retard'),
    ], string='Comportement de remboursement précédent')

    # ------------------------------------------------------------------
    # Bloc F — Catégorisation sociale
    # ------------------------------------------------------------------
    social_score_ids = fields.One2many('microfinance.loan.application.social.score', 'application_id', string='Catégorisation sociale')

    # ------------------------------------------------------------------
    # Calculs
    # ------------------------------------------------------------------
    def _prior_loans_domain(self):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', PRIOR_LOAN_STATES),
        ]

    @api.depends('partner_id', 'company_id')
    def _compute_loan_sequence_number(self):
        Loan = self.env['microfinance.loan']
        for application in self:
            if not application.partner_id:
                application.loan_sequence_number = 1
                continue
            application.loan_sequence_number = Loan.search_count(application._prior_loans_domain()) + 1

    @api.depends('loan_sequence_number')
    def _compute_is_first_loan(self):
        for application in self:
            application.is_first_loan = application.loan_sequence_number == 1

    @api.depends('loan_sequence_number', 'company_id')
    def _compute_loan_tier(self):
        Tier = self.env['microfinance.loan.application.tier']
        for application in self:
            rank = application.loan_sequence_number or 1
            tier = Tier.search([
                ('sequence_number', '<=', rank),
                '|', ('company_id', '=', False), ('company_id', '=', application.company_id.id),
            ], order='sequence_number desc, company_id desc', limit=1)
            application.loan_tier_id = tier
            application.loan_tier_label = tier.name if tier else _('Prêt n°%s') % rank

    @api.depends('state')
    def _compute_kanban_color(self):
        color_by_state = {
            'draft': 0, 'field_survey': 4, 'analysis': 5, 'committee': 3,
            'ca_review': 2, 'cdag_review': 6, 'accepted': 10,
            'accepted_condition': 8, 'refused': 1, 'loan_created': 7,
        }
        for application in self:
            application.kanban_color = color_by_state.get(application.state, 0)

    @api.depends(
        'income_line_ids.monthly_amount', 'income_line_ids.category', 'income_line_ids.scenario',
        'safety_margin_current', 'safety_margin_forecast',
    )
    def _compute_financial_totals(self):
        weeks_per_month = 52.0 / 12.0
        for application in self:
            lines = application.income_line_ids

            def total(category, scenario):
                return sum(lines.filtered(
                    lambda line: line.category == category and line.scenario == scenario
                ).mapped('monthly_amount'))

            application.total_family_income_current = total('family_income', 'current')
            application.total_family_income_forecast = total('family_income', 'forecast')
            application.total_activity_expense_current = total('activity_expense', 'current')
            # Les dépenses d'activité prévisionnelles ont leurs propres lignes si l'enquêteur en
            # saisit ; à défaut on reconduit les dépenses actuelles.
            forecast_activity = total('activity_expense', 'forecast')
            application.total_activity_expense_forecast = forecast_activity or application.total_activity_expense_current
            # Dépenses familiales : un seul jeu de lignes (actuelles), majorées d'une marge de
            # sécurité différente en actuel (+5%) et en prévisionnel (+10%), fidèle à la fiche
            # papier qui applique un pourcentage plutôt que de redemander le détail.
            family_expense_base = total('family_expense', 'current')
            application.total_family_expense_current = family_expense_base * (1 + application.safety_margin_current / 100.0)
            application.total_family_expense_forecast = family_expense_base * (1 + application.safety_margin_forecast / 100.0)
            application.repayment_capacity_monthly_current = application.total_family_income_current - (
                application.total_activity_expense_current + application.total_family_expense_current)
            application.repayment_capacity_weekly_current = application.repayment_capacity_monthly_current / weeks_per_month
            application.repayment_capacity_monthly_forecast = application.total_family_income_forecast - (
                application.total_activity_expense_forecast + application.total_family_expense_forecast)
            application.repayment_capacity_weekly_forecast = application.repayment_capacity_monthly_forecast / weeks_per_month

    def _compute_counts(self):
        for application in self:
            application.field_visit_count = len(application.field_visit_ids)

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('microfinance.loan.application') or 'Nouveau'
            if vals.get('state') and vals['state'] != 'draft':
                raise UserError(_('Un nouveau dossier d\'instruction doit démarrer à l\'état Brouillon.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals:
            for application in self:
                application._check_state_transition(application.state, vals['state'])
        return super().write(vals)

    def _check_state_transition(self, current, new):
        self.ensure_one()
        if current == new:
            return
        state_labels = dict(self._fields['state'].selection)
        allowed = self.ALLOWED_TRANSITIONS.get(current, set())
        if new not in allowed:
            raise UserError(_(
                'Transition invalide : impossible de passer de "%(current)s" à "%(new)s". '
                'Étape(s) suivante(s) possible(s) : %(allowed)s.'
            ) % {
                'current': state_labels.get(current, current),
                'new': state_labels.get(new, new),
                'allowed': ', '.join(state_labels[state] for state in self.ALLOWED_TRANSITIONS.get(current, set())) or _('aucune'),
            })
        if new == 'loan_created' and not self.env.context.get('application_create_loan'):
            raise UserError(_('Le passage à "Transformé en crédit" se fait uniquement via le bouton "Créer le crédit".'))
        if not self.env.is_superuser() and not self.env.user.has_group('microfinance_loan_management.group_microfinance_manager'):
            required_group = self.STATE_TARGET_GROUP.get(new)
            if required_group and not self.env.user.has_group(required_group):
                raise UserError(_(
                    'Vous n\'avez pas le rôle requis pour amener un dossier à l\'étape "%s".'
                ) % state_labels.get(new, new))
        if new == 'committee':
            self._check_committee_eligibility()

    def _check_committee_eligibility(self):
        """Contrôle d'éligibilité avant soumission au comité. Sans objet pour un premier
        prêt (loan_sequence_number == 1) ; pour un rang supérieur, le contrôle §3bis.4
        (épargne cible du crédit de rang précédent) est branché par le module
        microfinance_savings_management via _check_previous_loan_requirements()."""
        for application in self:
            if application.is_first_loan:
                continue
            application._check_previous_loan_requirements()

    def _check_previous_loan_requirements(self):
        """Hook d'éligibilité pour un dossier de rang > 1 — volontairement vide ici :
        l'implémentation §3bis.4 vit dans microfinance_savings_management (le contrôle
        porte sur savings_target_reached, un champ du module épargne)."""
        self.ensure_one()

    def _get_previous_rank_loan(self):
        """Crédit de rang loan_sequence_number - 1 du même partenaire (comparaison
        systématique au rang précédent, pas au "dernier crédit" de façon vague — utile si
        plusieurs crédits se chevauchent dans le temps). Vide si ce crédit n'existe pas
        dans le système (ex. rang saisi manuellement pour un historique externe)."""
        self.ensure_one()
        Loan = self.env['microfinance.loan']
        if self.loan_sequence_number <= 1 or not self.partner_id:
            return Loan
        prior_loans = Loan.search(self._prior_loans_domain(), order='application_date asc, id asc')
        index = self.loan_sequence_number - 2
        if 0 <= index < len(prior_loans):
            return prior_loans[index]
        return Loan

    # Boutons d'étape du formulaire — la validation (ordre + rôle) est portée par write().
    def action_start_field_survey(self):
        self.write({'state': 'field_survey'})

    def action_start_analysis(self):
        self.write({'state': 'analysis'})

    def action_submit_committee(self):
        self.write({'state': 'committee'})

    def action_ca_review(self):
        self.write({'state': 'ca_review', 'ca_responsible_id': self.env.user.id})

    def action_cdag_review(self):
        self.write({'state': 'cdag_review'})

    def action_accept(self):
        self.write({'state': 'accepted'})

    def action_accept_condition(self):
        self.write({'state': 'accepted_condition'})

    def action_refuse(self):
        self.write({'state': 'refused'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_sync_partner(self):
        """Pousse les champs KYC pertinents du snapshot d'enquête vers la fiche contact.
        Volontairement explicite (bouton) : les données du dossier restent figées au moment
        de l'enquête, la fiche contact n'est jamais mise à jour automatiquement."""
        for application in self:
            values = {}
            if application.partner_phone:
                values['phone'] = application.partner_phone
            if application.partner_current_address:
                values['street'] = application.partner_current_address
            if application.partner_fokontany:
                values['street2'] = application.partner_fokontany
            if not values:
                raise UserError(_('Aucune donnée d\'identité à synchroniser vers la fiche contact.'))
            application.partner_id.write(values)
            application.message_post(body=_(
                'Données d\'identité synchronisées vers la fiche contact %s (téléphone, adresse, fokontany).'
            ) % application.partner_id.display_name)
        return True

    def action_create_loan(self):
        """Ouvre le wizard de transformation en crédit. Le produit est choisi manuellement
        par l'agent à cette étape (jamais deviné automatiquement) ; toute la logique
        d'approbation/décaissement reste sur microfinance.loan."""
        self.ensure_one()
        if self.state not in ('accepted', 'accepted_condition'):
            raise UserError(_('Le crédit ne peut être créé que pour un dossier accepté (avec ou sans condition).'))
        if self.loan_id:
            raise UserError(_('Un crédit a déjà été créé pour ce dossier : %s.') % self.loan_id.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Créer le crédit'),
            'res_model': 'microfinance.loan.application.create.loan.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_view_loan(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'microfinance.loan',
            'view_mode': 'form',
            'res_id': self.loan_id.id,
        }
