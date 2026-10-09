# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _pcec_default(code):
    """Défaut calculé pour un champ account.account : recherche par code + société, jamais
    par référence XML statique (les comptes PCEC sont dupliqués par société via le chart
    template plan_compta_pcec). Retourne un recordset vide si le compte n'existe pas pour la
    société courante (plan PCEC non chargé) : le champ reste simplement vide, comme avant
    l'introduction de ce défaut. Dupliqué depuis microfinance_loan_product.py /
    microfinance_savings_product.py, faute de module utilitaire partagé pour ce seul besoin."""
    def _default(self):
        return self.env['account.account'].search([
            ('code', '=', code), ('company_id', '=', self.env.company.id),
        ], limit=1)
    return _default


class ResCompany(models.Model):
    _inherit = 'res.company'

    agency_code = fields.Char(
        string='Code agence', size=3, required=True,
        help="Code court identifiant l'agence CEFOR (ex. IS pour Isotry). Sert de préfixe "
             "automatique pour la numérotation des dossiers de crédit et des comptes "
             "d'épargne (format AGENCE/TYPE/SÉRIE, ou AGENCE/SÉRIE pour le crédit). "
             "Obligatoire pour toute société de cette instance.",
    )

    _sql_constraints = [
        ('agency_code_unique', 'unique(agency_code)', "Le code agence doit être unique par société."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # required=True sur le champ suffit à empêcher l'enregistrement en base (NOT NULL),
        # mais laisse remonter une erreur SQL brute jusqu'à l'utilisateur ; ce contrôle
        # explicite intercepte le cas le plus courant (champ jamais renseigné) avec un message
        # métier clair avant même d'atteindre la contrainte SQL.
        for vals in vals_list:
            if not vals.get('agency_code'):
                raise ValidationError(_('Le code agence est obligatoire pour créer une agence CEFOR.'))
        companies = super().create(vals_list)
        companies.mapped('partner_id').write({'microfinance_partner_type': 'agence'})
        return companies

    def _get_or_create_numbering_sequence(self, code, padding=6):
        """Renvoie le prochain numéro (chaîne, déjà complétée par des zéros à `padding`
        chiffres) d'une séquence dédiée à cette société pour `code` — jamais partagée avec une
        autre société. Créée à la demande plutôt que pré-déclarée par agence en XML : de
        nouvelles agences sont ajoutées manuellement au fil de l'eau (jusqu'à 25 à terme), donc
        aucune liste figée de sociétés ne peut être connue à l'avance."""
        self.ensure_one()
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([('code', '=', code), ('company_id', '=', self.id)], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': '%s (%s)' % (code, self.name),
                'code': code,
                'company_id': self.id,
                'padding': padding,
                'number_next': 1,
                'number_increment': 1,
            })
        return sequence.next_by_id()

    loan_product_code_prefix = fields.Char(
        string='Préfixe code produit crédit', default='CR',
        help="Préfixe utilisé pour générer automatiquement le code des nouveaux produits de "
             "crédit de cette société (ex. CR00001). Modifiable uniquement tant qu'aucun "
             "produit de crédit n'a encore été créé pour cette société — dès le premier "
             "produit, le préfixe est verrouillé pour ne jamais mélanger deux styles de code "
             "dans l'historique.",
    )
    loan_product_code_locked = fields.Boolean(
        string='Préfixe crédit verrouillé', compute='_compute_loan_product_code_locked',
        help="Vrai dès qu'au moins un produit de crédit existe pour cette société.",
    )
    microfinance_fond_credit_default_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit par défaut',
        domain="[('active', '=', True), ('destination', '=', 'credit'), "
               "'|', ('date_cloture', '=', False), ('date_cloture', '>=', context_today().strftime('%Y-%m-%d')), "
               "'|', '&', ('scope', '=', 'single_company'), ('company_id', '=', id), "
               "'&', ('scope', '=', 'multi_company'), "
               "'|', ('allocation_required', '=', False), ('allocation_ids.company_id', '=', id)]",
        help="Fonds bailleur rotatif proposé par défaut à la création d'un nouveau crédit dans "
             "cette société (pré-remplissage de microfinance.loan.fond_credit_id, simple aide à "
             "la saisie - reste librement modifiable par l'utilisateur avant décaissement, sans "
             "rapport avec le verrouillage de fond_credit_id après décaissement). Modifiable à "
             "tout moment sans restriction ni effet rétroactif : seuls les crédits créés après un "
             "changement de ce champ se voient proposer le nouveau fonds, les crédits déjà créés "
             "gardent leur fond_credit_id tel quel. Pas de groups= au niveau champ (bloquerait la "
             "lecture depuis l'onchange de microfinance.loan pour tout utilisateur non manager, "
             "cassant le pré-remplissage pour un simple agent) : la restriction à "
             "group_microfinance_manager est portée uniquement par la vue "
             "(microfinance_res_company_views.xml).",
    )
    microfinance_fond_account_default_id = fields.Many2one(
        'account.account', string='Compte bailleur par défaut (fonds de crédit)',
        domain="[('account_type', 'in', ('liability_current', 'liability_non_current', 'equity')), "
               "('company_id', '=', id)]",
        help="Compte comptable bailleur (microfinance.fond.credit.account_id) proposé par défaut "
             "à la création d'un nouveau fonds de crédit rotatif pour cette société - simple aide "
             "à la saisie, reste librement modifiable sur chaque fonds, y compris juste après sa "
             "création. Aucun effet rétroactif : changer ce défaut ne touche jamais les fonds déjà "
             "créés (comportement identique à microfinance_fond_credit_default_id ci-dessus). "
             "Défaut vide = comportement actuel inchangé (le compte reste à saisir manuellement, "
             "_check_account_required continue de bloquer si passer_gl est actif sans compte). Pas "
             "de groups= au niveau champ (même raison que ci-dessus : ne pas casser la lecture du "
             "défaut par un non-manager à la création d'un fonds) : restriction à "
             "group_microfinance_manager portée uniquement par la vue "
             "(microfinance_res_company_views.xml).",
    )

    @api.constrains('microfinance_fond_account_default_id')
    def _check_fond_account_default_id(self):
        # Défense en profondeur : le domaine du champ (UI) exclut déjà les comptes d'un autre
        # type ou d'une autre société, mais un write()/import direct doit être bloqué aussi -
        # même raisonnement que MicrofinanceFondCredit._check_account_type.
        allowed_types = ('liability_current', 'liability_non_current', 'equity')
        for company in self:
            account = company.microfinance_fond_account_default_id
            if not account:
                continue
            if account.account_type not in allowed_types:
                raise ValidationError(_(
                    'Le compte bailleur par défaut doit être un compte de type dette ou fonds '
                    'propres (liability_current, liability_non_current ou equity).'
                ))
            if account.company_id != company:
                raise ValidationError(_(
                    'Le compte bailleur par défaut de "%(company)s" doit appartenir à cette '
                    'société (compte "%(account)s" rattaché à "%(account_company)s").'
                ) % {
                    'company': company.name, 'account': account.display_name,
                    'account_company': account.company_id.name,
                })

    microfinance_social_grid_include_impression_in_total = fields.Boolean(
        string="Grille sociale : inclure l'impression de l'enquêteur dans le total du dossier",
        help="Ajoute jusqu'à 4 points au maximum théorique. Ajustez vos niveaux en conséquence.",
    )
    # Nom raccourci par rapport à l'intitulé fonctionnel complet ("...eligibility") : la
    # limite PostgreSQL de 63 octets par identifiant tronque silencieusement tout nom plus
    # long, ce qui peut faire collisionner deux champs distincts sur la même colonne
    # physique sans avertissement — champ renommé pour rester nettement sous la limite.
    microfinance_social_grid_include_impression_next_loan = fields.Boolean(
        string="Grille sociale : inclure l'impression de l'enquêteur dans l'éligibilité d'un prochain crédit",
        help="Indépendant du réglage ci-dessus. Branché sur le contrôle de rang > 1 "
             '(_check_previous_loan_requirements).',
    )
    microfinance_social_grid_impression_next_loan_min_score = fields.Integer(
        string="Grille sociale : score minimum d'impression pour un prochain crédit",
        default=1,
        help='Actif uniquement si le réglage ci-dessus est coché. Un dossier de rang > 1 ne '
             'peut pas être soumis au comité si l\'impression personnelle de l\'enquêteur sur '
             'le dossier précédent (surveyor_impression_score) est strictement inférieure à '
             'ce seuil.',
    )

    cash_journal_id = fields.Many2one(
        'account.journal', string='Journal de caisse (guichet)',
        domain="[('type', '=', 'cash'), ('company_id', '=', id)]",
        help="Journal unique autorisé pour l'ouverture d'une session de caisse guichet dans "
             "cette agence.",
    )
    disbursement_journal_ids = fields.Many2many(
        'account.journal', string='Journaux de décaissement autorisés (guichet)',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', id)]",
        help="Restreint la liste des journaux proposés à l'écran « Décaissement crédit » du "
             "guichet caisse à ceux sélectionnés ici (ex. Crédits, Caisse, Banque-Crédits) — "
             "exclut ainsi les journaux sans rapport avec le crédit (Épargne, Banque-Épargne) "
             "qui apparaissaient jusque-là sans distinction. Laissé vide : aucun filtre "
             "supplémentaire, tous les journaux bank/cash de l'agence restent proposés "
             "(rétrocompatibilité pour une agence pas encore configurée).",
    )
    microfinance_account_ecart_caisse_deficit_id = fields.Many2one(
        'account.account', string="Compte d'attente écart de caisse (déficit)",
        domain="[('account_type', '=', 'asset_current'), ('company_id', '=', id)]",
        default=_pcec_default('324000'),
        help="Compte de contrepartie de l'écriture posée à la clôture d'une session de caisse "
             "quand un écart NÉGATIF (manquant en caisse : compté < théorique) est constaté : "
             "le montant y reste en attente jusqu'à sa réconciliation manuelle par un manager "
             "(même principe que le compte d'attente chèques - "
             "microfinance.savings.product.account_cheques_attente_id). Normalement déjà "
             "pré-rempli (compte PCEC 324 « Comptes d'attente à régulariser - actif ») : à ne "
             "changer que pour un cas particulier.",
    )
    microfinance_account_ecart_caisse_excedent_id = fields.Many2one(
        'account.account', string="Compte d'attente écart de caisse (excédent)",
        domain="[('account_type', '=', 'liability_current'), ('company_id', '=', id)]",
        default=_pcec_default('329100'),
        help="Compte de contrepartie de l'écriture posée à la clôture d'une session de caisse "
             "quand un écart POSITIF (excédent en caisse : compté > théorique) est constaté : "
             "le montant y reste en attente jusqu'à son affectation manuelle par un manager "
             "(même principe que le compte d'attente chèques - "
             "microfinance.savings.product.account_cheques_attente_id). Normalement déjà "
             "pré-rempli (compte PCEC 3291 « Écritures créditrices à régulariser ») : à ne "
             "changer que pour un cas particulier.",
    )

    _COLLECTION_DAY_LABELS = {
        'monday': 'Alatsinainy',
        'tuesday': 'Talata',
        'wednesday': 'Alarobia',
        'thursday': 'Alakamisy',
        'friday': 'Zoma',
    }

    collection_day = fields.Selection(
        [
            ('monday', 'Lundi'),
            ('tuesday', 'Mardi'),
            ('wednesday', 'Mercredi'),
            ('thursday', 'Jeudi'),
            ('friday', 'Vendredi'),
        ], string='Jour de collecte', default='monday', required=True,
        help="Jour de la semaine où cette agence collecte les remboursements. Un seul jour par "
             "agence (pas par produit). Sert de date limite : la date d'échéance brute calculée "
             "par périodicité (microfinance.loan._build_installment_commands) est arrondie en "
             "avant jusqu'à la prochaine occurrence de ce jour (microfinance.loan."
             "_roll_forward_to_collection_day) - le client peut payer avant, mais cette date "
             "reste la date officielle affichée sur l'échéancier et le contrat. Défaut 'monday' : "
             "reprend le jour codé en dur (ALATSINAINY) dans report_contrat_credit.xml avant "
             "l'introduction de ce champ, pour ne rien changer au comportement existant tant "
             "qu'une agence n'a pas été reconfigurée explicitement.",
    )

    def get_collection_day_label(self):
        """Libellé malgache du jour de collecte (Alatsinainy/Talata/Alarobia/Alakamisy/Zoma),
        pour le rapport de contrat de crédit (report_contrat_credit.xml) - remplace l'ancien
        texte 'ALATSINAINY' codé en dur, identique pour toutes les agences."""
        self.ensure_one()
        return self._COLLECTION_DAY_LABELS.get(self.collection_day, '')

    def _compute_loan_product_code_locked(self):
        Product = self.env['microfinance.loan.product']
        for company in self:
            company.loan_product_code_locked = bool(Product.search_count([('company_id', '=', company.id)]))

    def _get_microfinance_dashboard_subtitle(self):
        """Nom de la société + adresse (rue, complément, ville) pour le sous-titre de l'en-tête
        du tableau de bord microfinance. Omet proprement les segments d'adresse vides plutôt que
        de laisser des virgules ou un tiret orphelins."""
        self.ensure_one()
        address_parts = [part for part in (self.street, self.street2, self.city) if part]
        if not address_parts:
            return self.name
        return '%s — %s' % (self.name, ', '.join(address_parts))

    def write(self, vals):
        if 'agency_code' in vals and not vals['agency_code']:
            raise ValidationError(_('Le code agence est obligatoire pour créer une agence CEFOR.'))
        if 'loan_product_code_prefix' in vals:
            Product = self.env['microfinance.loan.product']
            locked = self.filtered(lambda c: Product.search_count([('company_id', '=', c.id)]))
            if locked:
                raise UserError(_(
                    "Le préfixe de code produit crédit ne peut plus être modifié : des produits "
                    "de crédit existent déjà pour %s (numérotation déjà initiée)."
                ) % ', '.join(locked.mapped('name')))
        res = super().write(vals)
        if 'partner_id' in vals:
            self.mapped('partner_id').write({'microfinance_partner_type': 'agence'})
        return res

    microfinance_operating_journal_id = fields.Many2one(
        'account.journal', string='Journal bancaire d\'exploitation',
        domain="[('type', '=', 'bank'), ('company_id', '=', id)]",
        help="Compte bancaire d'exploitation de l'agence (salaires par virement, loyer et "
             "fournisseurs par chèque), séparé des fonds de crédit et de l'épargne. Défaut : le "
             "journal BMOP de la société. Les journaux de fonds (FDBM, FDBN) sont refusés. Le "
             "journal de paie et le journal proposé par défaut pour les paiements fournisseurs "
             "suivent ce champ.",
    )
    payroll_journal_id = fields.Many2one(
        compute='_compute_payroll_journal_id', store=True, readonly=False,
    )

    OPERATING_FORBIDDEN_CODES = ('FDBM', 'FDBN')
    OPERATING_DISCOURAGED_CODES = ('BMCR', 'BNCR', 'BMEP', 'BNEP')

    @api.depends('microfinance_operating_journal_id')
    def _compute_payroll_journal_id(self):
        """Le journal de paie suit le journal d'exploitation ; sans journal d'exploitation, la
        valeur actuelle (choix manuel) est conservée. Reste modifiable à la main."""
        for company in self:
            company.payroll_journal_id = (
                company.microfinance_operating_journal_id or company.payroll_journal_id)

    @api.constrains('microfinance_operating_journal_id')
    def _check_microfinance_operating_journal(self):
        for company in self:
            journal = company.microfinance_operating_journal_id
            if not journal:
                continue
            if journal.code in self.OPERATING_FORBIDDEN_CODES:
                raise ValidationError(_(
                    "Le journal « %s » est un journal de fonds : il ne peut pas servir de "
                    "journal bancaire d'exploitation.") % journal.display_name)
            if journal.type != 'bank' or journal.company_id != company:
                raise ValidationError(_(
                    "Le journal bancaire d'exploitation doit être un journal de type banque "
                    "de la société %s.") % company.name)

    @api.model
    def _operating_journal_warning(self, journal):
        """Avertissement (jamais bloquant) si le journal choisi est dédié au crédit ou à
        l'épargne. Retourne un dict `warning` utilisable par un onchange, ou {}."""
        if journal and journal.code in self.OPERATING_DISCOURAGED_CODES:
            return {'warning': {
                'title': _("Journal de crédit ou d'épargne"),
                'message': _(
                    "Le journal « %s » sert au crédit ou à l'épargne des clients. L'exploitation "
                    "devrait passer par son propre compte bancaire (BMOP ou BNOP).")
                    % journal.display_name,
            }}
        return {}

    @api.onchange('microfinance_operating_journal_id')
    def _onchange_microfinance_operating_journal_id(self):
        return self._operating_journal_warning(self.microfinance_operating_journal_id)

    is_microfinance_parent = fields.Boolean(
        string='Société mère (fonds bailleurs)', compute='_compute_is_microfinance_parent',
        help="Vrai si cette société est la société mère désignée dans les paramètres. Non stocké : "
             "sert uniquement à masquer la création/modification dans les vues des agences.",
    )

    @api.model
    def _get_microfinance_parent(self):
        """Société mère désignée dans les paramètres (recordset vide si aucune)."""
        param = self.env['ir.config_parameter'].sudo().get_param('microfinance.parent_company_id')
        if not param or not param.isdigit():
            return self.browse()
        return self.sudo().browse(int(param)).exists()

    @api.depends_context('company')
    def _compute_is_microfinance_parent(self):
        parent = self._get_microfinance_parent()
        for company in self:
            company.is_microfinance_parent = bool(parent) and company.id == parent.id

    @api.model
    def _check_microfinance_parent_only(self):
        """Garde « société mère uniquement » : sans mère configurée, aucune restriction
        (comportement d'origine). Sinon la société courante doit être la mère."""
        parent = self._get_microfinance_parent()
        if parent and self.env.company.id != parent.id:
            raise UserError(_('Seule la société mère (%s) peut effectuer cette opération.') % parent.name)
