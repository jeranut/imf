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
    name = fields.Char(
        string='Référence dossier', related='partner_id.microfinance_account_number', store=True,
        readonly=True, copy=False, tracking=True,
        help="Reprend le numéro de compte permanent du client (res.partner) : la même "
             "référence apparaît sur tous les dossiers de ce client, ce n'est plus un numéro "
             "propre à ce dossier.",
    )
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
    # Pagination de la fiche d'enquête (3 pages, cf. _SURVEY_PAGES ci-dessous pour l'ordre de
    # navigation) : totalement indépendante de state, navigable librement même sur un dossier
    # déjà validé ou clôturé — un futur découpage plus fin en davantage de pages reste possible
    # sans casser ce mécanisme (ajout de nouvelles valeurs de sélection + _SURVEY_PAGES).
    survey_page = fields.Selection([
        ('partner_identification', 'Page 1'),
        ('guarantor_documents_activity', 'Page 2'),
        ('financial_visits_ca_cdag', 'Page 3'),
    ], string="Page de la fiche d'enquête", default='partner_identification', copy=False)
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
    # Synchronisé depuis res.partner (client + conjoint) tant que le dossier est en cours
    # (draft/field_survey) : cf. _compute_kyc_from_partner (section Calculs ci-dessous). Gelé
    # dès le passage en analysis et au-delà (plus aucune resynchronisation, valeurs figées pour
    # l'audit) — sauf partner_current_address et partner_phone, volontairement en dehors de ce
    # mécanisme (toujours éditables, jamais recalculés ni gelés, simple pré-remplissage à la
    # création, cf. create()/_onchange_partner_id_prefill_contact_fields ci-dessous).
    partner_surname = fields.Char(
        string='Nom de famille', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_nickname = fields.Char(
        string='Surnom',
        help="Aucun champ équivalent sur la fiche client : toujours saisi manuellement, jamais "
             "synchronisé — gelé comme le reste du Bloc A une fois le dossier hors instruction.",
    )
    partner_id_card_number = fields.Char(
        string='N° CIN', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_id_card_issue_date = fields.Date(
        string='CIN délivrée le', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_id_card_issue_place = fields.Char(
        string='CIN délivrée à', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_id_card_duplicate_date = fields.Date(
        string='Duplicata délivré le',
        help="Aucun champ équivalent sur la fiche client : toujours saisi manuellement, jamais "
             "synchronisé — gelé comme le reste du Bloc A une fois le dossier hors instruction.",
    )
    partner_id_card_duplicate_place = fields.Char(
        string='Duplicata délivré à',
        help="Aucun champ équivalent sur la fiche client : toujours saisi manuellement, jamais "
             "synchronisé — gelé comme le reste du Bloc A une fois le dossier hors instruction.",
    )
    # Changement d'adresse constaté / distance domicile-agence : constat fait par l'enquêteur au
    # moment de la visite (pas une information de contact à tenir à jour en continu comme
    # partner_current_address/partner_phone) — suit donc le gel normal du Bloc A, pas le régime
    # d'exception adresse/téléphone.
    partner_address_changed = fields.Boolean(
        string="Changement d'adresse du partenaire",
        help="Constat fait par l'enquêteur au moment de la visite : aucun champ équivalent sur "
             "la fiche client, toujours saisi manuellement, gelé comme le reste du Bloc A.",
    )
    partner_current_address = fields.Char(string='Adresse actuelle')
    partner_fokontany = fields.Char(
        string='Fokontany', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_address_since = fields.Date(
        string="À cette adresse depuis",
        help="Aucun champ équivalent sur la fiche client (ni sur celle du conjoint) : toujours "
             "saisi manuellement, jamais synchronisé ni gelé.",
    )
    partner_housing_status = fields.Selection([
        ('owner_inheritance', 'Propriétaire (héritage)'),
        ('owner_purchase', 'Propriétaire (achat)'),
        ('owner_donation', 'Propriétaire (donation)'),
        ('tenant_free', 'Locataire sans loyer'),
        ('tenant_paying', 'Locataire avec loyer'),
    ], string="Statut d'occupation du logement",
        compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_agency_distance_km = fields.Integer(
        string="Distance domicile-agence (km)",
        help="Aucun champ équivalent trouvé sur la fiche client ni ailleurs dans le module "
             "(vérifié). Constat fait par l'enquêteur : toujours saisi manuellement, gelé "
             "comme le reste du Bloc A.",
    )
    partner_phone = fields.Char(string='Téléphone')
    # Qualifie directement partner_phone (à qui appartient ce numéro) : suit le même régime
    # d'exception (toujours modifiable), pour ne jamais devenir incohérent avec un numéro déjà
    # modifié après le gel (ex. numéro remplacé par celui d'un voisin après coup).
    partner_phone_type = fields.Selection([
        ('personal', 'Personnel'), ('neighbor', 'Voisin'), ('other', 'Autre'),
    ], string='Type de téléphone')
    partner_phone_type_detail = fields.Char(string='Précisez')
    partner_reference_contact_name = fields.Char(
        string='Personne de référence', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_reference_contact_phone = fields.Char(
        string='Téléphone de la référence', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_birth_date = fields.Date(
        string='Date de naissance', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_birth_place = fields.Char(
        string='Lieu de naissance', compute='_compute_kyc_from_partner', store=True, readonly=False)
    partner_marital_status = fields.Selection([
        ('single', 'Célibataire'),
        ('married', 'Marié(e)'),
        ('cohabiting', 'Union libre'),
        ('divorced', 'Divorcé(e)'),
        ('widowed', 'Veuf / Veuve'),
    ], string='Situation matrimoniale', compute='_compute_kyc_from_partner', store=True, readonly=False)

    # Champs conjoint : lus via partner_id.microfinance_spouse_id (le conjoint est déjà un
    # contact res.partner complet, jamais dupliqué sur le client — cf. décision confirmée avec
    # Micka lors du correctif de synchronisation du Bloc A).
    spouse_name = fields.Char(
        string='Nom du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_id_card_number = fields.Char(
        string='CIN du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_id_card_issue_date = fields.Date(
        string='CIN du conjoint délivrée le', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_id_card_issue_place = fields.Char(
        string='CIN du conjoint délivrée à', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_address = fields.Char(
        string='Adresse du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_fokontany = fields.Char(
        string='Fokontany du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_profession = fields.Char(
        string='Profession du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_employer = fields.Char(
        string='Employeur du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    spouse_phone = fields.Char(
        string='Téléphone du conjoint', compute='_compute_kyc_from_partner', store=True, readonly=False)
    union_duration = fields.Char(
        string="Durée de l'union",
        help="Aucune date de mariage/union sur la fiche client ou celle du conjoint : toujours "
             "saisi manuellement, jamais synchronisé ni gelé.",
    )

    dependent_ids = fields.One2many('microfinance.loan.application.dependent', 'application_id', string='Enfants et personnes à charge')
    # Distinct de dependent_count (total des lignes, enfants + autres personnes à charge, déjà
    # existant et utilisé sur le formulaire principal) : la fiche papier CEFOR veut
    # spécifiquement le nombre d'ENFANTS (Lien de parenté = Enfant), d'où ces deux champs
    # séparés plutôt qu'une redéfinition de dependent_count.
    children_count = fields.Integer(
        string="Nombre d'enfants", compute='_compute_children_counts', store=True,
        help="Calculé automatiquement à partir du tableau ci-dessous (lignes avec Lien de "
             "parenté = Enfant), pour éviter toute incohérence entre ce résumé et le détail.",
    )
    children_schooled_count = fields.Integer(
        string="Nombre d'enfants scolarisés", compute='_compute_children_counts', store=True,
        help="Nombre d'enfants (Lien de parenté = Enfant) dont l'École est renseignée dans le "
             "tableau ci-dessous.",
    )
    dependent_count = fields.Integer(string='Nombre de personnes à charge', compute='_compute_counts')
    # Garant unique par dossier (confirmé avec Micka) : champs directs sur le dossier, comme
    # partner_/spouse_ pour le Bloc A, plutôt qu'un modèle de ligne séparé pour un seul
    # enregistrement — abandon de l'architecture wizard/modèle-ligne (cf. STATUS.md, décision du
    # 2026-07-18). guarantor_partner_id n'est jamais gelé (identité du garant, comme partner_id
    # lui-même) ; guarantor_address/guarantor_profession suivent le même gel que le Bloc A
    # (compute/store/readonly=False, figés hors draft/field_survey) ; guarantor_phone reste
    # toujours modifiable (même exception que partner_phone) ; les autres champs sont saisis à
    # la main (aucun équivalent sur res.partner) et gelés uniquement via la vue (comme
    # partner_nickname).
    guarantor_partner_id = fields.Many2one('res.partner', string='Nom et prénom')
    guarantor_id_card_number = fields.Char(string='N° CIN')
    guarantor_id_card_issue_date = fields.Date(string='CIN délivrée le')
    guarantor_id_card_issue_place = fields.Char(string='CIN délivrée à')
    guarantor_id_card_duplicate_date = fields.Date(string='Duplicata délivré le')
    guarantor_id_card_duplicate_place = fields.Char(string='Duplicata délivré à')
    guarantor_address = fields.Char(
        string='Adresse', compute='_compute_guarantor_kyc_from_partner', store=True, readonly=False)
    guarantor_fokontany = fields.Char(string='Fokontany')
    guarantor_profession = fields.Char(
        string='Profession', compute='_compute_guarantor_kyc_from_partner', store=True, readonly=False)
    guarantor_employer = fields.Char(string='Employeur')
    guarantor_phone = fields.Char(
        string='Téléphone', compute='_compute_guarantor_phone', store=True, readonly=False)
    guarantor_relationship_with_borrower = fields.Char(string='Lien avec le partenaire')
    guarantor_surveyor_comment = fields.Text(string="Commentaire de l'enquêteur")
    guarantor_count = fields.Integer(string='Nombre de garants', compute='_compute_counts')
    primary_guarantor_name = fields.Char(string='Garant principal', compute='_compute_counts')
    # Pré-remplis automatiquement à la création du dossier (cf. create() ci-dessous) : "Photo
    # d'identité" volontairement exclue de cette liste, déjà couverte par le champ photo natif
    # de res.partner (image_1920), pas besoin de la suivre une deuxième fois ici.
    _DEFAULT_DOCUMENT_TYPES = ('Copie CIN', 'Certificat de résidence – 3 mois')
    document_line_ids = fields.One2many('microfinance.loan.application.document.line', 'application_id', string='Documents administratifs fournis')
    document_provided_count = fields.Integer(string='Documents fournis', compute='_compute_counts')
    document_missing_count = fields.Integer(string='Documents manquants', compute='_compute_counts')
    surveyor_comment = fields.Text(string="Commentaire de l'enquêteur")

    # ------------------------------------------------------------------
    # Bloc B — Analyse de viabilité de l'activité
    # ------------------------------------------------------------------
    activity_description = fields.Text(string="Description de l'activité")
    activity_id = fields.Many2one(
        'microfinance.loan.application.activity', string='Activité',
        help="Sélection dans le référentiel configuré (Configuration > Activités). Une "
             "nouvelle activité peut être créée directement ici si elle n'existe pas encore "
             "(code + nom + catégorie existante) — jamais de nouvelle catégorie depuis ce "
             "point, seulement depuis Configuration.",
    )
    activity_sector_id = fields.Many2one(
        'microfinance.loan.application.activity.category', string="Secteur d'activité",
        compute='_compute_activity_sector_id', store=True, readonly=True,
        help="Catégorie de l'activité sélectionnée : jamais saisi manuellement, toujours "
             "dérivé de activity_id.",
    )
    sale_location_status = fields.Selection([
        ('owner', 'Propriétaire'),
        ('tenant', 'Locataire'),
    ], string='Statut du lieu')
    sale_location_type = fields.Selection([
        ('fixed', 'Fixe'),
        ('mobile', 'Mobile'),
        ('ambulant', 'Ambulant'),
        ('delivery', 'Livraison'),
    ], string='Type du lieu')
    sale_location_enclosed = fields.Selection([
        ('open', 'Ouvert'),
        ('closed', 'Fermé'),
    ], string='Lieu de vente : fermé/ouvert', default='open')
    formalization_level = fields.Selection([
        ('informal', 'Informel'),
        ('fokontany_authorization', 'Autorisation fokontany'),
        ('patente', 'Patente'),
        ('statistical_card', 'Carte statistique'),
        ('trade_register', 'Registre du commerce'),
    ], string='Niveau de formalisation')
    activity_start_date = fields.Date(string="Début de l'activité")
    activity_duration = fields.Char(
        string="Durée de l'activité", compute='_compute_activity_duration',
        help="Calculée à partir de la date de début et d'aujourd'hui : jamais stockée, pour "
             "rester exacte dans le temps (recalculée à chaque affichage).",
    )
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
    # Champs dédiés par tableau (un par catégorie × situation), même méthodologie que
    # document_line_ids (Section III) : un champ à usage unique par tableau affiché, filtre
    # intégré dans la définition du champ (domain Python), pas seulement dans la vue — plutôt
    # que de réutiliser income_line_ids 6 fois avec un domaine différent à chaque occurrence
    # (source probable des soucis d'édition/affichage rencontrés). income_line_ids reste la
    # source unique pour les calculs de totaux et le pré-remplissage ; ces 6 champs ne sont que
    # des vues filtrées de la même table, jamais une deuxième source de vérité.
    income_line_family_income_current_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string='Revenus familiaux (actuel)',
        domain=[('category', '=', 'family_income'), ('situation', '=', 'current')])
    income_line_family_income_forecast_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string='Revenus familiaux (prévisionnel)',
        domain=[('category', '=', 'family_income'), ('situation', '=', 'forecast')])
    income_line_activity_expense_current_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string="Dépenses d'activité (actuel)",
        domain=[('category', '=', 'activity_expense'), ('situation', '=', 'current')])
    income_line_activity_expense_forecast_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string="Dépenses d'activité (prévisionnel)",
        domain=[('category', '=', 'activity_expense'), ('situation', '=', 'forecast')])
    income_line_family_expense_current_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string='Dépenses familiales (actuel)',
        domain=[('category', '=', 'family_expense'), ('situation', '=', 'current')])
    income_line_family_expense_forecast_ids = fields.One2many(
        'microfinance.loan.application.income.line', 'application_id',
        string='Dépenses familiales (prévisionnel)',
        domain=[('category', '=', 'family_expense'), ('situation', '=', 'forecast')])
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
    income_growth_occurred = fields.Selection([
        ('no', 'Non'),
        ('yes', 'Oui'),
    ], string='Accroissement du revenu', default='no', required=True)
    income_growth_before = fields.Monetary(string='Revenu avant')
    income_growth_after = fields.Monetary(string='Revenu actuel')
    financial_analysis_comment = fields.Text(string="Commentaire de l'enquêteur")

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
    # États considérés "en cours" pour la synchronisation du Bloc A : cohérents avec les seuls
    # états antérieurs à la transformation effective du dossier (cf. STATE_TARGET_GROUP/
    # ALLOWED_TRANSITIONS ci-dessus) — confirmé avec Micka lors du correctif de synchronisation.
    _KYC_IN_PROGRESS_STATES = ('draft', 'field_survey')

    # (nom du champ dossier, fonction extrayant la valeur source depuis res.partner) — le
    # conjoint est lu via partner.microfinance_spouse_id (contact complet, jamais dupliqué sur
    # le client). partner_current_address/partner_phone sont volontairement absents de cette
    # liste : hors mécanisme de gel, cf. leurs champs et create()/l'onchange dédié plus bas.
    _KYC_FIELD_SOURCES = (
        ('partner_surname', lambda partner: partner.name),
        ('partner_id_card_number', lambda partner: partner.microfinance_id_number),
        ('partner_id_card_issue_date', lambda partner: partner.microfinance_id_issue_date),
        ('partner_id_card_issue_place', lambda partner: partner.microfinance_id_issue_place),
        ('partner_fokontany', lambda partner: partner.microfinance_fokontany_id.name),
        ('partner_housing_status', lambda partner: partner.microfinance_housing_status),
        ('partner_reference_contact_name', lambda partner: partner.microfinance_next_of_kin_name),
        ('partner_reference_contact_phone', lambda partner: partner.microfinance_next_of_kin_phone),
        ('partner_birth_date', lambda partner: partner.microfinance_birthdate),
        ('partner_birth_place', lambda partner: partner.microfinance_birth_place),
        ('partner_marital_status', lambda partner: partner.microfinance_marital_status),
        ('spouse_name', lambda partner: partner.microfinance_spouse_id.name),
        ('spouse_id_card_number', lambda partner: partner.microfinance_spouse_id.microfinance_id_number),
        ('spouse_id_card_issue_date', lambda partner: partner.microfinance_spouse_id.microfinance_id_issue_date),
        ('spouse_id_card_issue_place', lambda partner: partner.microfinance_spouse_id.microfinance_id_issue_place),
        ('spouse_address', lambda partner: ', '.join(filter(None, [
            partner.microfinance_spouse_id.street, partner.microfinance_spouse_id.street2,
        ]))),
        ('spouse_fokontany', lambda partner: partner.microfinance_spouse_id.microfinance_fokontany_id.name),
        ('spouse_profession', lambda partner: partner.microfinance_spouse_profession.name),
        ('spouse_employer', lambda partner: partner.microfinance_spouse_id.microfinance_employer),
        ('spouse_phone', lambda partner: partner.microfinance_spouse_phone),
    )

    @api.depends(
        'partner_id.name', 'partner_id.microfinance_id_number', 'partner_id.microfinance_id_issue_date',
        'partner_id.microfinance_id_issue_place', 'partner_id.microfinance_fokontany_id.name',
        'partner_id.microfinance_housing_status', 'partner_id.microfinance_next_of_kin_name',
        'partner_id.microfinance_next_of_kin_phone', 'partner_id.microfinance_birthdate',
        'partner_id.microfinance_birth_place', 'partner_id.microfinance_marital_status',
        'partner_id.microfinance_spouse_id.name', 'partner_id.microfinance_spouse_id.microfinance_id_number',
        'partner_id.microfinance_spouse_id.microfinance_id_issue_date',
        'partner_id.microfinance_spouse_id.microfinance_id_issue_place',
        'partner_id.microfinance_spouse_id.street', 'partner_id.microfinance_spouse_id.street2',
        'partner_id.microfinance_spouse_id.microfinance_fokontany_id.name',
        'partner_id.microfinance_spouse_id.microfinance_employer',
        'partner_id.microfinance_spouse_profession.name', 'partner_id.microfinance_spouse_phone',
    )
    def _compute_kyc_from_partner(self):
        """Bloc A synchronisé depuis res.partner (client + conjoint) tant que le dossier est en
        cours (draft/field_survey). Dès qu'il en sort (analysis et au-delà), les champs listés
        dans _KYC_FIELD_SOURCES sont gelés : on les réaffecte explicitement à leur propre
        valeur (un compute readonly=False stocké doit fixer une valeur pour chaque champ à
        chaque appel, sous peine d'être vidé par l'ORM) plutôt que de les recalculer depuis la
        fiche client, qui a pu changer entre-temps."""
        for application in self:
            if application.state not in self._KYC_IN_PROGRESS_STATES:
                for field_name, _source in self._KYC_FIELD_SOURCES:
                    application[field_name] = application[field_name]
                continue
            partner = application.partner_id
            for field_name, source in self._KYC_FIELD_SOURCES:
                application[field_name] = source(partner) if partner else False

    @api.depends('activity_id.category_id')
    def _compute_activity_sector_id(self):
        for application in self:
            application.activity_sector_id = application.activity_id.category_id

    @api.depends('activity_start_date')
    def _compute_activity_duration(self):
        # Non stocké (pas de store=True) : recalculé à chaque affichage à partir
        # d'activity_start_date et de la date du jour, pour rester exact dans le temps.
        today = fields.Date.context_today(self)
        for application in self:
            start = application.activity_start_date
            if not start:
                application.activity_duration = False
                continue
            total_months = (today.year - start.year) * 12 + (today.month - start.month)
            if today.day < start.day:
                total_months -= 1
            if total_months <= 0:
                application.activity_duration = "Moins d'un mois"
                continue
            years, months = divmod(total_months, 12)
            if years == 0:
                application.activity_duration = '1 mois' if months == 1 else f'{months} mois'
            elif months == 0:
                application.activity_duration = '1 an' if years == 1 else f'{years} ans'
            else:
                year_label = '1 an' if years == 1 else f'{years} ans'
                month_label = '1 mois' if months == 1 else f'{months} mois'
                application.activity_duration = f'{year_label} et {month_label}'

    def _get_partner_current_address(self, partner):
        return ', '.join(filter(None, [partner.street, partner.street2]))

    @api.onchange('partner_id')
    def _onchange_partner_id_prefill_contact_fields(self):
        # partner_current_address/partner_phone restent hors du mécanisme de gel du Bloc A
        # (cf. _compute_kyc_from_partner) : simple pré-remplissage à la sélection du client,
        # jamais recalculé ensuite, toujours éditable manuellement — cf. aussi create().
        for application in self:
            partner = application.partner_id
            if not partner:
                continue
            if not application.partner_current_address:
                application.partner_current_address = application._get_partner_current_address(partner)
            if not application.partner_phone:
                application.partner_phone = partner.phone or partner.mobile

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
        'income_line_ids.monthly_amount', 'income_line_ids.category', 'income_line_ids.situation',
        'safety_margin_current', 'safety_margin_forecast',
    )
    def _compute_financial_totals(self):
        # Diviseur hebdomadaire = 4 exactement (4 semaines par mois, fiche papier), pas 52/12
        # (≈4,333) — vérifié sur l'exemple papier CEFOR (213890 / 4 = 53472,5 exact).
        WEEKS_PER_MONTH = 4.0
        for application in self:
            lines = application.income_line_ids

            def total(category, situation):
                return sum(lines.filtered(
                    lambda line: line.category == category and line.situation == situation
                ).mapped('monthly_amount'))

            application.total_family_income_current = total('family_income', 'current')
            application.total_family_income_forecast = total('family_income', 'forecast')
            application.total_activity_expense_current = total('activity_expense', 'current')
            application.total_activity_expense_forecast = total('activity_expense', 'forecast')
            # Dépenses familiales : chaque situation a ses propres lignes saisies (plus de
            # dérivation de la prévisionnelle depuis l'actuelle) ; la majoration (+X%, fiche
            # papier : +5%) s'applique au sous-total de CETTE situation uniquement — jamais aux
            # dépenses d'activité (cf. audit Section V, point de vérification confirmé).
            application.total_family_expense_current = total('family_expense', 'current') * (
                1 + application.safety_margin_current / 100.0)
            application.total_family_expense_forecast = total('family_expense', 'forecast') * (
                1 + application.safety_margin_forecast / 100.0)
            application.repayment_capacity_monthly_current = application.total_family_income_current - (
                application.total_activity_expense_current + application.total_family_expense_current)
            application.repayment_capacity_weekly_current = application.repayment_capacity_monthly_current / WEEKS_PER_MONTH
            application.repayment_capacity_monthly_forecast = application.total_family_income_forecast - (
                application.total_activity_expense_forecast + application.total_family_expense_forecast)
            application.repayment_capacity_weekly_forecast = application.repayment_capacity_monthly_forecast / WEEKS_PER_MONTH

    @api.depends('dependent_ids.relationship', 'dependent_ids.school_name')
    def _compute_children_counts(self):
        for application in self:
            children = application.dependent_ids.filtered(lambda d: d.relationship == 'child')
            application.children_count = len(children)
            application.children_schooled_count = len(children.filtered('school_name'))

    @api.depends(
        'field_visit_ids', 'dependent_ids', 'guarantor_partner_id',
        'document_line_ids.provided_by_partner', 'document_line_ids.provided_by_guarantor',
    )
    def _compute_counts(self):
        for application in self:
            application.field_visit_count = len(application.field_visit_ids)
            application.dependent_count = len(application.dependent_ids)
            application.guarantor_count = 1 if application.guarantor_partner_id else 0
            application.primary_guarantor_name = application.guarantor_partner_id.name or False
            # "Fourni" = coché pour le partenaire ou pour le garant (au moins une des deux
            # cases), depuis l'éclatement de l'ancien champ unique is_provided.
            provided = len(application.document_line_ids.filtered(
                lambda line: line.provided_by_partner or line.provided_by_guarantor
            ))
            application.document_provided_count = provided
            application.document_missing_count = len(application.document_line_ids) - provided

    # États du dossier considérés "en cours" pour la synchronisation garant — mêmes valeurs que
    # _KYC_IN_PROGRESS_STATES (Bloc A), pas de dépendance directe entre les deux constantes.
    _GUARANTOR_SYNC_IN_PROGRESS_STATES = ('draft', 'field_survey')
    _GUARANTOR_KYC_FIELD_SOURCES = (
        ('guarantor_address', lambda partner: ', '.join(filter(None, [partner.street, partner.street2]))),
        ('guarantor_profession', lambda partner: partner.microfinance_profession.name),
    )

    @api.depends(
        'guarantor_partner_id.street', 'guarantor_partner_id.street2',
        'guarantor_partner_id.microfinance_profession.name',
    )
    def _compute_guarantor_kyc_from_partner(self):
        """Adresse/profession du garant : même patron de gel que le Bloc A
        (_compute_kyc_from_partner) — synchronisées depuis guarantor_partner_id tant que le
        dossier est en cours (draft/field_survey), figées au-delà."""
        for application in self:
            if application.state not in self._GUARANTOR_SYNC_IN_PROGRESS_STATES:
                for field_name, _source in self._GUARANTOR_KYC_FIELD_SOURCES:
                    application[field_name] = application[field_name]
                continue
            partner = application.guarantor_partner_id
            for field_name, source in self._GUARANTOR_KYC_FIELD_SOURCES:
                application[field_name] = source(partner) if partner else False

    @api.depends('guarantor_partner_id.phone', 'guarantor_partner_id.mobile')
    def _compute_guarantor_phone(self):
        # Hors mécanisme de gel (comme partner_phone sur le Bloc A) : toujours resynchronisé
        # depuis le contact garant, jamais figé.
        for application in self:
            partner = application.guarantor_partner_id
            application.guarantor_phone = (partner.phone or partner.mobile) if partner else False

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
        # name n'est plus généré ici : related='partner_id.microfinance_account_number' (cf.
        # déclaration du champ ci-dessus) — la référence du dossier reprend le numéro de compte
        # permanent du client, elle n'est plus une séquence propre au dossier.
        for vals in vals_list:
            if vals.get('state') and vals['state'] != 'draft':
                raise UserError(_('Un nouveau dossier d\'instruction doit démarrer à l\'état Brouillon.'))
            # partner_current_address/partner_phone : hors du mécanisme de gel du Bloc A (cf.
            # _compute_kyc_from_partner) — pré-remplis ici pour les dossiers créés directement
            # par l'ORM (ex. res.partner._get_or_create_loan_application()), sans passer par le
            # formulaire où l'onchange partner_id s'en chargerait.
            if vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                if not vals.get('partner_current_address'):
                    address = self._get_partner_current_address(partner)
                    if address:
                        vals['partner_current_address'] = address
                if not vals.get('partner_phone'):
                    phone = partner.phone or partner.mobile
                    if phone:
                        vals['partner_phone'] = phone
        applications = super().create(vals_list)
        for application in applications:
            application._ensure_default_document_lines()
            application._ensure_default_financial_lines()
        return applications

    # NE PAS réintroduire d'appel à _ensure_default_financial_lines() (ni équivalent) depuis
    # read()/web_read() : une lecture peut être appelée plusieurs fois en parallèle par le
    # client web (un appel par bloc <field domain="..."> imbriqué, notamment) — un
    # déclenchement d'écriture depuis une lecture n'est pas protégé contre cette concurrence et
    # peut dupliquer massivement les lignes (constaté : jusqu'à 70 lignes pour un catalogue de
    # 7 désignations). Les dossiers créés avant l'introduction de ce mécanisme doivent être
    # corrigés au cas par cas (script one-shot), pas via un hook de lecture.

    def _ensure_default_document_lines(self):
        """Garantit la présence des lignes documents standard (Copie CIN / Certificat de
        résidence), sans jamais dupliquer celles déjà présentes — vérifié par document_type
        (name) plutôt qu'un simple test "collection vide", pour aussi fonctionner sur un
        dossier existant qui a déjà une ligne personnalisée mais pas encore les 2 standard.
        Appelé à la création du dossier ; écrit directement sur document_line_ids (le modèle
        réel), plus de wizard intermédiaire."""
        self.ensure_one()
        existing_types = set(self.document_line_ids.mapped('name'))
        missing = [doc_type for doc_type in self._DEFAULT_DOCUMENT_TYPES if doc_type not in existing_types]
        if missing:
            self.document_line_ids = [(0, 0, {'name': doc_type}) for doc_type in missing]

    # Catégorie -> (modèle du catalogue de désignations, champ Many2one correspondant sur
    # microfinance.loan.application.income.line) — un seul des 3 champs designation est rempli
    # selon la catégorie de la ligne (cf. docstring du modèle de ligne).
    _FINANCIAL_CATEGORY_DESIGNATION_FIELDS = {
        'family_income': ('microfinance.financial.designation.income', 'income_designation_id'),
        'activity_expense': ('microfinance.financial.designation.activity.expense', 'activity_expense_designation_id'),
        'family_expense': ('microfinance.financial.designation.family.expense', 'family_expense_designation_id'),
    }

    def _ensure_default_financial_lines(self):
        """Garantit une ligne par désignation configurée (Configuration > Financement), pour
        chacune des 3 catégories et des 2 situations (actuelle/prévisionnelle), montant à 0 —
        à compléter par l'enquêteur. Ne duplique jamais une ligne déjà présente pour une
        désignation donnée (même patron que _ensure_default_document_lines)."""
        self.ensure_one()
        new_line_vals = []
        for category, (model_name, field_name) in self._FINANCIAL_CATEGORY_DESIGNATION_FIELDS.items():
            designations = self.env[model_name].search([('active', '=', True)])
            for situation in ('current', 'forecast'):
                lines = self.income_line_ids.filtered(
                    lambda line, category=category, situation=situation:
                        line.category == category and line.situation == situation)
                existing_designation_ids = set(lines.mapped(field_name).ids)
                missing = designations.filtered(lambda d: d.id not in existing_designation_ids)
                new_line_vals += [{
                    'category': category, 'situation': situation, field_name: designation.id,
                } for designation in missing]
        if new_line_vals:
            self.income_line_ids = [(0, 0, vals) for vals in new_line_vals]

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
    # Pagination de la fiche d'enquête (3 pages) — bascule survey_page selon l'ordre de
    # _SURVEY_PAGES, sans aucun effet sur state ni sur les autres champs. Basé sur une liste
    # ordonnée plutôt que des valeurs figées pour rester valable si une page supplémentaire est
    # ajoutée un jour (il suffit alors d'étendre _SURVEY_PAGES et le Selection survey_page).
    # ------------------------------------------------------------------
    _SURVEY_PAGES = ['partner_identification', 'guarantor_documents_activity', 'financial_visits_ca_cdag']

    def action_survey_next_page(self):
        for application in self:
            index = self._SURVEY_PAGES.index(application.survey_page)
            if index < len(self._SURVEY_PAGES) - 1:
                application.survey_page = self._SURVEY_PAGES[index + 1]

    def action_survey_previous_page(self):
        for application in self:
            index = self._SURVEY_PAGES.index(application.survey_page)
            if index > 0:
                application.survey_page = self._SURVEY_PAGES[index - 1]

class MicrofinanceLoanApplicationDependent(models.Model):
    """Section I — Enfants et personnes à charge du partenaire.

    "Lien de parenté" (relationship) n'existe pas sur la fiche papier CEFOR d'origine (qui
    liste juste "enfants et personnes à charge" sans distinguer) : conservé au-delà du papier
    car déjà utile pour les personnes à charge non-enfants — cf. docs_dev/programme_progressif/
    STATUS.md, point de décision confirmé avec Micka lors de la mise en conformité au papier."""
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
    age = fields.Integer(
        string='Age', compute='_compute_age', store=True,
        help="Calculé à partir de la date de naissance (âge à la date du jour) : jamais saisi "
             "à la main, pour ne jamais entrer en incohérence avec la date de naissance.",
    )
    school_class = fields.Char(string='Classe')
    school_name = fields.Char(string='École')
    remark = fields.Char(string='Remarque')

    @api.depends('birth_date')
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for dependent in self:
            if not dependent.birth_date:
                dependent.age = 0
                continue
            birth_date = dependent.birth_date
            years = today.year - birth_date.year
            if (today.month, today.day) < (birth_date.month, birth_date.day):
                years -= 1
            dependent.age = years


class MicrofinanceLoanApplicationDocumentLine(models.Model):
    """Section III — Dossiers administratifs fournis : matrice Partenaire/Garant.

    "Photo d'identité" n'apparaît jamais dans ces lignes (ni pré-remplie ni à ajouter à la
    main) : déjà couverte par le champ photo natif de res.partner (image_1920), pas besoin de
    la suivre une deuxième fois ici."""
    _name = 'microfinance.loan.application.document.line'
    _description = 'Document administratif fourni (dossier de crédit)'

    application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier', required=True, ondelete='cascade')
    name = fields.Char(string='Document', required=True)
    provided_by_partner = fields.Boolean(string='Partenaire')
    provided_by_guarantor = fields.Boolean(string='Garant')
    observation = fields.Char(string='Observation')


class MicrofinanceLoanApplicationIncomeLine(models.Model):
    """Section V — Analyse financière : lignes de revenus familiaux / dépenses d'activité /
    dépenses familiales, pour chaque situation (actuelle/prévisionnelle). Un seul modèle avec
    un champ category (comme avant la refonte, pour limiter la casse) plutôt que 3 modèles de
    ligne séparés — décision confirmée avec Micka. designation_id référence le catalogue
    correspondant à category (un seul des 3 champs designation rempli selon la catégorie,
    même patron que microfinance.loan.application.field.visit pour les champs
    spécifiques-au-type). monthly_amount n'est plus saisi directement (cf. ancienne
    implémentation) : calculé depuis amount × frequency_id.multiplier."""
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
    situation = fields.Selection([
        ('current', 'Actuelle'),
        ('forecast', 'Prévisionnelle'),
    ], string='Situation', required=True, default='current')
    income_designation_id = fields.Many2one(
        'microfinance.financial.designation.income', string='Désignation')
    activity_expense_designation_id = fields.Many2one(
        'microfinance.financial.designation.activity.expense', string='Désignation')
    family_expense_designation_id = fields.Many2one(
        'microfinance.financial.designation.family.expense', string='Désignation')
    amount = fields.Monetary(string='Montant', help='Montant saisi, à la fréquence indiquée.')
    frequency_id = fields.Many2one(
        'microfinance.financial.frequency', string='Fréquence', required=True,
        default=lambda self: self.env.ref(
            'microfinance_loan_management.financial_frequency_monthly', raise_if_not_found=False),
    )
    monthly_amount = fields.Monetary(
        string='Montant mensuel', compute='_compute_monthly_amount', store=True,
        help='Montant × multiplicateur de la fréquence (ex. Hebdomadaire ×4) — jamais saisi '
             'directement.',
    )

    @api.depends('amount', 'frequency_id.multiplier')
    def _compute_monthly_amount(self):
        for line in self:
            line.monthly_amount = line.amount * line.frequency_id.multiplier


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
