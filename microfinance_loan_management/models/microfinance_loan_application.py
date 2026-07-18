# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

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
    loan_product_id = fields.Many2one(
        'microfinance.loan.product', string='Produit de prêt', required=True, tracking=True,
        domain="[('company_id', '=', company_id)]",
        help="Produit visé par ce dossier, choisi dès l'instruction (pré-rempli à la "
             "création du crédit, modifiable à cette étape). Sert aussi au calcul "
             "d'éligibilité informative des programmes progressifs.",
    )
    company_logo = fields.Binary(related='company_id.logo', string='Logo agence', readonly=True)
    survey_start_time = fields.Char(string="Heure début enquête")
    survey_end_time = fields.Char(string="Heure fin enquête")
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
    progressive_eligibility_status = fields.Selection([
        ('not_applicable', 'Non applicable'),
        ('no_prior_loan', 'Aucun prêt antérieur'),
        ('prior_active', 'Prêt précédent en cours'),
        ('eligible', 'Éligible'),
        ('warning', 'Avertissement'),
        ('defaulted', 'Défaut'),
    ], string='Éligibilité programme progressif', compute='_compute_progressive_eligibility',
        help='Purement informatif : ne bloque jamais la soumission ni la validation du '
             'dossier. La décision d\'octroi reste toujours à la commission de crédit / '
             'au valideur (cf. _check_eligibility sur microfinance.loan, jamais '
             'modifié par ce champ).',
    )
    progressive_eligibility_message = fields.Char(
        string='Message éligibilité programme progressif', compute='_compute_progressive_eligibility')

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
    dependent_count = fields.Integer(string='Nombre de personnes à charge', compute='_compute_counts')
    guarantor_line_ids = fields.One2many('microfinance.loan.application.guarantor.line', 'application_id', string='Garants')
    guarantor_count = fields.Integer(string='Nombre de garants', compute='_compute_counts')
    primary_guarantor_name = fields.Char(string='Garant principal', compute='_compute_counts')
    document_line_ids = fields.One2many('microfinance.loan.application.document.line', 'application_id', string='Documents administratifs fournis')
    document_provided_count = fields.Integer(string='Documents fournis', compute='_compute_counts')
    document_missing_count = fields.Integer(string='Documents manquants', compute='_compute_counts')
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

    # Plan de financement — lignes détaillées (fiche papier), total calculé par somme des
    # lignes plutôt que saisi librement.
    funding_plan_raw_materials_current = fields.Monetary(string='Matières premières (actuel)')
    funding_plan_merchandise_current = fields.Monetary(string='Marchandises (actuel)')
    funding_plan_available_cash_current = fields.Monetary(string='Argent disponible (actuel)')
    funding_plan_current_total = fields.Monetary(
        string='Plan de financement (actuel)', compute='_compute_funding_plan_totals', store=True)
    funding_plan_equipment_forecast = fields.Monetary(string='Matériel-Mobilier-Équipement (prévisionnel)')
    funding_plan_raw_materials_forecast = fields.Monetary(string='Matières premières (prévisionnel)')
    funding_plan_merchandise_forecast = fields.Monetary(string='Marchandises (prévisionnel)')
    funding_plan_forecast_total = fields.Monetary(
        string='Plan de financement (prévisionnel)', compute='_compute_funding_plan_totals', store=True)

    # Suivi de l'augmentation du capital/stock (fiche papier, dossier de rang > 1).
    capital_increase = fields.Boolean(string='Augmentation du capital (ou stock)')
    capital_before_previous_loan = fields.Monetary(string='Capital avant le prêt précédent')
    capital_currently_observed = fields.Monetary(string='Dûment constaté actuellement')
    capital_currently_confirmed = fields.Monetary(string='Constaté actuellement')
    previous_loan_fund_usage = fields.Text(string='Utilisation du dernier crédit (suivi de fonds)')

    # ------------------------------------------------------------------
    # Section VI — Fiche de catégorisation sociale (VAD/VAV)
    # ------------------------------------------------------------------
    field_visit_ids = fields.One2many('microfinance.loan.application.field.visit', 'application_id', string='Visites terrain (VAD/VAV)')
    field_visit_count = fields.Integer(string='Nombre de visites', compute='_compute_counts')

    # ------------------------------------------------------------------
    # Section VI (suite) — Fiche de catégorisation sociale : grille de points
    # ------------------------------------------------------------------
    household_size = fields.Integer(string='Taille du ménage')
    members_over_14 = fields.Integer(string='Nb de membres > 14 ans')
    members_under_14 = fields.Integer(string='Nb de membres < 14 ans')
    consumption_units = fields.Float(
        string='Unité de consommation (UC)', compute='_compute_consumption_units', store=True,
        help='1 (1er adulte) + 0,5 × (membres > 14 ans restants) + 0,3 × (membres < 14 ans).',
    )

    assets_score = fields.Integer(string='Actifs / Patrimoine (1-4)')
    assets_exact_amount = fields.Monetary(string='Actifs : montant exact')
    activity_score = fields.Integer(string='Activité (1-4)')
    income_score = fields.Integer(string='Revenus - bénéfice net du ménage (1-4)')
    income_net_benefit_amount = fields.Monetary(string='Revenus : montant BN')
    food_score = fields.Integer(string='Alimentation (1-4)')
    health_score = fields.Integer(string='Santé (1-4)')
    housing_state_score = fields.Integer(string='Habitat : état du toit (0-2)')
    housing_surface_score = fields.Integer(string='Habitat : surface par membre (0-2)')
    housing_score = fields.Integer(
        string='Habitat total (0-4)', compute='_compute_housing_score', store=True,
        help='Somme état + surface, hypothèse de calcul à confirmer avec CEFOR si erronée.',
    )
    education_borrower_score = fields.Integer(string="Niveau d'éducation du candidat (0-4)")
    education_children_score = fields.Integer(string='Éducation des enfants (1-4)')

    savings_amount = fields.Monetary(string='Épargne (montant)')
    savings_score = fields.Integer(string='Épargne (1-4, optionnel)')
    administrative_score = fields.Integer(string='Administratif (1-4, optionnel)')
    surveyor_impression_score = fields.Integer(
        string="Impression personnelle de l'enquêteur",
        help="Note libre de 1 à 4, jamais recalculée. Hypothèse d'échelle par défaut "
             '(1-4, alignée sur les autres catégories) — à confirmer avec CEFOR si une '
             'échelle différente est utilisée en pratique.',
    )

    total_points = fields.Integer(string='Total points ménage', compute='_compute_total_points', store=True)
    social_level_id = fields.Many2one(
        'microfinance.social.category.level', string='Niveau du ménage',
        compute='_compute_total_points', store=True,
    )

    surveyor_level_impression = fields.Text(string="Impression personnelle sur le niveau du ménage")
    is_eligible = fields.Selection([
        ('yes', 'Oui'), ('no', 'Non'), ('tbd', 'À déterminer'),
    ], string='Le ménage peut-il recevoir un prêt CEFOR ?', default='tbd',
       help="Saisie manuelle pour l'instant — sera reconnecté à la logique de seuil/comité "
            'de crédit une fois ce chantier lancé (actuellement en standby).')

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

    # Statuts du plus favorable (eligible) au moins favorable (defaulted) : quand plusieurs
    # prêts existent sur le produit précédent, le statut global retient le plus favorable
    # au client (cf. prompt programme progressif, Lot 2).
    _PROGRESSIVE_STATUS_RANK = {'defaulted': 0, 'prior_active': 1, 'warning': 2, 'eligible': 3}

    @api.depends('loan_product_id', 'partner_id')
    def _compute_progressive_eligibility(self):
        Step = self.env['microfinance.loan.progressive.program.step']
        for application in self:
            product = application.loan_product_id
            current_step = product.progressive_step_ids[:1] if product else Step
            if not current_step or current_step.sequence_number <= 1:
                application.progressive_eligibility_status = 'not_applicable'
                application.progressive_eligibility_message = False
                continue
            prior_step = Step.sudo().search([
                ('program_id', '=', current_step.program_id.id),
                ('sequence_number', '=', current_step.sequence_number - 1),
            ], limit=1)
            if not prior_step:
                application.progressive_eligibility_status = 'not_applicable'
                application.progressive_eligibility_message = False
                continue
            if not application.partner_id:
                application.progressive_eligibility_status = 'no_prior_loan'
                application.progressive_eligibility_message = _(
                    'Aucun prêt antérieur trouvé sur le produit prérequis (%s) — '
                    "vérifier l'historique du client avant octroi."
                ) % prior_step.product_id.name
                continue
            # Le parcours client est évalué tous établissements confondus (cross-agency,
            # sudo() nécessaire car le client peut avoir pris son premier prêt dans une
            # agence et demander le suivant dans une autre) — même exception documentée
            # que la matrice fonds bailleurs (microfinance_fond_credit.py).
            prior_loans = self.env['microfinance.loan'].sudo().search([
                ('partner_id', '=', application.partner_id.id),
                ('product_id', '=', prior_step.product_id.id),
            ])
            status, message = application._evaluate_progressive_eligibility(prior_loans, prior_step)
            application.progressive_eligibility_status = status
            application.progressive_eligibility_message = message

    def _evaluate_progressive_eligibility(self, prior_loans, prior_step):
        self.ensure_one()
        if not prior_loans:
            return 'no_prior_loan', _(
                'Aucun prêt antérieur trouvé sur le produit prérequis (%s) — vérifier '
                "l'historique du client avant octroi."
            ) % prior_step.product_id.name
        best = None
        for loan in prior_loans:
            result = self._evaluate_progressive_loan(loan, prior_step)
            if best is None or self._PROGRESSIVE_STATUS_RANK[result[0]] > self._PROGRESSIVE_STATUS_RANK[best[0]]:
                best = result
        return best

    def _evaluate_progressive_loan(self, loan, prior_step):
        self.ensure_one()
        product_name = prior_step.product_id.name
        if loan.state in ('defaulted', 'written_off'):
            return 'defaulted', _(
                'Prêt précédent (%s) radié ou en défaut — vérifier avant octroi.'
            ) % product_name
        if loan.state != 'closed':
            state_label = dict(loan._fields['state'].selection).get(loan.state, loan.state)
            return 'prior_active', _(
                'Prêt précédent (%(product)s) pas encore clôturé (état : %(state)s).'
            ) % {'product': product_name, 'state': state_label}

        # Retard historique : les métriques de scoring (overdue_amount, _get_max_overdue_days)
        # reflètent l'état COURANT des échéances, toujours à 0 sur un prêt clôturé (soldé en
        # entier). On reconstitue donc le retard constaté pendant la vie du prêt à partir de
        # arrears_onset_date/arrears_cured_date, posés une fois pour toutes sur chaque échéance
        # (cf. microfinance_loan_installment.py), plutôt que de dupliquer un nouveau calcul.
        late_installments = loan.installment_ids.filtered('arrears_onset_date')
        today = fields.Date.context_today(self)
        max_days = max(
            ((line.arrears_cured_date or today) - line.arrears_onset_date).days
            for line in late_installments
        ) if late_installments else 0
        late_amount = sum(late_installments.mapped('total_amount'))
        late_ratio = loan.loan_amount and (late_amount / loan.loan_amount * 100.0) or 0.0

        date_suffix = loan.closed_date and (_(' le %s') % loan.closed_date.strftime('%d/%m/%Y')) or ''
        if max_days <= prior_step.late_tolerance_days and late_ratio <= prior_step.late_tolerance_amount_percent:
            return 'eligible', _(
                'Prêt précédent (%(product)s) clôturé%(date)s sans retard significatif.'
            ) % {'product': product_name, 'date': date_suffix}
        return 'warning', _(
            'Prêt précédent (%(product)s) clôturé%(date)s avec %(days)s jour(s) de retard '
            'maximum constatés (tolérance configurée : %(tolerance)s jours).'
        ) % {
            'product': product_name, 'date': date_suffix,
            'days': max_days, 'tolerance': prior_step.late_tolerance_days,
        }

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

    @api.depends('field_visit_ids', 'dependent_ids', 'guarantor_line_ids', 'document_line_ids.is_provided')
    def _compute_counts(self):
        for application in self:
            application.field_visit_count = len(application.field_visit_ids)
            application.dependent_count = len(application.dependent_ids)
            application.guarantor_count = len(application.guarantor_line_ids)
            application.primary_guarantor_name = application.guarantor_line_ids[:1].name or False
            provided = len(application.document_line_ids.filtered('is_provided'))
            application.document_provided_count = provided
            application.document_missing_count = len(application.document_line_ids) - provided

    @api.depends(
        'funding_plan_raw_materials_current', 'funding_plan_merchandise_current',
        'funding_plan_available_cash_current', 'funding_plan_equipment_forecast',
        'funding_plan_raw_materials_forecast', 'funding_plan_merchandise_forecast',
    )
    def _compute_funding_plan_totals(self):
        for application in self:
            application.funding_plan_current_total = (
                application.funding_plan_raw_materials_current
                + application.funding_plan_merchandise_current
                + application.funding_plan_available_cash_current
            )
            application.funding_plan_forecast_total = (
                application.funding_plan_equipment_forecast
                + application.funding_plan_raw_materials_forecast
                + application.funding_plan_merchandise_forecast
            )

    @api.depends('members_over_14', 'members_under_14')
    def _compute_consumption_units(self):
        """Hypothèse de calcul (non garantie à 100% par la fiche papier) : le 1er adulte
        compte pour 1 unité et est déjà inclus dans members_over_14 — il est donc retiré
        du multiplicateur 0,5 appliqué aux membres > 14 ans restants."""
        for application in self:
            over_14 = application.members_over_14 or 0
            under_14 = application.members_under_14 or 0
            application.consumption_units = 1 + 0.5 * max(over_14 - 1, 0) + 0.3 * under_14

    @api.depends('housing_state_score', 'housing_surface_score')
    def _compute_housing_score(self):
        """Somme simple état du toit + surface par membre — hypothèse de calcul à
        confirmer avec CEFOR si erronée."""
        for application in self:
            application.housing_score = (application.housing_state_score or 0) + (application.housing_surface_score or 0)

    @api.depends(
        'assets_score', 'activity_score', 'income_score', 'food_score', 'health_score',
        'housing_score', 'education_borrower_score', 'education_children_score',
        'savings_score', 'administrative_score', 'surveyor_impression_score', 'company_id',
        'company_id.microfinance_social_grid_include_savings',
        'company_id.microfinance_social_grid_include_administrative',
        'company_id.microfinance_social_grid_include_impression_in_total',
    )
    def _compute_total_points(self):
        Level = self.env['microfinance.social.category.level']
        for application in self:
            company = application.company_id
            total = (
                (application.assets_score or 0) + (application.activity_score or 0)
                + (application.income_score or 0) + (application.food_score or 0)
                + (application.health_score or 0) + (application.housing_score or 0)
                + (application.education_borrower_score or 0) + (application.education_children_score or 0)
            )
            if company.microfinance_social_grid_include_savings:
                total += application.savings_score or 0
            if company.microfinance_social_grid_include_administrative:
                total += application.administrative_score or 0
            if company.microfinance_social_grid_include_impression_in_total:
                total += application.surveyor_impression_score or 0
            application.total_points = total
            # Barème propre à la société d'abord, barème commun (company_id vide) en repli —
            # évite de dépendre de l'ordre de tri PostgreSQL sur les NULL de company_id.
            level = Level.search([
                ('min_points', '<=', total), ('max_points', '>=', total),
                ('company_id', '=', company.id),
            ], limit=1)
            if not level:
                level = Level.search([
                    ('min_points', '<=', total), ('max_points', '>=', total),
                    ('company_id', '=', False),
                ], limit=1)
            application.social_level_id = level

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                # agency_code est obligatoire sur res.company (NOT NULL) : toute société valide
                # en possède un, pas besoin de re-vérifier ici.
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                number = company._get_or_create_numbering_sequence('microfinance.loan.application.agency')
                vals['name'] = '%s/%s' % (company.agency_code, number)
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
        """Hook d'éligibilité pour un dossier de rang > 1. Le contrôle §3bis.4 (épargne
        cible du crédit de rang précédent) est branché par microfinance_savings_management
        (porte sur savings_target_reached, un champ du module épargne). Contrôle natif à ce
        module : impression personnelle de l'enquêteur sur le dossier précédent, actif
        seulement si microfinance_social_grid_include_impression_next_loan est coché sur
        la société — appel à super() nécessaire pour toute future surcharge côté épargne."""
        self.ensure_one()
        company = self.company_id
        if company.microfinance_social_grid_include_impression_next_loan:
            previous_application = self._get_previous_rank_application()
            threshold = company.microfinance_social_grid_impression_next_loan_min_score
            if previous_application and previous_application.surveyor_impression_score < threshold:
                raise UserError(_(
                    'Le dossier précédent (%(name)s) a une impression personnelle de '
                    "l'enquêteur (%(score)s) inférieure au seuil requis (%(threshold)s) pour "
                    'soumettre ce nouveau dossier au comité.'
                ) % {
                    'name': previous_application.name,
                    'score': previous_application.surveyor_impression_score,
                    'threshold': threshold,
                })

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

    def _get_previous_rank_application(self):
        """Dossier d'instruction de rang loan_sequence_number - 1 du même partenaire —
        pendant de _get_previous_rank_loan() mais sur microfinance.loan.application :
        microfinance.loan n'a aucun lien retour vers le dossier d'instruction qui l'a
        produit, or c'est ce dossier (pas le crédit) qui porte surveyor_impression_score.
        Vide si ce dossier n'existe pas dans le système."""
        self.ensure_one()
        Application = self.env['microfinance.loan.application']
        if self.loan_sequence_number <= 1 or not self.partner_id:
            return Application
        prior_applications = Application.search([
            ('company_id', '=', self.company_id.id),
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'loan_created'),
        ], order='application_date asc, id asc')
        index = self.loan_sequence_number - 2
        if 0 <= index < len(prior_applications):
            return prior_applications[index]
        return Application

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

    # ------------------------------------------------------------------
    # Boutons "Modifier" des résumés en lecture seule (Lot 1) — ouvrent chacun le
    # wizard popup dédié à leur section (Lots 2-3).
    # ------------------------------------------------------------------
    def action_open_partner_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Modifier l'identification du partenaire",
            'res_model': 'microfinance.loan.application.partner.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_guarantor_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modifier les garants',
            'res_model': 'microfinance.loan.application.guarantor.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_document_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modifier les documents administratifs fournis',
            'res_model': 'microfinance.loan.application.document.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_activity_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Modifier l'analyse de l'activité",
            'res_model': 'microfinance.loan.application.activity.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_financial_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Modifier l'analyse financière",
            'res_model': 'microfinance.loan.application.financial.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_social_grid_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modifier la grille de catégorisation sociale',
            'res_model': 'microfinance.loan.application.social.grid.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_field_visit_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modifier les visites terrain',
            'res_model': 'microfinance.loan.application.field.visit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }

    def action_open_ca_cdag_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modifier les avis CA et CDAG',
            'res_model': 'microfinance.loan.application.ca.cdag.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id},
        }


class MicrofinanceLoanApplicationDependent(models.Model):
    """Section I — Enfants et personnes à charge du partenaire."""
    _name = 'microfinance.loan.application.dependent'
    _description = 'Enfant ou personne à charge (dossier de crédit)'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    name = fields.Char(string='Nom', required=True)
    relationship = fields.Selection([
        ('child', 'Enfant'),
        ('other_dependent', 'Autre personne à charge'),
    ], string='Lien de parenté', required=True, default='child')
    birth_date = fields.Date(string='Date de naissance')
    occupation = fields.Char(string='Occupation / École')


class MicrofinanceLoanApplicationGuarantorLine(models.Model):
    """Section II — Identification du garant."""
    _name = 'microfinance.loan.application.guarantor.line'
    _description = 'Garant (dossier de crédit)'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Garant (fiche contact)')
    name = fields.Char(string='Nom', required=True)
    id_card_number = fields.Char(string='N° CIN')
    address = fields.Char(string='Adresse')
    phone = fields.Char(string='Téléphone')
    profession = fields.Char(string='Profession')
    relationship_to_borrower = fields.Char(string="Lien avec l'emprunteur")


class MicrofinanceLoanApplicationDocumentLine(models.Model):
    """Section III — Dossiers administratifs fournis."""
    _name = 'microfinance.loan.application.document.line'
    _description = 'Document administratif fourni (dossier de crédit)'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    name = fields.Char(string='Document', required=True)
    is_provided = fields.Boolean(string='Fourni')
    comment = fields.Char(string='Commentaire')


class MicrofinanceLoanApplicationIncomeLine(models.Model):
    """Section V — Analyse financière : lignes de revenus/dépenses."""
    _name = 'microfinance.loan.application.income.line'
    _description = 'Ligne revenus/dépenses (dossier de crédit)'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)
    category = fields.Selection([
        ('family_income', 'Revenu familial'),
        ('activity_expense', "Dépense d'activité"),
        ('family_expense', 'Dépense familiale'),
    ], string='Catégorie', required=True)
    scenario = fields.Selection([
        ('current', 'Actuel'),
        ('forecast', 'Prévisionnel'),
    ], string='Scénario', required=True, default='current')
    name = fields.Char(string='Libellé', required=True)
    monthly_amount = fields.Monetary(string='Montant mensuel', required=True)


class MicrofinanceLoanApplicationFieldVisit(models.Model):
    """Section VI — Fiche de catégorisation sociale : visites terrain (VAD/VAV).

    Chaque type de visite (domicile ou lieu de vente) est réalisé une première fois par un
    agent, puis contre-vérifié le même jour par un second agent indépendant (Contre-VAD /
    Contre-VAV), conformément à la fiche papier CEFOR (dossier réf. 7140, agence IS)."""
    _name = 'microfinance.loan.application.field.visit'
    _description = 'Visite terrain (VAD/VAV) — Section VI'
    _order = 'visit_date, id'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)

    visit_type = fields.Selection([
        ('home', 'Visite à domicile (VAD)'),
        ('sales_point', 'Visite au lieu de vente (VAV)'),
    ], string='Type de visite', required=True)

    is_counter_visit = fields.Boolean(string='Contre-visite')
    counter_visit_of_id = fields.Many2one(
        'microfinance.loan.application.field.visit', string='Contre-visite de',
        domain="[('application_id', '=', application_id), ('visit_type', '=', visit_type), ('is_counter_visit', '=', False)]",
        help="Renseigné uniquement si la case Contre-visite est cochée : référence la visite "
             "initiale du même type que celle-ci contre-vérifie.",
    )

    agent_id = fields.Many2one('res.users', string='Effectué par', required=True)
    visit_date = fields.Date(string='Date', required=True, default=fields.Date.context_today)

    # Champs spécifiques VAD
    constats = fields.Text(string='Constats')
    neighborhood_reputation = fields.Text(string='Réputation dans le quartier (recoupement moral)')

    # Champs spécifiques VAV
    project_exists = fields.Boolean(string='Existence du projet (lieu de vente)')
    potential_clients_level = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Élevée'),
    ], string='Existence des clients potentiels')
    stock_value = fields.Monetary(string='Valeur du stock')
    competition_level = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Élevée'),
    ], string='Concurrence')
    product_presentation = fields.Selection([
        ('low', 'Basse'), ('medium', 'Moyenne'), ('high', 'Bonne'),
    ], string='Présentation des produits')
    commercial_attitude = fields.Selection([
        ('bad', 'Mauvaise'), ('medium', 'Moyenne'), ('good', 'Bonne'),
    ], string='Attitude commerciale')

    @api.constrains('is_counter_visit', 'counter_visit_of_id', 'visit_type')
    def _check_counter_visit_reference(self):
        for visit in self:
            if not visit.is_counter_visit:
                continue
            if not visit.counter_visit_of_id:
                raise ValidationError(_(
                    'Une contre-visite doit référencer la visite initiale qu\'elle contre-vérifie.'
                ))
            if visit.counter_visit_of_id.visit_type != visit.visit_type:
                raise ValidationError(_(
                    'La contre-visite doit être du même type (VAD ou VAV) que la visite '
                    'initiale référencée.'
                ))

    @api.constrains('is_counter_visit', 'agent_id', 'counter_visit_of_id')
    def _check_counter_visit_independent_agent(self):
        for visit in self:
            if (
                visit.is_counter_visit
                and visit.counter_visit_of_id
                and visit.agent_id == visit.counter_visit_of_id.agent_id
            ):
                raise ValidationError(_(
                    'La contre-visite doit être réalisée par un agent différent de celui de '
                    'la visite initiale (contrôle indépendant).'
                ))
