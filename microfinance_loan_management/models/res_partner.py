# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Réglage global unique (toutes agences confondues, cf. Microfinance > Configuration >
# Paramètres) : pas de champ dupliqué par société, ne s'applique qu'aux nouveaux dossiers.
MICROFINANCE_PRODUCT_POLICY_PARAM = 'microfinance_loan_management.microfinance_product_policy'

# États d'un crédit « en cours » au sens du blocage inter-agences (un client ne peut pas être
# créé ni obtenir de crédit dans une agence tant qu'il en a un dans une autre). 'active' inclut
# le crédit activé mais pas encore décaissé ; 'approved' et 'written_off' sont exclus.
ACTIVE_LOAN_STATES = ('active', 'defaulted')

# Sans ce flag, aucun client ne peut être créé (ni un contact promu client) sous microfinance_context.
MICROFINANCE_PARTNER_CREATE_FLAG = 'allow_microfinance_partner_create'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_partner_type = fields.Selection([
        ('bailleur', 'Bailleur de fonds'),
        ('agence', 'Agence'),
        ('client', 'Client'),
    ], string='Type de partenaire',
        help="Catégorie du partenaire au sens microfinance, distincte de « Type de client » "
             "(particulier/société) qui décrit la nature juridique. Détermine la visibilité "
             "dans le menu Clients (filtré sur 'client') et dans la sélection des bailleurs sur "
             "microfinance.bailleur.fonds (filtrée sur 'bailleur'). Toujours renseigné par le code "
             "(jamais saisi à la main) : 'agence' synchronisé depuis res.company, 'bailleur' fixé à la "
             "création depuis microfinance.bailleur.fonds, 'client' par défaut de contexte sur le menu "
             "Clients. Volontairement non 'required=True' au niveau champ : ce partner est partagé "
             "avec les autres usages de l'instance (EAT, immobilier), qui n'ont pas cette notion.")

    microfinance_client_type = fields.Selection([
        ('individual', 'Particulier'),
        ('company', 'Société'),
    ], string='Type de client', default='individual')

    # Champ natif res.partner.company_id (déjà filtré par la règle multi-société standard
    # base.res_partner_rule) : un client microfinance est rattaché à une seule agence, pas
    # de partage entre sociétés. Non requis au niveau du champ pour ne pas impacter les
    # partenaires des autres usages de l'instance (EAT, immobilier...) qui restent partagés ;
    # le caractère obligatoire n'est appliqué qu'en contexte microfinance (cf. contrainte
    # _check_microfinance_company_required ci-dessous).
    company_id = fields.Many2one(
        'res.company', string='Société (agence)',
        default=lambda self: self.env.company if self.env.context.get('microfinance_context') else False,
        help="Agence à laquelle ce client est rattaché de façon exclusive. Obligatoire pour "
             "les clients microfinance, laissé vide pour les partenaires partagés entre "
             "sociétés (usages hors microfinance de l'instance).",
    )

    # Redéclaré ici (même colonne que microfinance_payroll_loan, qui le déclarait seul) pour que le
    # panneau « Portefeuille » du menu Clients et le chemin Mon portefeuille n'en dépendent pas.
    microfinance_officer_id = fields.Many2one(
        'res.users', string='Agent crédit (portefeuille)', index=True, tracking=True, copy=False,
        help="Agent de crédit dont ce client dépend. Posé à la création depuis le portefeuille "
             "de l'agent (ou par le wizard « Avance spéciale ») ; ne change jamais tout seul.",
    )

    @api.model
    def _microfinance_is_unauthorized_client_creation(self, vals):
        context = self.env.context
        if not context.get('microfinance_context') or context.get(MICROFINANCE_PARTNER_CREATE_FLAG):
            return False
        if 'microfinance_partner_type' in vals:
            return vals['microfinance_partner_type'] == 'client'
        return context.get('default_microfinance_partner_type') == 'client'

    @api.model
    def _microfinance_raise_client_creation_forbidden(self):
        raise UserError(_(
            "La création d'un client se fait uniquement depuis le portefeuille de l'agent de crédit."))

    @api.model
    def _microfinance_check_officer_assignable(self, vals):
        """Même avec le flag, l'agent posé doit avoir un portefeuille actif dans l'agence du
        client : le flag et le default_* transitent par le contexte, donc forgeables en RPC."""
        officer_id = vals.get('microfinance_officer_id') or self.env.context.get(
            'default_microfinance_officer_id')
        if not officer_id:
            return
        company_id = vals.get('company_id') or self.env.company.id
        if not self.env['microfinance.portfolio'].sudo().search_count([
            ('agent_id', '=', officer_id), ('company_id', '=', company_id), ('active', '=', True),
        ]):
            raise UserError(_(
                "L'agent de crédit choisi n'a pas de portefeuille actif dans l'agence de ce client."))

    def action_open_microfinance_client_form(self):
        """Fiche client microfinance (form du menu Clients), pour un client existant : jamais le
        flag de création dans le contexte."""
        self.ensure_one()
        self.check_access_rights('read')
        self.check_access_rule('read')
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'res.partner',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('microfinance_loan_management.view_microfinance_client_form_clients_menu').id, 'form')],
            'context': {'microfinance_context': True, 'default_microfinance_partner_type': 'client'},
            'target': 'current',
        }

    def get_formview_action(self, access_uid=None):
        # Clic sur un Many2one partner d'une vue microfinance : même fiche que le menu Clients.
        if self.env.context.get('microfinance_context') and len(self) == 1 \
                and self.microfinance_partner_type == 'client':
            return self.action_open_microfinance_client_form()
        return super().get_formview_action(access_uid=access_uid)

    @api.onchange('microfinance_client_type')
    def _onchange_microfinance_client_type(self):
        for partner in self:
            partner.is_company = partner.microfinance_client_type == 'company'

    @api.onchange('microfinance_commune_id', 'microfinance_fokontany_id')
    def _onchange_microfinance_geo_derived_fields(self):
        # La Commune pilote Ville/Code postal/District/Région (plutôt qu'une saisie manuelle
        # dupliquée) : city = nom de la commune, zip = son code postal, district_id/region_id
        # repris tels quels du rattachement déjà fait sur la commune (champs readonly côté vue,
        # jamais de saisie manuelle directe — cf. PATCH_commune_model Lot 5). Le fokontany n'a
        # pas de nom de ville propre (ne touche jamais city/district/region) mais reste
        # prioritaire sur zip quand il a son propre code postal, plus précis que celui de la
        # commune. city/zip restent modifiables à la main ensuite : on ne les efface jamais si
        # aucune valeur n'est connue, un agent doit pouvoir corriger si le référentiel est
        # incomplet. district_id/region_id restent vides si la commune n'est pas encore
        # rattachée à un district (721 communes sur 1645, cf.
        # docs/unmatched_ambiguous_report.csv).
        for partner in self:
            if partner.microfinance_commune_id:
                partner.city = partner.microfinance_commune_id.name
                if partner.microfinance_commune_id.postal_code:
                    partner.zip = partner.microfinance_commune_id.postal_code
                partner.microfinance_district_id = partner.microfinance_commune_id.district_id
                partner.microfinance_region_id = partner.microfinance_commune_id.region_id
            if partner.microfinance_fokontany_id.postal_code:
                partner.zip = partner.microfinance_fokontany_id.postal_code

    @api.onchange('microfinance_spouse_id')
    def _onchange_microfinance_spouse_phone(self):
        # phone en priorité, mobile en repli si phone est vide sur la fiche du conjoint ; ne
        # touche jamais à la fiche du conjoint elle-même (spouse_phone n'est pas related, cf.
        # commentaire sur le champ). Ne préremplit que si une valeur est trouvée : si le
        # conjoint n'a ni phone ni mobile, la saisie manuelle reste possible sans être écrasée.
        for partner in self:
            spouse_phone = partner.microfinance_spouse_id.phone or partner.microfinance_spouse_id.mobile
            if spouse_phone:
                partner.microfinance_spouse_phone = spouse_phone

    @api.constrains('company_id', 'microfinance_client_type')
    def _check_microfinance_company_required(self):
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            if not partner.company_id:
                raise ValidationError(_('La société (agence) est obligatoire pour un client microfinance.'))

    @api.constrains('microfinance_partner_type', 'microfinance_client_type', 'is_company',
                    'microfinance_id_type', 'microfinance_id_number')
    def _check_microfinance_cin_required(self):
        # Uniquement pour un client particulier : un garant, un conjoint ou une société partagent
        # le même bloc identité sans être clients. Nécessaire au blocage inter-agences, qui
        # identifie un client par son CIN. Lit toujours la valeur stockée sur le record (jamais
        # vals) : le N° CIN saisi (microfinance_id_number_display) y est ramené avant la
        # validation par _microfinance_fold_id_number_display().
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            if (partner.microfinance_partner_type != 'client' or partner.is_company
                    or partner.microfinance_client_type != 'individual'):
                continue
            number = partner.microfinance_id_number or ''
            if partner.microfinance_id_type in ('passport', 'other'):
                if not number.strip():
                    raise ValidationError(_("Le numéro de la pièce d'identité est obligatoire pour un client particulier."))
            elif not re.sub(r'\D', '', number):
                raise ValidationError(_('Le numéro de CIN est obligatoire pour un client particulier.'))

    @api.model
    def _microfinance_fold_id_number_display(self, vals, id_type):
        """Remplace « N° CIN » (microfinance_id_number_display, calculé non stocké) par le champ
        stocké microfinance_id_number dans vals, avec la même normalisation que son inverse
        (chiffres seuls pour un CIN, valeur brute sinon).

        Odoo valide les contraintes des champs stockés AVANT d'exécuter l'inverse d'un champ non
        stocké (models.py write/_create) : sans ce repli, la contrainte de CIN obligatoire voit
        un numéro encore vide au moment où l'agent vient de le saisir."""
        if 'microfinance_id_number_display' not in vals:
            return
        value = vals.pop('microfinance_id_number_display') or ''
        vals['microfinance_id_number'] = re.sub(r'\D', '', value) if id_type == 'cin' else value

    # --- Numéro de compte client (permanent) ---
    # Attribué une seule fois, à la création de la fiche, dès que ce contact est reconnu comme
    # client microfinance (microfinance_partner_type == 'client'). Sert de référence unique
    # affichée sur tous les dossiers d'instruction de ce client (microfinance_loan_application.name
    # devient un related vers ce champ) — ne change jamais après attribution.
    microfinance_account_number = fields.Char(
        string='Numéro de compte client', readonly=True, copy=False,
        help="Numéro de compte permanent (format AGENCE/NNNNNN), attribué automatiquement et "
             "une seule fois à la création de la fiche, dès que ce contact est un client "
             "microfinance. Sert de référence unique pour ce client sur tous ses dossiers "
             "d'instruction — ne change jamais, non modifiable manuellement.",
    )

    def _assign_microfinance_account_number(self):
        self.ensure_one()
        if self.microfinance_account_number:
            return
        company = self.company_id or self.env.company
        number = company._get_or_create_numbering_sequence('microfinance.partner.account')
        self.with_context(microfinance_allow_account_number_write=True).write({
            'microfinance_account_number': '%s/%s' % (company.agency_code, number),
        })

    # --- Communs ---
    microfinance_internal_reference = fields.Char(string='Référence interne')
    microfinance_statistical_number = fields.Char(string='Numéro statistique')
    microfinance_category_1 = fields.Many2one('microfinance.client.category', string='Catégorie 1')
    microfinance_category_2 = fields.Many2one('microfinance.client.category', string='Catégorie 2')
    microfinance_category_3 = fields.Many2one('microfinance.client.category', string='Catégorie 3')
    microfinance_exit_date = fields.Date(string="Date de sortie")
    microfinance_exit_reason = fields.Text(string="Motif de sortie")
    microfinance_blacklist_ids = fields.One2many('microfinance.client.blacklist', 'partner_id', string='Liste noire')
    microfinance_is_blacklisted = fields.Boolean(compute='_compute_microfinance_is_blacklisted', store=True)

    # --- Crédit ---
    microfinance_loan_ids = fields.One2many('microfinance.loan', 'partner_id', string='Crédits')
    microfinance_loan_count = fields.Integer(compute='_compute_microfinance_loan_count')
    microfinance_loan_account_ids = fields.One2many(
        'microfinance.loan.account', 'partner_id', string='Compte crédit')
    microfinance_loan_account_loan_count = fields.Integer(
        compute='_compute_microfinance_loan_account_loan_count')

    @api.depends('microfinance_loan_ids')
    def _compute_microfinance_loan_count(self):
        for partner in self:
            partner.microfinance_loan_count = len(partner.microfinance_loan_ids)

    @api.depends('microfinance_loan_account_ids.loan_count')
    def _compute_microfinance_loan_account_loan_count(self):
        for partner in self:
            partner.microfinance_loan_account_loan_count = sum(
                partner.microfinance_loan_account_ids.mapped('loan_count'))

    def _get_or_create_microfinance_loan_account(self):
        """Ouvre (ou réutilise) le compte crédit conteneur de ce client pour sa société — pas de
        logique métier dessus à ce stade (cf. microfinance_loan_account.py), uniquement pour
        éviter une migration de données plus tard. Idempotent : sans effet si un compte existe
        déjà pour ce client et cette société (contrainte SQL unique(partner_id, company_id))."""
        self.ensure_one()
        company = self.company_id or self.env.company
        Account = self.env['microfinance.loan.account']
        existing = Account.search([
            ('partner_id', '=', self.id), ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            return existing
        return Account.create({'partner_id': self.id, 'company_id': company.id})

    def action_view_microfinance_loan_account(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Compte crédit',
            'res_model': 'microfinance.loan.account',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_microfinance_loans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crédits',
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    # --- Crédit : sélection produit (indépendant / progressif) et dossier courant ---
    # TODO(fusion): la réutilisation excluait auparavant aussi les dossiers 'refused' (rejeté,
    # un nouveau dossier peut être retenté) — plus d'équivalent direct depuis la simplification
    # du cycle de microfinance.loan.application (draft/visite/contre_visite/fait), même sujet
    # que le TODO sur _microfinance_product_change_unlocked() ci-dessous. Seul le critère
    # loan_id (dossier déjà transformé en crédit) reste appliqué pour l'instant.

    microfinance_product_policy = fields.Selection([
        ('independent', 'Produit indépendant'),
        ('progressive', 'Produit progressif'),
    ], string='Politique de produit', compute='_compute_microfinance_product_policy',
        help="Reflet en lecture seule du réglage global (Microfinance > Configuration > "
             "Paramètres), unique pour toutes les agences : détermine le domaine du champ "
             "Produit ci-dessous. Non modifiable depuis la fiche client.",
    )
    microfinance_selected_product_id = fields.Many2one(
        'microfinance.loan.product', string='Produit sélectionné',
        help="Produit visé par ce client pour son prochain crédit. Optionnel (client "
             "épargne uniquement, ou aucun produit encore choisi). Non modifiable tant que "
             "le dossier ou le crédit en cours sur le produit actuellement sélectionné n'est "
             "pas rejeté ou entièrement remboursé.",
    )
    microfinance_current_loan_application_id = fields.Many2one(
        'microfinance.loan.application', string='Dossier de crédit courant', readonly=True, copy=False,
        help="Dossier d'instruction associé au produit sélectionné ci-dessus : réutilisé tant "
             "qu'il n'est ni rejeté ni transformé en crédit clôturé ou annulé, sinon recréé "
             "automatiquement à l'enregistrement.",
    )
    microfinance_progressive_eligible_product_ids = fields.Many2many(
        'microfinance.loan.product', compute='_compute_microfinance_progressive_eligible_products',
        string='Produits progressifs éligibles',
        help="Produits de programme progressif actuellement accessibles à ce client : la 1ère "
             "étape de chaque programme (aucun prérequis), et les étapes suivantes dont le prêt "
             "précédent est clôturé sans retard bloquant (statut 'Éligible' ou 'Avertissement').",
    )

    @api.depends()
    def _compute_microfinance_product_policy(self):
        # Réglage global unique (Microfinance > Configuration > Paramètres), jamais par
        # société : pas de dépendance de champ, relu depuis ir.config_parameter à chaque
        # accès (cf. prompt correctif politique produit globale).
        policy = self.env['ir.config_parameter'].sudo().get_param(
            MICROFINANCE_PRODUCT_POLICY_PARAM, 'independent')
        for partner in self:
            partner.microfinance_product_policy = policy

    @api.depends('company_id', 'microfinance_loan_ids.state', 'microfinance_loan_ids.product_id')
    def _compute_microfinance_progressive_eligible_products(self):
        Step = self.env['microfinance.loan.progressive.program.step'].sudo()
        Loan = self.env['microfinance.loan'].sudo()
        # Instance jetable (jamais enregistrée) pour réutiliser _evaluate_progressive_eligibility
        # tel quel plutôt que de dupliquer la logique déjà validée sur loan.application.
        evaluator = self.env['microfinance.loan.application'].new()
        all_steps = Step.search([])
        for partner in self:
            eligible = self.env['microfinance.loan.product']
            for step in all_steps.filtered(lambda s: s.product_id.company_id == partner.company_id):
                if step.sequence_number <= 1:
                    eligible |= step.product_id
                    continue
                prior_step = Step.search([
                    ('program_id', '=', step.program_id.id),
                    ('sequence_number', '=', step.sequence_number - 1),
                ], limit=1)
                if not prior_step:
                    eligible |= step.product_id
                    continue
                prior_loans = Loan.search([
                    ('partner_id', '=', partner.id),
                    ('product_id', '=', prior_step.product_id.id),
                ])
                if not prior_loans:
                    continue
                status, _message = evaluator._evaluate_progressive_eligibility(prior_loans, prior_step)
                if status in ('eligible', 'warning'):
                    eligible |= step.product_id
            partner.microfinance_progressive_eligible_product_ids = eligible

    def _microfinance_product_change_unlocked(self, application):
        # TODO(fusion): plus d'état 'refused' explicite depuis la simplification du cycle de
        # microfinance.loan.application (draft/visite/contre_visite/fait) — l'ancien
        # déblocage "dossier refusé" n'a plus de déclencheur direct. En l'état, un dossier
        # sans loan_id reste verrouillé quel que soit son état (fail-safe : plus proche du
        # comportement "en cours" que d'un déblocage inventé). Si un scénario de refus
        # explicite doit rouvrir la sélection de produit, à rattacher ici une fois tranché
        # avec Micka — même sujet que le TODO sur _check_committee_eligibility côté
        # microfinance.loan.application.
        self.ensure_one()
        if not application:
            return True
        if application.loan_id:
            # Un crédit annulé n'a jamais été décaissé (cf. PRIOR_LOAN_STATES qui l'exclut déjà
            # des prêts antérieurs réalisés) : il ne doit pas bloquer un nouveau choix de produit.
            return application.loan_id.state in ('closed', 'cancelled')
        return False

    microfinance_product_change_locked = fields.Boolean(
        compute='_compute_microfinance_product_lock',
        help="Vrai si le champ produit ne peut pas être modifié (dossier en cours "
             "d'instruction, ou crédit décaissé non encore entièrement remboursé).",
    )
    microfinance_product_lock_message = fields.Char(compute='_compute_microfinance_product_lock')

    @api.depends(
        'microfinance_current_loan_application_id.state',
        'microfinance_current_loan_application_id.loan_id.state',
    )
    def _compute_microfinance_product_lock(self):
        for partner in self:
            application = partner.microfinance_current_loan_application_id
            locked = bool(application) and not partner._microfinance_product_change_unlocked(application)
            partner.microfinance_product_change_locked = locked
            partner.microfinance_product_lock_message = locked and _(
                "Le produit ne peut être changé tant que le crédit en cours sur '%s' n'est pas "
                "entièrement remboursé (ou le dossier rejeté)."
            ) % application.loan_product_id.display_name

    @api.constrains('microfinance_selected_product_id')
    def _check_microfinance_product_change_allowed(self):
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            application = partner.microfinance_current_loan_application_id
            if not application or application.loan_product_id == partner.microfinance_selected_product_id:
                continue
            if not partner._microfinance_product_change_unlocked(application):
                raise ValidationError(_(
                    "Le produit ne peut être changé tant que le crédit en cours sur '%s' n'est "
                    "pas entièrement remboursé (ou le dossier rejeté)."
                ) % application.loan_product_id.display_name)

    @api.constrains('microfinance_selected_product_id')
    def _check_microfinance_product_matches_policy(self):
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            product = partner.microfinance_selected_product_id
            if not product:
                continue
            if partner.microfinance_product_policy == 'independent' and product.is_progressive_step:
                raise ValidationError(_(
                    "Le produit '%s' fait partie d'un programme progressif : la politique de "
                    "produit actuelle (Microfinance > Configuration > Paramètres) est réglée "
                    "sur 'Produit indépendant'."
                ) % product.display_name)
            if partner.microfinance_product_policy == 'progressive' and (
                product not in partner.microfinance_progressive_eligible_product_ids
            ):
                raise ValidationError(_(
                    "Le produit '%s' n'est pas (ou plus) accessible à ce client selon la "
                    "politique de produit progressif actuellement configurée."
                ) % product.display_name)

    def _get_or_create_loan_application(self):
        self.ensure_one()
        product = self.microfinance_selected_product_id
        if not product:
            return False
        Application = self.env['microfinance.loan.application']
        application = Application.search([
            ('partner_id', '=', self.id),
            ('loan_product_id', '=', product.id),
            ('loan_id', '=', False),
        ], limit=1)
        created = False
        if not application:
            application = Application.create({
                'partner_id': self.id,
                'loan_product_id': product.id,
                'company_id': self.company_id.id or self.env.company.id,
            })
            created = True
        if self.microfinance_current_loan_application_id != application:
            self.microfinance_current_loan_application_id = application.id
        self._notify_microfinance_loan_application(application, created)
        return application

    def _notify_microfinance_loan_application(self, application, created):
        self.ensure_one()
        message = (
            _("Nouveau dossier de crédit brouillon créé : %s.") % application.name
            if created else
            _("Dossier de crédit existant réutilisé : %s.") % application.name
        )
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': 'success',
            'title': _('Dossier de crédit'),
            'message': message,
            'sticky': False,
        })

    @api.model
    def _check_no_active_loan_elsewhere(self, cin, company_id):
        """Bloque si un client de même CIN a un crédit en cours (ACTIVE_LOAN_STATES) dans une
        autre agence que company_id. Point de vérité unique du blocage inter-agences.

        Limite connue et acceptée : aucun verrou inter-agences, deux agences qui décaissent au
        même instant pour un même CIN peuvent passer toutes les deux."""
        digits = re.sub(r'\D', '', cin or '')
        if not digits:
            return
        # sudo() limité à cette recherche : la règle multi-société masque les autres agences.
        other_loans = self.env['microfinance.loan'].sudo().search([
            ('company_id', '!=', company_id),
            ('state', 'in', ACTIVE_LOAN_STATES),
            ('partner_id.microfinance_id_type', '=', 'cin'),
            ('partner_id.microfinance_id_number', '!=', False),
        ]).filtered(
            lambda loan: re.sub(r'\D', '', loan.partner_id.microfinance_id_number or '') == digits
        )
        if not other_loans:
            return
        agencies = sorted(set(other_loans.mapped('company_id.name')))
        raise ValidationError(_(
            "Ce client a un crédit en cours dans une autre agence : %s. Il doit d'abord solder "
            "son crédit, puis demander un transfert de compte vers cette agence."
        ) % ', '.join(agencies))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Jamais saisi manuellement, même à la création : uniquement attribué par
            # _assign_microfinance_account_number() ci-dessus, sur la base de la séquence dédiée.
            vals.pop('microfinance_account_number', None)
            self._microfinance_fold_id_number_display(vals, vals.get('microfinance_id_type'))
            if self._microfinance_is_unauthorized_client_creation(vals):
                self._microfinance_raise_client_creation_forbidden()
            if self.env.context.get(MICROFINANCE_PARTNER_CREATE_FLAG):
                self._microfinance_check_officer_assignable(vals)
            if self.env.context.get('microfinance_context') and vals.get('microfinance_id_type') == 'cin':
                # Avant super().create() : évite de consommer un numéro de compte permanent
                # (séquence non transactionnelle) pour un client finalement refusé.
                self._check_no_active_loan_elsewhere(
                    vals.get('microfinance_id_number') or vals.get('microfinance_id_number_display'),
                    vals.get('company_id') or self.env.company.id,
                )
        partners = super().create(vals_list)
        for partner in partners:
            if partner.microfinance_partner_type == 'client':
                partner._assign_microfinance_account_number()
        if self.env.context.get('microfinance_context'):
            for partner in partners:
                if partner.microfinance_selected_product_id:
                    partner._get_or_create_loan_application()
                # Compte crédit conteneur ouvert au même moment que le compte épargne principal
                # (cf. microfinance_savings_management.res_partner.create()), pour rester
                # cohérent dans le cycle de vie du client — même déclencheur, même garde-fou.
                if partner.microfinance_partner_type == 'client':
                    partner._get_or_create_microfinance_loan_account()
        return partners

    _MICROFINANCE_CIN_GUARD_FIELDS = {
        'microfinance_id_type', 'microfinance_id_number', 'microfinance_id_number_display', 'company_id',
    }

    def write(self, vals):
        if 'microfinance_account_number' in vals and not self.env.context.get(
            'microfinance_allow_account_number_write'
        ):
            raise ValidationError(_(
                'Le numéro de compte client est permanent : il ne peut jamais être modifié '
                'manuellement.'
            ))
        if vals.get('microfinance_partner_type') == 'client' and self._microfinance_is_unauthorized_client_creation(vals) \
                and any(partner.microfinance_partner_type != 'client' for partner in self):
            self._microfinance_raise_client_creation_forbidden()
        if 'microfinance_id_number_display' in vals:
            if 'microfinance_id_type' not in vals and len(set(self.mapped('microfinance_id_type'))) > 1:
                # Types de pièce différents : la normalisation dépend de chaque fiche.
                for partner in self:
                    partner.write(dict(vals))
                return True
            vals = dict(vals)
            self._microfinance_fold_id_number_display(
                vals, vals.get('microfinance_id_type', self[:1].microfinance_id_type))
        if self.env.context.get('microfinance_context') and self._MICROFINANCE_CIN_GUARD_FIELDS & set(vals):
            for partner in self:
                id_type = vals.get('microfinance_id_type', partner.microfinance_id_type)
                if id_type != 'cin':
                    continue
                if 'microfinance_id_number' in vals or 'microfinance_id_number_display' in vals:
                    cin = vals.get('microfinance_id_number') or vals.get('microfinance_id_number_display')
                else:
                    cin = partner.microfinance_id_number
                self._check_no_active_loan_elsewhere(
                    cin, vals.get('company_id') or partner.company_id.id or self.env.company.id)
        result = super().write(vals)
        if self.env.context.get('microfinance_context') and 'microfinance_selected_product_id' in vals:
            for partner in self:
                if partner.microfinance_selected_product_id:
                    partner._get_or_create_loan_application()
        return result

    # --- Particulier : Identification ---
    microfinance_registration_number = fields.Char(string="N° d'enregistrement")
    microfinance_id_type = fields.Selection([
        ('cin', 'CIN'), ('passport', 'Passeport'), ('other', 'Autre'),
    ], string="Type de pièce d'identité")
    microfinance_id_number = fields.Char(string="N° pièce d'identité")
    microfinance_id_issue_date = fields.Date(string='Date de délivrance')
    microfinance_id_issue_place = fields.Char(string='Lieu de délivrance')
    microfinance_id_duplicate_date = fields.Date(string='Duplicata délivré le')
    microfinance_id_duplicate_place = fields.Char(string='Duplicata délivré à')
    microfinance_birthdate = fields.Date(string='Date de naissance')
    microfinance_birth_place = fields.Char(string='Lieu de naissance')
    microfinance_gender = fields.Selection([('m', 'Masculin'), ('f', 'Féminin')], string='Genre')
    microfinance_marital_status = fields.Selection([
        ('single', 'Célibataire'), ('married', 'Marié(e)'), ('cohabiting', 'Union libre'),
        ('divorced', 'Divorcé(e)/Séparé(e)'), ('widowed', 'Veuf/Veuve'),
    ], string='Situation matrimoniale')
    microfinance_profession = fields.Many2one(
        'microfinance.profession', string='Profession',
        help="Autocomplete sur un référentiel configurable (menu Microfinance > Configuration "
             "> Professions), plutôt qu'une liste figée : une institution peut y ajouter ses "
             "propres valeurs à tout moment.",
    )
    # Générique (pas préfixé "spouse_") : réutilisable aussi bien pour le client que pour son
    # conjoint (lu via microfinance_spouse_id.microfinance_employer sur le dossier d'instruction,
    # cf. correctif synchronisation Bloc A) — symétrique à microfinance_profession.
    microfinance_employer = fields.Char(string='Employeur')
    microfinance_education_level = fields.Selection([
        ('none', 'Aucun'), ('primary', 'Primaire'), ('secondary', 'Secondaire'), ('higher', 'Supérieur'),
    ], string="Niveau d'éducation")

    # --- Particulier : Famille et compte ---
    microfinance_spouse_id = fields.Many2one('res.partner', string='Conjoint')
    # Char indépendant (pas related) : contrairement à microfinance_spouse_profession, ce champ
    # doit pouvoir se replier sur mobile quand phone est vide (cf. onchange ci-dessous) — un
    # related='microfinance_spouse_id.phone' écrirait ce repli directement sur le phone du
    # conjoint, un effet de bord non voulu sur sa fiche. Auto-rempli par onchange, jamais
    # verrouillé (même logique que city/zip).
    microfinance_spouse_phone = fields.Char(string='Téléphone du conjoint')
    # related/store/readonly=False : le conjoint est un contact à part entière (souvent lui-même
    # client), la profession se lit et s'écrit directement sur sa fiche plutôt que d'être
    # dupliquée ici — décision confirmée, une seule source de vérité.
    microfinance_spouse_profession = fields.Many2one(
        'microfinance.profession', related='microfinance_spouse_id.microfinance_profession',
        string='Profession du conjoint', store=True, readonly=False)
    microfinance_next_of_kin_name = fields.Char(string='Personne à contacter')
    microfinance_next_of_kin_address = fields.Char(string='Adresse contact')
    microfinance_next_of_kin_phone = fields.Char(string='Téléphone du contact')
    microfinance_housing_status = fields.Selection([
        ('owner_inheritance', 'Propriétaire (héritage)'),
        ('owner_purchase', 'Propriétaire (achat)'),
        ('owner_donation', 'Propriétaire (donation)'),
        ('tenant_free', 'Locataire sans loyer'),
        ('tenant_paying', 'Locataire avec loyer'),
    ], string="Statut d'occupation du logement")
    microfinance_co_holder_name = fields.Char(string='Co-titulaire')
    microfinance_guarantor_id = fields.Many2one('res.partner', string='Garant')
    microfinance_required_signatures = fields.Integer(string='Signatures requises', default=1)

    # --- Société : Identité légale (NIF/STAT/RCS remplacent le N° TVA natif) ---
    microfinance_trade_name = fields.Char(string='Nom commercial')
    microfinance_acronym = fields.Char(string='Sigle')
    microfinance_enterprise_type = fields.Selection([
        ('sole_proprietorship', 'Entreprise individuelle'), ('sarl', 'SARL'), ('sa', 'SA'),
        ('cooperative', 'Coopérative'), ('association', 'Association'), ('ngo', 'ONG'),
        ('public', 'Institution publique'), ('other', 'Autre'),
    ], string="Type d'entreprise")
    microfinance_nif = fields.Char(string='NIF')
    microfinance_stat = fields.Char(string='STAT')
    microfinance_rcs = fields.Char(string='RCS')
    microfinance_legal_form = fields.Char(string='Forme juridique')
    microfinance_creation_date = fields.Date(string='Date création')

    # --- Société : Activité et finances ---
    microfinance_business_sector = fields.Char(string="Secteur d'activité")
    microfinance_main_activity = fields.Char(string='Activité principale')
    microfinance_share_capital = fields.Monetary(string='Capital social')
    microfinance_estimated_turnover = fields.Monetary(string='CA estimé')
    microfinance_employee_count = fields.Integer(string='Employés')

    # --- Société : Localisation étendue ---
    # Dépréciés au profit de microfinance_region_id / microfinance_district_id /
    # microfinance_commune_id / microfinance_fokontany_id (référentiels structurés). Conservés
    # tels quels dans l'attente d'un lot de migration séparé (rapprochement texte -> M2O à
    # valider explicitement avant toute suppression de données existantes) : 721 communes sur
    # 1645 ne sont pas encore rattachées à un district dans le référentiel (cf.
    # docs/unmatched_ambiguous_report.csv), tant que ce n'est pas traité tous les clients ne
    # peuvent pas être classés par district via le nouveau champ.
    microfinance_region = fields.Char(string='Région (ancien, texte libre)')
    microfinance_district = fields.Char(string='District (ancien, texte libre)')
    microfinance_commune = fields.Char(string='Commune (ancien, texte libre)')
    microfinance_locality = fields.Char(string='Localité (ancien, texte libre)')
    microfinance_commune_id = fields.Many2one('microfinance.geo.commune', string='Commune')
    microfinance_fokontany_id = fields.Many2one('microfinance.geo.fokontany', string='Fokontany')

    # --- Référentiel administratif (Loi n°2018-011) : nouvelle section, distincte de la
    # Résidence commune/fokontany (référentiel BCM) affichée dans la vue. ---
    microfinance_region_id = fields.Many2one('microfinance.geo.region', string='Région')
    microfinance_district_id = fields.Many2one('microfinance.geo.district', string='District')

    # --- Société : Fermeture ---
    microfinance_closure_date = fields.Date(string='Date de fermeture')
    microfinance_closure_reason = fields.Text(string='Motif')

    # --- Groupe ---
    microfinance_sub_group_count = fields.Integer(string='Nombre de sous-groupes')

    # --- Comité (Société + Groupe) et Membres (Groupe) ---
    microfinance_representative_ids = fields.One2many('microfinance.client.representative', 'partner_id', string='Comité')
    microfinance_member_ids = fields.One2many('microfinance.client.group.member', 'group_id', string='Membres du groupe')

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    microfinance_id_number_display = fields.Char(
        string='N° pièce (affiché)', compute='_compute_id_number_display', inverse='_inverse_id_number_display',
        help="Présentation en blocs de 3 chiffres pour la lisibilité (ex. 123 456 789 012 pour "
             "un CIN). La valeur brute (chiffres uniquement) reste stockée dans le champ "
             "technique 'N° pièce d'identité' — cette présentation n'affecte ni la validation "
             "12 chiffres ni la recherche. Sans effet pour un type de pièce autre que CIN "
             "(passeport, autre), affiché tel quel.",
    )

    @api.depends('microfinance_id_number', 'microfinance_id_type')
    def _compute_id_number_display(self):
        for partner in self:
            raw = partner.microfinance_id_number or ''
            if partner.microfinance_id_type == 'cin':
                digits = re.sub(r'\D', '', raw)
                partner.microfinance_id_number_display = ' '.join(digits[i:i + 3] for i in range(0, len(digits), 3)) if digits else ''
            else:
                partner.microfinance_id_number_display = raw

    def _inverse_id_number_display(self):
        for partner in self:
            value = partner.microfinance_id_number_display or ''
            if partner.microfinance_id_type == 'cin':
                partner.microfinance_id_number = re.sub(r'\D', '', value)
            else:
                partner.microfinance_id_number = value

    def get_contrat_address(self):
        """Adresse « monina ao amin'ny … » du contrat de crédit : concaténation de
        `street`, du fokontany (`microfinance_fokontany_id.name`) et de `city`, dans
        cet ordre, segments vides ignorés, séparés par « , ». Chaîne vide si aucun
        segment — le template garde le fragment sous t-if."""
        self.ensure_one()
        parts = (self.street, self.microfinance_fokontany_id.name, self.city)
        return ', '.join(part for part in parts if part)

    @api.depends('microfinance_blacklist_ids.active', 'microfinance_blacklist_ids.date_end')
    def _compute_microfinance_is_blacklisted(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.microfinance_is_blacklisted = any(
                b.active and (not b.date_end or b.date_end >= today) for b in partner.microfinance_blacklist_ids
            )

    @api.constrains('microfinance_id_type', 'microfinance_id_number')
    def _check_cin_format(self):
        for partner in self:
            if partner.microfinance_id_type == 'cin' and partner.microfinance_id_number:
                digits = re.sub(r'\D', '', partner.microfinance_id_number)
                if len(digits) != 12:
                    raise ValidationError(_('Le numéro de CIN doit contenir exactement 12 chiffres.'))

    @api.constrains('microfinance_id_type', 'microfinance_id_number')
    def _check_cin_unique(self):
        # Unicité globale (toute la base, toutes sociétés/usages confondus) : une CIN identifie
        # une personne physique unique, indépendamment de son rôle (client, garant, conjoint) ou
        # de l'usage de l'instance (microfinance, EAT, immobilier) — cf. audit
        # docs_dev/centralisation_identite_partner/AUDIT.md section 5, décision confirmée par
        # Micka. Comparaison sur les chiffres seuls (comme _check_cin_format) pour ignorer les
        # variations de présentation (espaces du widget microfinance_grouped_digits).
        for partner in self:
            if partner.microfinance_id_type != 'cin' or not partner.microfinance_id_number:
                continue
            digits = re.sub(r'\D', '', partner.microfinance_id_number)
            if not digits:
                continue
            # Comparaison sur les chiffres seuls (pas sur la chaîne stockée telle quelle) pour
            # ignorer les variations de présentation (espaces éventuels).
            candidates = self.env['res.partner'].search([
                ('id', '!=', partner.id),
                ('microfinance_id_type', '=', 'cin'),
                ('microfinance_id_number', '!=', False),
            ])
            duplicate = candidates.filtered(
                lambda p: re.sub(r'\D', '', p.microfinance_id_number or '') == digits
            )
            if duplicate:
                raise ValidationError(_(
                    'Ce numéro de CIN est déjà utilisé par un autre contact (%s).'
                ) % duplicate[:1].display_name)

    @api.constrains('microfinance_client_type', 'microfinance_nif')
    def _check_nif_format(self):
        for partner in self:
            if partner.microfinance_client_type == 'company' and partner.microfinance_nif:
                digits = re.sub(r'\D', '', partner.microfinance_nif)
                if len(digits) != 12:
                    raise ValidationError(_('Le NIF doit contenir exactement 12 chiffres.'))

    @api.constrains('microfinance_marital_status', 'microfinance_spouse_id', 'microfinance_spouse_phone')
    def _check_spouse_required_if_married(self):
        # Hors contexte microfinance, ce contact est partagé avec d'autres usages de l'instance
        # (EAT, immobilier) : aucune contrainte microfinance ne doit s'y appliquer.
        if not self.env.context.get('microfinance_context'):
            return
        for partner in self:
            if partner.microfinance_marital_status == 'married' and not (
                partner.microfinance_spouse_id and partner.microfinance_spouse_phone
            ):
                raise ValidationError(_(
                    'Le conjoint et son téléphone sont obligatoires pour un client marié.'
                ))
