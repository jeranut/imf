# -*- coding: utf-8 -*-
import base64
import math
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

try:
    from num2words import num2words
except ImportError:  # pragma: no cover
    # num2words fait partie des dépendances de requirements.txt d'Odoo (le core
    # l'utilise pour le libellé en lettres des chèques). Repli défensif : si absent,
    # get_amount_in_words() renvoie une chaîne vide plutôt que de casser le module.
    num2words = None


class MicrofinanceLoan(models.Model):
    _name = 'microfinance.loan'
    _description = 'Crédit microfinance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Emprunteur', required=True, tracking=True)
    product_id = fields.Many2one('microfinance.loan.product', string='Produit', required=True, tracking=True)
    fond_credit_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit rotatif', tracking=True,
        domain="[('active', '=', True), "
               "'|', ('date_cloture', '=', False), ('date_cloture', '>=', context_today().strftime('%Y-%m-%d')), "
               "'|', '&', ('scope', '=', 'single_company'), ('company_id', '=', company_id), ('scope', '=', 'multi_company')]",
        help="Fonds bailleur rotatif dont ce crédit consomme le solde disponible au décaissement. "
             "Un fonds « Agence unique » d'une autre société n'apparaît jamais dans ce domaine ; "
             "un fonds « Multi-agences » (scope='multi_company') est toujours proposé, quelle que "
             "soit la société courante.",
    )
    has_active_fond = fields.Boolean(
        string='Fonds actif disponible pour cette société', compute='_compute_has_active_fond',
        help="Vrai si au moins un fonds de crédit rotatif actif est visible pour la société de ce "
             "crédit (mêmes critères que le domaine de fond_credit_id ci-dessus : single_company de "
             "cette société, ou multi_company). Sert uniquement à rendre fond_credit_id visuellement "
             "obligatoire dans le formulaire ; le contrôle bloquant réel est serveur, dans "
             "_check_fond_disponibilite() ci-dessous, seul appelé depuis action_disburse().",
    )
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True, tracking=True)
    loan_account_id = fields.Many2one(
        'microfinance.loan.account', string='Compte crédit', index=True,
        help="Conteneur regroupant l'historique des crédits de ce client (cf. correctif "
             "numérotation) — pas de logique métier dessus à ce stade. Non required : les "
             "crédits déjà en base avant l'introduction de ce modèle restent sans compte "
             "associé, résolu paresseusement au prochain crédit du même client via "
             "res.partner._get_or_create_microfinance_loan_account() plutôt qu'une migration "
             "globale (volume négligeable à ce jour, décision validée par Micka).",
    )
    currency_id = fields.Many2one('res.currency', string='Devise', default=lambda self: self.env.company.currency_id, required=True)
    loan_amount = fields.Monetary(string='Montant crédit', required=True, tracking=True)
    term = fields.Integer(string='Nombre échéances', required=True, default=1, tracking=True)
    application_date = fields.Date(string='Date de demande', default=fields.Date.context_today, required=True)
    approval_date = fields.Date(string="Date d'approbation", readonly=True)
    # Découplage activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md) :
    # date du passage à 'active' (clic « Activer »), distincte de disbursement_date (sortie de
    # caisse effective au guichet). Sert de clé de file d'attente FIFO pour l'onglet
    # « Décaissements en attente » (get_pending_disbursements).
    activation_date = fields.Date(string="Date d'activation", readonly=True, copy=False)
    disbursement_date = fields.Date(string='Date de décaissement', readonly=True)
    closed_date = fields.Date(string='Date de clôture', readonly=True, copy=False)
    interest_rate = fields.Float(string='Taux intérêt annuel (%)', related='product_id.interest_rate', readonly=False, store=True)
    interest_method = fields.Selection(related='product_id.interest_method', readonly=False, store=True)
    repayment_frequency_mode = fields.Selection(
        related='product_id.repayment_frequency_mode', string='Mode périodicité (produit)', readonly=True,
    )
    allowed_repayment_frequency_ids = fields.Many2many(
        related='product_id.allowed_repayment_frequency_ids', string='Périodicités autorisées (produit)',
    )
    # Exposé pour les modifiers de vue (bouton « Envoyer les frais en caisse ») : les
    # expressions invisible= ne savent pas suivre product_id.xxx, il faut un champ du modèle.
    fee_charged_before_disbursement = fields.Boolean(
        related='product_id.fee_charged_before_disbursement', string='Frais exigés avant décaissement (produit)',
        readonly=True,
    )
    repayment_frequency_id = fields.Many2one(
        'microfinance.repayment.frequency', string='Périodicité de remboursement',
        compute='_compute_repayment_frequency_id', store=True, readonly=False,
        domain="[('id', 'in', allowed_repayment_frequency_ids)] if repayment_frequency_mode == 'client_choice' else []",
        help='Reprise automatiquement du produit si celui-ci impose une périodicité unique. '
             "Si le produit laisse le choix au client/agent, à sélectionner obligatoirement parmi "
             "les périodicités autorisées par le produit avant de générer l'échéancier.",
    )
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('enquete', 'Enquête'),
        ('avis_ca', 'Avis CA'),
        ('avis_cdag', 'Avis CDAG'),
        ('approved', 'Approuvé'),
        ('active', 'Actif'),
        ('closed', 'Clôturé'),
        ('defaulted', 'Défaut'),
        ('written_off', 'Radié'),
        ('cancelled', 'Annulé'),
    ], string='État', default='draft', tracking=True, index=True)
    officer_id = fields.Many2one('res.users', string='Agent crédit', default=lambda self: self.env.user, tracking=True)
    manager_id = fields.Many2one('res.users', string='Manager', tracking=True)
    finance_user_id = fields.Many2one('res.users', string='Utilisateur finance', tracking=True)
    collection_agent_id = fields.Many2one('res.users', string='Agent recouvrement', tracking=True)
    installment_amount = fields.Monetary(
        string='Échéance',
        help="Montant de la tranche périodique, calculé automatiquement à partir du montant du "
             "crédit et du nombre d'échéances (ou modifiable directement, ce qui recalcule alors "
             "le nombre d'échéances en retour). Aperçu avant génération de l'échéancier détaillé "
             "(installment_ids) - un aller-retour loan_amount/term <-> installment_amount ne "
             "redonne pas nécessairement le montant de départ exact, du fait des arrondis "
             "(installment_rounding_unit d'un côté, arrondi à l'entier du nombre d'échéances de "
             "l'autre) : comportement normal, pas un bug.")
    avis_ca_amount = fields.Monetary(
        string='Montant avis CA', tracking=True,
        help="Montant proposé par le Comité d'Agence (CA). Par défaut égal à loan_amount à "
             "l'entrée en état 'Avis CA' (action_ca_review), modifiable ensuite tant que le "
             "crédit reste dans cet état. Toute modification recalcule avis_ca_installment_amount "
             "(même mécanisme bidirectionnel que loan_amount/term/installment_amount ci-dessus) "
             "et se répercute par défaut sur le bloc Avis CDAG tant que celui-ci n'a pas été "
             "modifié explicitement (cf. avis_cdag_manually_set).")
    avis_ca_epargne_exigee = fields.Monetary(
        string='Épargne exigée (CA)',
        help="Saisie libre par défaut - ce module seul n'a aucune notion d'épargne garantie de "
             "crédit à calculer (ne participe pas au recalcul bidirectionnel montant/durée/"
             "échéance ci-dessus). Redéclaré en champ calculé (compute+store, lecture seule) par "
             "microfinance_savings_management s'il est installé - cf. docs_dev/epargne_exigee_"
             "ca_cdag/AUDIT.md et microfinance_loan_extension.py::_compute_avis_epargne_exigee.")
    avis_ca_installment_amount = fields.Monetary(
        string='Remboursement (CA)',
        help="Calculé automatiquement à partir de avis_ca_amount/avis_ca_term (même formule "
             "ceiling que installment_amount ci-dessus) - modifiable directement, ce qui "
             "recalcule alors avis_ca_term en retour.")
    avis_ca_term = fields.Integer(
        string='Durée avis CA (échéances)',
        help="Par défaut égal à term à l'entrée en état 'Avis CA'. Modifiable : recalcule "
             "avis_ca_installment_amount avec le nombre d'échéances proposé par le CA.")
    avis_cdag_amount = fields.Monetary(
        string='Montant avis CDAG', tracking=True,
        help="Hérite par défaut de avis_ca_amount à chaque modification du bloc CA, tant que le "
             "CDAG n'a pas modifié explicitement ce bloc (cf. avis_cdag_manually_set) - passé ce "
             "point, la cascade automatique CA -> CDAG s'arrête définitivement pour ce crédit.")
    avis_cdag_epargne_exigee = fields.Monetary(
        string='Épargne exigée (CDAG)',
        help="Saisie libre par défaut, mêmes règles que avis_ca_epargne_exigee ci-dessus - y "
             "compris la redéclaration en champ calculé par microfinance_savings_management.")
    avis_cdag_installment_amount = fields.Monetary(
        string='Remboursement (CDAG)',
        help="Calculé automatiquement à partir de avis_cdag_amount/avis_cdag_term, même "
             "mécanisme que le bloc Avis CA ci-dessus.")
    avis_cdag_term = fields.Integer(string='Durée avis CDAG (échéances)')
    avis_cdag_manually_set = fields.Boolean(
        string='Avis CDAG modifié manuellement', default=False, copy=False,
        help="Champ technique, non affiché en formulaire standard. Passe à True dès que "
             "avis_cdag_amount/avis_cdag_term diverge de avis_ca_amount/avis_ca_term (preuve "
             "d'une saisie manuelle du CDAG, par opposition à un recalcul automatique issu de la "
             "cascade CA -> CDAG, qui pose toujours ces deux paires à des valeurs identiques) ; "
             "ne repasse jamais à False. Sert uniquement de garde pour arrêter la cascade "
             "automatique CA -> CDAG une fois que le CDAG a pris la main (cf. "
             "_onchange_avis_ca_recompute_installment et les deux onchange du bloc CDAG "
             "ci-dessous).")
    # Chantier "Épargne exigée/disponible" (docs_dev/epargne_exigee_disponible/AUDIT.md,
    # microfinance_savings_management) : même patron que avis_ca_epargne_exigee ci-dessus - ce
    # module seul n'a aucune notion d'épargne garantie de crédit, ces deux champs restent
    # inertes (valeur nulle, jamais calculée) tant que microfinance_savings_management n'est pas
    # installé. Redéclarés en champs calculés (compute+store pour l'exigée, compute seul pour le
    # solde - jamais figé, toujours le solde réel courant) par ce module s'il est installé, cf.
    # microfinance_loan_extension.py::_compute_guarantee_savings_required/_compute_guarantee_
    # savings_balance. Déclarés ici (pas seulement dans l'extension) car
    # microfinance.loan.application.required_savings/available_savings (module de base) y sont
    # related= - un related= dont la cible n'existe pas encore au chargement du module de base
    # fait échouer le chargement (KeyError sur le setup du champ), constaté en tentant de les
    # déclarer uniquement dans l'extension épargne.
    guarantee_savings_required = fields.Monetary(
        string='Épargne garantie requise',
        help="Saisie libre par défaut - ce module seul n'a aucune notion d'épargne garantie de "
             "crédit. Redéclaré en champ calculé (compute+store, lecture seule) par "
             "microfinance_savings_management s'il est installé.")
    guarantee_savings_balance = fields.Monetary(
        string='Solde épargne garantie du client',
        help="Saisie libre par défaut, mêmes règles que guarantee_savings_required ci-dessus.")
    installment_ids = fields.One2many('microfinance.loan.installment', 'loan_id', string='Échéancier')
    payment_ids = fields.One2many('microfinance.loan.payment', 'loan_id', string='Remboursements')
    visit_ids = fields.One2many('microfinance.collection.visit', 'loan_id', string='Visites')
    move_ids = fields.One2many('account.move', 'microfinance_loan_id', string='Écritures comptables')
    application_ids = fields.One2many('microfinance.loan.application', 'loan_id', string='Enquêtes')
    principal_total = fields.Monetary(string='Total capital', compute='_compute_totals', store=True)
    interest_total = fields.Monetary(string='Total intérêts', compute='_compute_totals', store=True)
    penalty_total = fields.Monetary(string='Total pénalités', compute='_compute_totals', store=True)
    paid_total = fields.Monetary(string='Total payé', compute='_compute_totals', store=True)
    balance_total = fields.Monetary(string='Solde restant', compute='_compute_totals', store=True)
    overdue_amount = fields.Monetary(string='Montant en retard', compute='_compute_totals', store=True)
    overdue_installment_count = fields.Integer(string="Nombre d'échéances en retard", compute='_compute_totals', store=True)
    # Instantané figé : écrit par cron_update_overdue_and_penalties (quotidien) via
    # _get_max_overdue_days(), PAS un compute réactif (installment.state -> 'overdue' dépend
    # déjà du même cron). Permet le calcul du PAR par agent en pur read_group (dashboard
    # portefeuille, Lot 1) sans itérer les échéances de chaque crédit à chaque requête HTTP.
    max_days_overdue = fields.Integer(string='Jours de retard (max)', readonly=True, default=0, copy=False)
    provision_amount = fields.Monetary(compute='_compute_provision', store=True, string='Provision requise')
    provision_posted_amount = fields.Monetary(copy=False, readonly=True, default=0.0, string='Provision comptabilisée')
    scoring_profile_id = fields.Many2one(
        'microfinance.scoring.profile',
        string='Profil de scoring',
        domain="['|', ('product_id', '=', False), ('product_id', '=', product_id)]",
        copy=False,
        tracking=True,
    )
    internal_score = fields.Float(
        string='Score', copy=False, readonly=True, tracking=True,
        help='Score de scoring unique du crédit (plus haut = plus sûr), calculé par le moteur de '
             'scoring configurable (microfinance.scoring.profile/rule). Remplace l\'ancien score de '
             'risque codé en dur.',
    )
    risk_level = fields.Selection([
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique'),
    ], string='Niveau de risque', copy=False, readonly=True, tracking=True)
    scoring_decision = fields.Selection([
        ('recommended', 'Recommandé'),
        ('manual_review', 'Revue manuelle'),
        ('reject_recommended', 'Risqué / Rejet recommandé'),
    ], string='Décision scoring', copy=False, readonly=True, tracking=True)
    scoring_line_ids = fields.One2many('microfinance.scoring.line', 'loan_id', string='Règles appliquées', copy=False, readonly=True)
    scoring_line_count = fields.Integer(string='Nombre de règles de scoring', compute='_compute_counts')
    note = fields.Text(string='Note')
    installment_count = fields.Integer(string="Nombre d'échéances", compute='_compute_counts')
    payment_count = fields.Integer(string='Nombre de remboursements', compute='_compute_counts')
    visit_count = fields.Integer(string='Nombre de visites', compute='_compute_counts')
    move_count = fields.Integer(string="Nombre d'écritures", compute='_compute_counts')
    application_count = fields.Integer(string="Nombre d'enquêtes", compute='_compute_counts')
    reschedule_count = fields.Integer(string='Nombre de rééchelonnements', default=0, copy=False, readonly=True, tracking=True)
    reschedule_history_ids = fields.One2many(
        'microfinance.loan.reschedule.history', 'loan_id', string='Historique de rééchelonnement', readonly=True,
    )
    co_borrower_id = fields.Many2one('res.partner', string='Co-emprunteur', tracking=True)
    guarantee_ids = fields.One2many('microfinance.loan.guarantee', 'loan_id', string='Garanties')
    guarantee_total = fields.Monetary(
        compute='_compute_guarantee_total', store=True, string='Total garanties validées',
        help='Somme des valeurs reconnues (recognized_value, après application du ratio de '
             'valorisation par type) des garanties validées, pas de la valeur brute estimée.',
    )
    fee_amount_due = fields.Monetary(compute='_compute_fee_amount', store=True, string='Frais de dossier dus')
    fee_paid = fields.Boolean(string='Frais payés', default=False, readonly=True, copy=False)
    # Marqueur "envoyé au guichet caisse" (docs_dev/guichet_caisse/AUDIT_frais.md + prompt
    # "Lot 1 étendu - Onglet Frais") : posé par action_send_fee_to_cashier() depuis la fiche
    # crédit (group_microfinance_finance), fait apparaître le dossier dans l'onglet "Frais" du
    # guichet. L'encaissement comptable réel a lieu au passage en caisse (action_charge_fee
    # via register_operation). Champ historique : jamais remis à False - une fois fee_paid,
    # c'est fee_paid qui garde contre un second envoi/encaissement.
    fee_sent_to_cashier = fields.Boolean(
        string='Frais envoyés en caisse', default=False, copy=False, readonly=True)
    # Flux Option A (docs_dev/frais_dossier_creance_pcec/) : deux écritures distinctes.
    # fee_receivable_move_id = engagement créé à l'approbation (débit "frais à recevoir" 208005 /
    # crédit commission 717003), uniquement pour les produits "frais exigés avant décaissement".
    # fee_move_id = écriture de RÈGLEMENT créée au clic "Encaisser" (débit caisse / crédit
    # 208005) - sémantique inchangée par rapport à avant ce lot (d'où le nom conservé), seul le
    # compte crédité passe de 717003 à la créance.
    fee_receivable_move_id = fields.Many2one(
        'account.move', string='Écriture engagement frais', readonly=True, copy=False)
    fee_move_id = fields.Many2one('account.move', string='Écriture de frais', readonly=True, copy=False)
    # Habillage badge du bloc frais (docs_dev/badges_fee_guarantee/) : dérivé, non stocké -
    # fee_amount_due et fee_paid, dont il dépend, sont déjà stockés. Rendu en widget="badge"
    # (vert = payé, rouge = non payé), sur le modèle du badge risk_level du scoring.
    fee_payment_state = fields.Selection(
        [('none', 'Sans frais'), ('unpaid', 'Non payé'), ('paid', 'Payé')],
        string='État frais de dossier', compute='_compute_fee_payment_state')
    net_disbursed_amount = fields.Monetary(
        compute='_compute_net_disbursed_amount', store=True, string='Montant net remis au client',
        help='Montant réellement remis en caisse au client. Égal au montant du crédit tant que les '
             "frais de dossier sont encaissés séparément (fee_charged_before_disbursement=True) ; "
             "sinon égal au montant du crédit diminué des frais de dossier dus, nettés directement "
             "dans l'écriture de décaissement. Le capital dû (loan_amount) reste toujours le montant "
             "plein : les frais ne réduisent jamais le principal remboursable.",
    )
    bypass_cash_balance = fields.Boolean(
        string='Déroger au contrôle de solde de caisse', default=False,
        help="Si activé, le décaissement est autorisé même si le solde comptable du journal de "
             "décaissement (uniquement vérifié pour un journal de type 'Espèces') deviendrait "
             "négatif. Dérogation distincte des autres contrôles de décaissement.",
    )
    signed_contract = fields.Binary(
        string='Contrat signé', attachment=True, copy=False,
        help="Contrat de crédit signé par l'emprunteur. Se téléverse une fois le crédit "
             "approuvé et constitue un prérequis à l'activation : action_disburse() refuse "
             "le décaissement tant que ce champ est vide. À l'enregistrement, le fichier est "
             "aussi posté dans le fil de communication du dossier. Sa pièce jointe ne peut "
             "plus être supprimée depuis le chatter (cf. ir.attachment.unlink). Se dépose "
             "exclusivement via le wizard microfinance.loan.contract.signature.wizard (bouton "
             "\"Téléverser le contrat signé\") : une fois contract_signature_date renseigné, "
             "ce champ est définitivement verrouillé, y compris pour un remplacement (cf. "
             "_check_contract_signature_locked()).",
    )
    signed_contract_filename = fields.Char(string='Nom du fichier contrat signé', copy=False)
    contract_signature_date = fields.Date(
        string='Date de signature du contrat', copy=False,
        help="Date à laquelle l'emprunteur a signé le contrat de crédit, saisie une seule "
             "fois via le wizard de confirmation (bouton \"Téléverser le contrat signé\") au "
             "moment du dépôt du fichier signé - pré-remplie à la date du jour dans le "
             "wizard mais librement modifiable avant confirmation. Verrouillée "
             "définitivement dès qu'elle est renseignée : ni cette date, ni signed_contract/ "
             "signed_contract_filename ne peuvent plus être modifiés ensuite, quel que soit "
             "l'état du dossier (y compris closed/defaulted/written_off) ou le groupe de "
             "l'utilisateur (cf. _check_contract_signature_locked(), sans dérogation) - "
             "décision Micka, docs_dev/date_signature_contrat/.",
    )

    # États où le crédit reste modifiable avant activation (avant tout paiement possible) :
    # échéancier/échéance encore librement recalculables. Utilisée par action_generate_schedule
    # et par les onchange d'aperçu installment_amount/installment_ids ci-dessous — remplace la
    # liste précédemment dupliquée en dur dans action_generate_schedule.
    _EDITABLE_SCHEDULE_STATES = ('draft', 'enquete', 'avis_ca', 'avis_cdag', 'approved')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                # agency_code est obligatoire sur res.company (NOT NULL) : toute société valide
                # en possède un, pas besoin de re-vérifier ici.
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                number = company._get_or_create_numbering_sequence('microfinance.loan.agency')
                vals['name'] = '%s/%s' % (company.agency_code, number)
            if vals.get('partner_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                # Numéro de compte permanent (microfinance_account_number) : plus limité à
                # microfinance_partner_type == 'client' (cf. docs_dev/epargne_exigee_display/
                # AUDIT_LOT0_conteneur_epargne.md - constaté en réel sur des partenaires
                # 'bailleur' ou de type vide ayant pourtant un crédit, donc un loan_account_id,
                # mais aucun numéro permanent, cassant la synchronisation avec le futur
                # conteneur épargne). Tout partenaire qui emprunte en a désormais besoin, quel
                # que soit son type - idempotent (no-op si déjà assigné).
                partner._assign_microfinance_account_number()
                if not vals.get('loan_account_id'):
                    # Rattrapage paresseux (cf. correctif microfinance.loan.account) : couvre
                    # aussi bien un client déjà en base avant l'introduction de ce modèle qu'un
                    # client créé hors microfinance_context (où le déclencheur normal,
                    # res.partner.create(), ne s'exécute pas) — pas de script de migration
                    # global (volume négligeable).
                    vals['loan_account_id'] = partner._get_or_create_microfinance_loan_account().id
        return super().create(vals_list)

    # Champs dont l'écriture doit répercuter l'avis courant (CA ou CDAG) sur loan_amount/term/
    # installment_amount - cf. write() et _propagate_avis_to_loan() ci-dessous. Décision actée du
    # chantier Avis CA/CDAG : répercussion immédiate à chaque sauvegarde, pas seulement à une
    # transition de statut (cf. docs_dev/workflow_avis_ca_cdag/).
    _AVIS_PROPAGATION_TRIGGER_FIELDS = {
        'avis_ca_amount', 'avis_ca_term', 'avis_ca_installment_amount',
        'avis_cdag_amount', 'avis_cdag_term', 'avis_cdag_installment_amount',
    }

    # Champs dont l'écriture doit (re)générer installment_ids - cf. write() ci-dessous. Corrige le
    # bug documenté dans docs_dev/echeancier_obsolete_readonly/AUDIT.md (Option 2) : les onchange
    # _onchange_loan_amount_recompute_installment/_onchange_installment_amount_recompute_terms
    # recalculent bien installment_ids en mémoire pour l'aperçu formulaire, mais ce champ est
    # marqué readonly="1" en vue - Odoo n'enregistre jamais un champ readonly modifié par
    # onchange (cf. AUDIT.md étape 1), donc l'échéancier réel en base restait figé sur son ancien
    # contenu après toute modification de ces champs. Généralise ici exactement le pattern déjà
    # utilisé par _propagate_avis_to_loan() ci-dessous, qui régénère correctement (parce que via
    # write()/action_generate_schedule(), jamais via onchange seul).
    #
    # Depuis le retrait du bouton "Générer échéancier" (docs_dev/retrait_bouton_generer_echeancier/)
    # ce chemin couvre aussi la TOUTE PREMIÈRE génération : dès que loan_amount + term +
    # repayment_frequency_id sont renseignés sur un crédit modifiable, la sauvegarde crée et
    # persiste l'échéancier, sans geste manuel. Le mode d'arrondi du reliquat est toujours
    # 'last_installment' (défaut, comme _propagate_avis_to_loan()) - 'distributed' n'est plus
    # exposé en UI mais reste accessible par code via action_generate_schedule(rounding_mode=...).
    _SCHEDULE_TRIGGER_FIELDS = {
        'loan_amount', 'term', 'repayment_frequency_id', 'interest_rate', 'installment_amount',
    }

    # États à partir desquels les champs _LOCKED_DOSSIER_FIELDS ci-dessous ne doivent plus être
    # modifiables manuellement (Lot 1, docs_dev/verrouillage_calcul_credit/) - reprend
    # exactement les états atteignables après avis_ca/avis_cdag établis à l'audit (section 2) :
    # 'cancelled' est volontairement exclu, aucune méthode du module ne l'atteint aujourd'hui
    # (état mort, cf. AUDIT.md section 2) - à ajouter ici le jour où un mécanisme l'atteint
    # réellement. Volontairement une constante séparée de _EDITABLE_SCHEDULE_STATES ci-dessus
    # (décision Micka explicite, AUDIT.md section 2) : portée différente, celle-ci verrouille la
    # saisie manuelle des champs source, _EDITABLE_SCHEDULE_STATES gouverne la régénération de
    # l'échéancier détaillé (ex. toujours permissif en 'approved') - ne pas fusionner les deux.
    _LOCKED_DOSSIER_STATES = ('avis_ca', 'avis_cdag', 'approved', 'active', 'closed', 'defaulted', 'written_off')

    # Champs verrouillés dès qu'un crédit atteint _LOCKED_DOSSIER_STATES - décision Micka,
    # docs_dev/verrouillage_calcul_credit/AUDIT.md, périmètre confirmé au Lot 1.
    _LOCKED_DOSSIER_FIELDS = {'loan_amount', 'term', 'product_id', 'interest_rate', 'installment_amount'}

    # États à partir desquels fee_amount_due (frais de dossier dus) est figé : un
    # changement ultérieur du taux/montant de frais sur le produit ne doit plus faire
    # bouger les frais d'un dossier déjà approuvé (décision Micka, docs_dev/product_fee/
    # AUDIT.md point 5 - même philosophie que _LOCKED_DOSSIER_STATES : montants gelés dès
    # qu'un dossier avance). Volontairement plus restreint que _LOCKED_DOSSIER_STATES :
    # avant 'approved' (draft/enquete/avis_ca/avis_cdag) les frais suivent encore la
    # config produit courante ; seuls les nouveaux dossiers héritent d'un nouveau taux.
    # 'cancelled' exclu (état mort, cf. _LOCKED_DOSSIER_STATES).
    _FEE_FROZEN_STATES = ('approved', 'active', 'closed', 'defaulted', 'written_off')

    def _check_locked_dossier_fields(self, vals):
        """Lève une ValidationError si `vals` touche un champ de _LOCKED_DOSSIER_FIELDS sur un
        crédit déjà dans _LOCKED_DOSSIER_STATES - sauf si l'écriture vient de
        _propagate_avis_to_loan() elle-même (context `propagation_avis_ca_cdag`, posé
        explicitement par cette méthode avant son propre write() interne). Volontairement un
        override de write(), pas un @api.constrains : un constrains valide un état final, il ne
        peut pas à lui seul distinguer une écriture système légitime d'une saisie manuelle sans
        ce même mécanisme de contexte - inutile de dupliquer la logique dans les deux endroits.
        Appelée avant super().write() (donc sur l'état du crédit tel qu'il était juste avant
        cette écriture, pas après)."""
        locked_now = self._LOCKED_DOSSIER_FIELDS & set(vals)
        if not locked_now or self.env.context.get('propagation_avis_ca_cdag'):
            return
        for loan in self:
            if loan.state not in loan._LOCKED_DOSSIER_STATES:
                continue
            avis_label = {'avis_ca': "un avis CA", 'avis_cdag': "un avis CDAG"}.get(loan.state, "un avis CA/CDAG")
            field_labels = ', '.join(loan._fields[f].string for f in sorted(locked_now))
            raise ValidationError(_(
                "Le crédit %(loan_name)s a déjà reçu %(avis)s : %(fields)s ne peuvent plus être "
                "modifiés à ce stade. Contactez le support technique si une correction est "
                "encore nécessaire."
            ) % {'loan_name': loan.name, 'avis': avis_label, 'fields': field_labels})

    # Champs verrouillés définitivement dès que contract_signature_date est renseigné une
    # première fois - décision Micka, docs_dev/date_signature_contrat/. Volontairement
    # DISTINCT de _LOCKED_DOSSIER_FIELDS/_check_locked_dossier_fields() ci-dessus : ce
    # verrouillage-ci ne dépend pas de `state` (il s'applique aussi bien sur un dossier
    # closed/defaulted/written_off que active), et n'admet AUCUNE dérogation (pas de
    # contexte d'échappement comme `propagation_avis_ca_cdag` : une fois signé, même le
    # wizard qui a posé la valeur ne peut plus la réécrire).
    _CONTRACT_SIGNATURE_LOCKED_FIELDS = {'signed_contract', 'signed_contract_filename', 'contract_signature_date'}

    def _check_contract_signature_locked(self, vals):
        """Lève une UserError si `vals` touche signed_contract, signed_contract_filename ou
        contract_signature_date sur un crédit dont contract_signature_date est déjà renseigné
        (valeur AVANT écriture, cette méthode est appelée avant super().write()). Aucune
        dérogation : contrairement à _check_locked_dossier_fields(), pas de contexte
        d'échappement - la seule écriture légitime sur ces champs est la toute première,
        effectuée par microfinance.loan.contract.signature.wizard.action_confirm() tant que
        contract_signature_date est encore vide."""
        if not (self._CONTRACT_SIGNATURE_LOCKED_FIELDS & set(vals)):
            return
        for loan in self:
            if loan.contract_signature_date:
                raise UserError(_(
                    "Le contrat signé et sa date de signature ne peuvent plus être modifiés "
                    "une fois confirmés."
                ))

    def unlink(self):
        # La suppression d'un crédit purge ses pièces jointes (dont le contrat signé,
        # protégé par ir.attachment.unlink) : on lève ici la protection le temps de la
        # suppression du dossier lui-même.
        return super(MicrofinanceLoan, self.with_context(bypass_signed_contract_protection=True)).unlink()

    def write(self, vals):
        self._check_locked_dossier_fields(vals)
        self._check_contract_signature_locked(vals)
        result = super().write(vals)
        if self._AVIS_PROPAGATION_TRIGGER_FIELDS & set(vals):
            for loan in self:
                loan._propagate_avis_to_loan()
        if vals.get('signed_contract'):
            for loan in self:
                loan._post_signed_contract_to_chatter()
        if self._SCHEDULE_TRIGGER_FIELDS & set(vals):
            for loan in self:
                # (Re)génère l'échéancier à chaque sauvegarde tant que le crédit est modifiable -
                # y compris la toute première fois (le bouton "Générer échéancier" a été retiré,
                # cf. docs_dev/retrait_bouton_generer_echeancier/). Toujours le mode d'arrondi
                # 'last_installment' par défaut, comme _propagate_avis_to_loan() : rounding_mode
                # n'est stocké nulle part sur le crédit, et 'distributed' n'a plus d'accès UI.
                # La garde sur les 3 champs essentiels évite un UserError de action_generate_
                # schedule() (périodicité manquante, L~1310) sur une sauvegarde de brouillon
                # incomplet : elle reste alors un no-op jusqu'à ce qu'ils soient renseignés.
                if (loan.state in loan._EDITABLE_SCHEDULE_STATES
                        and loan.repayment_frequency_id and loan.loan_amount and loan.term):
                    loan.action_generate_schedule()
        return result

    def _propagate_avis_to_loan(self):
        """Répercute le dernier avis (CA ou CDAG, selon l'état courant du crédit) sur
        loan_amount/term/installment_amount et régénère l'échéancier détaillé. Appelée uniquement
        depuis write() ci-dessus (jamais directement) dès qu'un des champs
        _AVIS_PROPAGATION_TRIGGER_FIELDS vient d'être écrit.

        Le `write({'loan_amount': ..., 'term': ..., 'installment_amount': ...})` ci-dessous
        rappelle write() (donc cette méthode) récursivement, mais sans risque de boucle : aucun
        des trois champs écrits ici (loan_amount/term/installment_amount) ne fait partie de
        _AVIS_PROPAGATION_TRIGGER_FIELDS, l'appel récursif ne retrouve donc jamais de champ
        déclencheur et s'arrête de lui-même. Même raisonnement pour action_generate_schedule()
        (écrit uniquement installment_ids)."""
        self.ensure_one()
        if self.state not in self._EDITABLE_SCHEDULE_STATES:
            return
        if self.state == 'avis_ca':
            source_amount, source_term, source_installment = (
                self.avis_ca_amount, self.avis_ca_term, self.avis_ca_installment_amount)
        elif self.state == 'avis_cdag':
            source_amount, source_term, source_installment = (
                self.avis_cdag_amount, self.avis_cdag_term, self.avis_cdag_installment_amount)
        else:
            return
        if not source_amount or not source_term:
            return
        if self.loan_amount == source_amount and self.term == source_term:
            return  # déjà synchronisé - évite un write()/régénération d'échéancier inutiles
        # Filet de sécurité : l'avis courant devrait déjà avoir sa propre échéance calculée (cf.
        # action_ca_review/action_cdag_review, qui appellent l'onchange correspondant juste après
        # avoir posé les valeurs par défaut) - recalculée ici au cas où ce ne soit pas le cas
        # (écriture directe hors formulaire/hors bouton, ex. import).
        source_installment = source_installment or self._compute_installment_target(source_amount, source_term)
        # Contexte `propagation_avis_ca_cdag` : signale à _check_locked_dossier_fields() que
        # cette écriture est la répercussion système de l'avis courant (Lot 1, docs_dev/
        # verrouillage_calcul_credit/), pas une saisie manuelle - sans ce flag, ce write() serait
        # bloqué par son propre verrou (loan_amount/term/installment_amount, state déjà
        # avis_ca/avis_cdag à ce stade).
        self.with_context(propagation_avis_ca_cdag=True).write({
            'loan_amount': source_amount,
            'term': source_term,
            'installment_amount': source_installment,
        })
        self.action_generate_schedule()

    @api.onchange('company_id')
    def _onchange_company_id_default_fond(self):
        """Pré-remplit fond_credit_id avec le fonds par défaut configuré pour cette société
        (res.company.microfinance_fond_credit_default_id) - uniquement si le champ n'est pas déjà
        renseigné : simple aide à la saisie, jamais un écrasement d'un choix déjà fait par
        l'utilisateur. Reste librement modifiable ensuite (aucun rapport avec le verrouillage de
        fond_credit_id après décaissement, cf. _check_fond_credit_id_locked_after_disbursement
        ci-dessous, qui s'applique uniquement une fois le crédit décaissé)."""
        if not self.fond_credit_id and self.company_id.microfinance_fond_credit_default_id:
            self.fond_credit_id = self.company_id.microfinance_fond_credit_default_id

    def _actual_duration_months(self):
        """Durée réelle du crédit en mois, à partir du nombre d'échéances et de la
        périodicité choisie. Les min_term/max_term du produit sont exprimés en mois
        quelle que soit la périodicité effectivement choisie sur le crédit (un produit
        multi-périodicité type PRET RURAL peut être remboursé en journalier, hebdomadaire
        ou mensuel) : il faut donc convertir avant de comparer, plutôt que de comparer le
        nombre brut d'échéances aux bornes mensuelles du produit.
        Approximation mois = 30 jours, cohérente avec le niveau de précision attendu pour
        une borne métier (pas un calcul financier au jour près comme les intérêts)."""
        self.ensure_one()
        freq = self.repayment_frequency_id
        if not freq:
            return False
        if freq.period_kind == 'months':
            return self.term * freq.period_value
        return (self.term * freq.period_value) / 30.0

    @api.constrains('loan_amount', 'term', 'product_id', 'repayment_frequency_id')
    def _check_product_limits(self):
        for loan in self:
            product = loan.product_id
            if product and (loan.loan_amount < product.min_amount or loan.loan_amount > product.max_amount):
                raise ValidationError(_('Le montant doit respecter les limites du produit.'))
            if product and loan.repayment_frequency_id:
                duration_months = loan._actual_duration_months()
                if duration_months < product.min_term or duration_months > product.max_term:
                    raise ValidationError(_('La durée doit respecter les limites du produit.'))

    @api.constrains('repayment_frequency_id', 'product_id')
    def _check_repayment_frequency_allowed(self):
        for loan in self:
            product = loan.product_id
            if product.repayment_frequency_mode == 'client_choice' and loan.repayment_frequency_id:
                if loan.repayment_frequency_id not in product.allowed_repayment_frequency_ids:
                    raise ValidationError(_(
                        'La périodicité "%(freq)s" n\'est pas autorisée par le produit "%(product)s".'
                    ) % {'freq': loan.repayment_frequency_id.name, 'product': product.name})

    @api.depends('installment_ids.principal_amount', 'installment_ids.interest_amount', 'installment_ids.penalty_amount',
                 'installment_ids.paid_principal', 'installment_ids.paid_interest', 'installment_ids.paid_penalty',
                 'installment_ids.residual_amount', 'installment_ids.state')
    def _compute_totals(self):
        for loan in self:
            loan.principal_total = sum(loan.installment_ids.mapped('principal_amount'))
            loan.interest_total = sum(loan.installment_ids.mapped('interest_amount'))
            loan.penalty_total = sum(loan.installment_ids.mapped('penalty_amount'))
            loan.paid_total = sum(loan.installment_ids.mapped('paid_principal')) + sum(loan.installment_ids.mapped('paid_interest')) + sum(loan.installment_ids.mapped('paid_penalty'))
            # Before a schedule exists, fall back to the nominal loan amount; once installments
            # exist, a fully repaid loan legitimately sums to 0 and must not fall back to
            # loan_amount (a plain "or" would treat that 0 as falsy and mask it).
            loan.balance_total = sum(loan.installment_ids.mapped('residual_amount')) if loan.installment_ids else loan.loan_amount
            overdue = loan.installment_ids.filtered(lambda l: l.state == 'overdue')
            loan.overdue_amount = sum(overdue.mapped('residual_amount'))
            loan.overdue_installment_count = len(overdue)

    @api.depends('guarantee_ids.recognized_value', 'guarantee_ids.state')
    def _compute_guarantee_total(self):
        for loan in self:
            validated = loan.guarantee_ids.filtered(lambda g: g.state == 'validated')
            loan.guarantee_total = sum(validated.mapped('recognized_value'))

    @api.depends('loan_amount', 'product_id.fee_type', 'product_id.fee_amount', 'product_id.fee_rate')
    def _compute_fee_amount(self):
        # Frais figés dès l'approbation (décision Micka, docs_dev/product_fee/AUDIT.md
        # point 5) : ce compute reste déclenché quand product_id.fee_rate/fee_amount change,
        # mais pour un dossier déjà dans _FEE_FROZEN_STATES on conserve la valeur en base au
        # lieu de la recalculer. Lecture SQL directe de fee_amount_due pour les dossiers
        # figés : on ne veut surtout pas re-déclencher le compute en relisant le champ via
        # l'ORM depuis sa propre méthode de calcul.
        frozen = self.filtered(lambda l: l.state in l._FEE_FROZEN_STATES)
        stored = {}
        if frozen.ids:
            self.env.cr.execute(
                "SELECT id, fee_amount_due FROM microfinance_loan WHERE id IN %s",
                (tuple(frozen.ids),),
            )
            stored = dict(self.env.cr.fetchall())
        for loan in self:
            if loan in frozen:
                loan.fee_amount_due = stored.get(loan.id) or 0.0
                continue
            product = loan.product_id
            if not product:
                loan.fee_amount_due = 0.0
            elif product.fee_type == 'fixed':
                loan.fee_amount_due = product.fee_amount
            else:
                loan.fee_amount_due = loan.loan_amount * product.fee_rate / 100.0

    @api.depends('fee_amount_due', 'fee_paid')
    def _compute_fee_payment_state(self):
        for loan in self:
            if loan.fee_amount_due <= 0:
                loan.fee_payment_state = 'none'
            else:
                loan.fee_payment_state = 'paid' if loan.fee_paid else 'unpaid'

    @api.depends('product_id.repayment_frequency_mode', 'product_id.repayment_frequency_id')
    def _compute_repayment_frequency_id(self):
        # Uniquement pour les produits à périodicité imposée : la valeur est alors recopiée du
        # produit et rendue readonly côté vue. Pour un produit à choix du client, on ne touche
        # jamais ici à une valeur déjà choisie manuellement par l'agent.
        for loan in self:
            if loan.product_id.repayment_frequency_mode == 'fixed':
                loan.repayment_frequency_id = loan.product_id.repayment_frequency_id

    @api.depends('loan_amount', 'fee_amount_due', 'product_id.fee_charged_before_disbursement')
    def _compute_net_disbursed_amount(self):
        for loan in self:
            if loan.product_id and not loan.product_id.fee_charged_before_disbursement:
                loan.net_disbursed_amount = loan.loan_amount - loan.fee_amount_due
            else:
                loan.net_disbursed_amount = loan.loan_amount

    def _get_max_overdue_days(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        overdue = self.installment_ids.filtered(lambda l: l.state == 'overdue')
        max_days = 0
        for line in overdue:
            if line.due_date:
                max_days = max(max_days, (today - line.due_date).days)
        return max_days

    @api.model
    def get_recent_loans(self, company_id, limit=5):
        """5 derniers prêts créés, pour le panneau "Derniers prêts" du tableau de bord. L'ordre
        par défaut du modèle (id desc) est équivalent à un tri par date de création décroissante.
        Extrait en méthode de modèle pour rester testable directement, comme get_par_buckets."""
        return self.search([('company_id', '=', company_id)], limit=limit)

    @api.model
    def get_overdue_monthly_flux(self, company_id, month_keys):
        """Nombre de "nouveaux impayés" par mois (flux, pas le stock cumulé) pour le graphique
        "Évolution des impayés" du tableau de bord, à partir de l'historique persistant
        arrears_onset_date/arrears_cured_date des échéances (cf. installment._sync_arrears_state).

        Un prêt compte un nouvel impayé au mois de la première échéance dont le retard est
        constaté, sauf si le prêt a déjà un "épisode" de retard ouvert à ce moment-là (une ou
        plusieurs échéances encore non soldées, chevauchant dans le temps) — auquel cas
        l'échéance rejoint le même épisode sans être recomptée. Un nouvel épisode n'est compté
        que si l'épisode précédent du prêt est bien clos (toutes ses échéances soldées) avant la
        date de retard de la nouvelle échéance : c'est ce qui distingue un retard continu sur
        plusieurs échéances (compté une fois) d'une régularisation suivie d'une rechute (comptée
        deux fois)."""
        installments = self.env['microfinance.loan.installment'].search([
            ('company_id', '=', company_id),
            ('arrears_onset_date', '!=', False),
        ], order='loan_id, arrears_onset_date')

        by_loan = defaultdict(list)
        for inst in installments:
            by_loan[inst.loan_id.id].append(inst)

        counts = defaultdict(int)
        for insts in by_loan.values():
            has_episode = False
            episode_open = False
            episode_cure_date = None
            for inst in insts:
                onset, cured = inst.arrears_onset_date, inst.arrears_cured_date
                starts_new = not has_episode or (not episode_open and onset > episode_cure_date)
                if starts_new:
                    counts[onset.strftime('%Y-%m')] += 1
                    has_episode = True
                    episode_open = False
                    episode_cure_date = None
                if not cured:
                    # Champ Date Odoo vide => False (jamais None) : "not cured" est la bonne
                    # façon de détecter une échéance encore non soldée ici.
                    episode_open = True
                elif not episode_open:
                    episode_cure_date = max(episode_cure_date, cured) if episode_cure_date else cured

        return {key: counts.get(key, 0) for key in month_keys}

    @api.model
    def get_par_buckets(self, company_id):
        """PAR (portefeuille à risque) par tranche d'ancienneté d'arriéré, pour le
        dashboard. Portée sur les crédits actifs/en défaut de la société (les crédits
        written_off/closed en sont donc déjà exclus). Extrait en méthode de modèle
        (plutôt que gardé dans le contrôleur HTTP) pour rester testable directement."""
        tranches = [('1-30', 1, 30), ('31-60', 31, 60), ('61-90', 61, 90), ('90+', 91, None)]
        # disbursement_date renseigné : un crédit 'active' non encore décaissé (découplage
        # activation / décaissement, docs_dev/guichet_caisse/AUDIT_decaissement.md) n'a pas de
        # portefeuille à risque — ses échéances pré-générées ne représentent aucun impayé réel.
        portfolio_loans = self.search([
            ('company_id', '=', company_id), ('state', 'in', ('active', 'defaulted')),
            ('disbursement_date', '!=', False),
        ])
        outstanding_amount = sum(portfolio_loans.mapped('balance_total'))
        amounts = dict.fromkeys([label for label, _, _ in tranches], 0.0)
        for loan in portfolio_loans:
            max_days = loan._get_max_overdue_days()
            if max_days <= 0:
                continue
            for label, min_days, max_days_bound in tranches:
                if max_days >= min_days and (max_days_bound is None or max_days <= max_days_bound):
                    amounts[label] += loan.balance_total
                    break
        return {
            'labels': ['PAR %s' % label for label, _, _ in tranches],
            'values': [
                (amounts[label] / outstanding_amount * 100.0) if outstanding_amount else 0.0
                for label, _, _ in tranches
            ],
        }

    # ==================================================================
    # Dashboard « Portefeuille par agent de crédit » (Lot 1)
    # Bloc entièrement ADDITIF : get_par_buckets et les panneaux existants du dashboard
    # (get_due_today, top_overdue_loans, monthly_*) ne sont pas touchés.
    # Décisions actées (docs_dev/dashboard_portefeuille_agent/) :
    #  - base encours/PAR = balance_total ;
    #  - portefeuille = state in ('active','defaulted') ET disbursement_date renseigné ;
    #  - dossiers sans officer_id exclus ;
    #  - scope : agent -> soi ; manager/gestionnaire -> agence active ; auditeur -> toutes ses
    #    agences ; contrôle serveur du scope obligatoire (jamais de confiance au paramètre client).
    # ==================================================================

    _AGENT_PORTFOLIO_STATES = ('active', 'defaulted')

    @api.model
    def _get_agent_portfolio_scope(self):
        """(company_ids, officer_id | None) selon le rôle de self.env.user. L'ordre des tests
        fait le « test en négatif » (décision n°11) : manager+auditeur -> traité en auditeur ;
        un pur agent tombe dans le else."""
        user = self.env.user
        mod = 'microfinance_loan_management.'
        if user.has_group(mod + 'group_microfinance_auditor'):
            return user.company_ids.ids, None
        if user.has_group(mod + 'group_microfinance_manager') \
                or user.has_group(mod + 'group_microfinance_gestionnaire'):
            return [self.env.company.id], None
        return [self.env.company.id], user.id

    @api.model
    def get_available_agents(self):
        """Agents sélectionnables par l'utilisateur courant (sélecteur d'en-tête). Un agent ne
        se voit que lui-même. Un manager/auditeur voit les officer_id ayant au moins un dossier
        du portefeuille dans son périmètre ; en multi-société (auditeur) un même agent ressort
        une ligne par agence."""
        company_ids, forced_officer = self._get_agent_portfolio_scope()
        if forced_officer:
            user = self.env.user
            return [{
                'officer_id': user.id, 'officer_name': user.display_name,
                'company_id': self.env.company.id, 'company_name': self.env.company.display_name,
            }]
        groups = self.read_group(
            [
                ('company_id', 'in', company_ids),
                ('state', 'in', self._AGENT_PORTFOLIO_STATES),
                ('disbursement_date', '!=', False),
                ('officer_id', '!=', False),
            ],
            ['officer_id', 'company_id'], ['officer_id', 'company_id'], lazy=False,
        )
        agents = [{
            'officer_id': row['officer_id'][0], 'officer_name': row['officer_id'][1],
            'company_id': row['company_id'][0], 'company_name': row['company_id'][1],
        } for row in groups if row['officer_id'] and row['company_id']]
        agents.sort(key=lambda a: (a['company_name'], a['officer_name']))
        return agents

    @api.model
    def _resolve_agent_request(self, officer_id_filter):
        """Contrôle serveur du scope (décision n°11, non négociable). Retourne
        (company_ids, officer_id_effectif). Lève AccessError si l'utilisateur demande un agent
        hors de son périmètre. `company_ids` provient TOUJOURS du rôle serveur, jamais du client."""
        company_ids, forced_officer = self._get_agent_portfolio_scope()
        if forced_officer:
            if officer_id_filter and officer_id_filter != forced_officer:
                raise AccessError(_("Vous ne pouvez consulter que votre propre portefeuille."))
            return company_ids, forced_officer
        if officer_id_filter:
            allowed = {a['officer_id'] for a in self.get_available_agents()}
            if officer_id_filter not in allowed:
                raise AccessError(_("Cet agent n'appartient pas à votre périmètre."))
        return company_ids, officer_id_filter

    @api.model
    def _agent_portfolio_domain(self, company_ids, officer_id_filter=None):
        domain = [
            ('company_id', 'in', company_ids),
            ('state', 'in', self._AGENT_PORTFOLIO_STATES),
            ('disbursement_date', '!=', False),
            ('officer_id', '!=', False),
        ]
        if officer_id_filter:
            domain.append(('officer_id', '=', officer_id_filter))
        return domain

    @api.model
    def get_agent_portfolio_kpis(self, officer_id_filter=None):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        loans = self.search(self._agent_portfolio_domain(company_ids, officer))
        inst_domain = [
            ('company_id', 'in', company_ids),
            ('loan_id.state', 'in', self._AGENT_PORTFOLIO_STATES),
            ('loan_id.disbursement_date', '!=', False),
            ('officer_id', '!=', False),
        ]
        pay_domain = [
            ('company_id', 'in', company_ids),
            ('state', '=', 'posted'),
            ('loan_id.state', 'in', self._AGENT_PORTFOLIO_STATES),
            ('loan_id.disbursement_date', '!=', False),
            ('officer_id', '!=', False),
        ]
        if officer:
            inst_domain.append(('officer_id', '=', officer))
            pay_domain.append(('officer_id', '=', officer))
        due = self.env['microfinance.loan.installment'].read_group(inst_domain, ['total_amount:sum'], [], lazy=False)
        paid = self.env['microfinance.loan.payment'].read_group(pay_domain, ['amount:sum'], [], lazy=False)
        total_due = (due and due[0].get('total_amount')) or 0.0
        total_paid = (paid and paid[0].get('amount')) or 0.0
        return {
            'nb_clients': len(loans.mapped('partner_id')),
            'encours': sum(loans.mapped('balance_total')),
            'nb_dossiers_actifs': len(loans),
            'nb_dossiers_en_retard': len(loans.filtered(lambda l: l.overdue_amount > 0)),
            'montant_impaye': sum(loans.mapped('overdue_amount')),
            'taux_remboursement': (total_paid / total_due * 100.0) if total_due else 0.0,
        }

    @api.model
    def get_agent_monthly_kpis(self, officer_id_filter=None, month=None):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        month_start = (fields.Date.to_date(month) if month
                       else fields.Date.context_today(self.env.user)).replace(day=1)
        next_month = month_start + relativedelta(months=1)

        disb_domain = [
            ('company_id', 'in', company_ids),
            ('disbursement_date', '>=', month_start), ('disbursement_date', '<', next_month),
            ('officer_id', '!=', False),
        ]
        inst_domain = [
            ('company_id', 'in', company_ids),
            ('due_date', '>=', month_start), ('due_date', '<', next_month),
            ('loan_id.state', 'in', self._AGENT_PORTFOLIO_STATES),
            ('loan_id.disbursement_date', '!=', False),
            ('officer_id', '!=', False),
        ]
        pay_domain = [
            ('company_id', 'in', company_ids),
            ('state', '=', 'posted'),
            ('payment_date', '>=', month_start), ('payment_date', '<', next_month),
            ('officer_id', '!=', False),
        ]
        if officer:
            for dom in (disb_domain, inst_domain, pay_domain):
                dom.append(('officer_id', '=', officer))
        disb = self.read_group(disb_domain, ['loan_amount:sum'], [], lazy=False)
        inst = self.env['microfinance.loan.installment'].read_group(inst_domain, ['total_amount:sum'], [], lazy=False)
        pay = self.env['microfinance.loan.payment'].read_group(pay_domain, ['amount:sum'], [], lazy=False)
        portfolio = self.search(self._agent_portfolio_domain(company_ids, officer))
        return {
            'month': month_start.strftime('%Y-%m'),
            'nb_credits_decaisses': (disb and disb[0].get('__count')) or 0,
            'montant_decaisse': (disb and disb[0].get('loan_amount')) or 0.0,
            'remboursement_attendu': (inst and inst[0].get('total_amount')) or 0.0,
            'remboursement_encaisse': (pay and pay[0].get('amount')) or 0.0,
            'montant_en_retard': sum(portfolio.mapped('overdue_amount')),
        }

    def _par_by_agent_raw(self, company_ids, officer_id_filter=None):
        """{officer_id: {officer_name, total (=Σ balance_total), at_risk [(balance_total, max_days), ...]}}.
        Lit le champ stocké max_days_overdue (un seul rafraîchissement par le cron quotidien),
        pas de re-scan des échéances."""
        loans = self.search(self._agent_portfolio_domain(company_ids, officer_id_filter))
        raw = {}
        for loan in loans:
            entry = raw.setdefault(loan.officer_id.id, {
                'officer_id': loan.officer_id.id,
                'officer_name': loan.officer_id.display_name,
                'total': 0.0, 'at_risk': [],
            })
            entry['total'] += loan.balance_total
            if loan.max_days_overdue > 0:
                entry['at_risk'].append((loan.balance_total, loan.max_days_overdue))
        return raw

    @api.model
    def get_par_buckets_by_agent(self, officer_id_filter=None):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        tranches = [('1-30', 1, 30), ('31-60', 31, 60), ('61-90', 61, 90), ('90+', 91, None)]
        result = []
        for entry in self._par_by_agent_raw(company_ids, officer).values():
            amounts = dict.fromkeys([lbl for lbl, _, _ in tranches], 0.0)
            for balance, days in entry['at_risk']:
                for lbl, lo, hi in tranches:
                    if days >= lo and (hi is None or days <= hi):
                        amounts[lbl] += balance
                        break
            total = entry['total']
            result.append({
                'officer_id': entry['officer_id'],
                'officer_name': entry['officer_name'],
                'labels': ['PAR %s' % lbl for lbl, _, _ in tranches],
                'values': [(amounts[lbl] / total * 100.0) if total else 0.0 for lbl, _, _ in tranches],
            })
        result.sort(key=lambda r: r['officer_name'])
        return result

    @api.model
    def get_cumulative_par_by_agent(self, officer_id_filter=None, thresholds=(30, 60, 90, 120)):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        result = []
        for entry in self._par_by_agent_raw(company_ids, officer).values():
            total = entry['total']
            result.append({
                'officer_id': entry['officer_id'],
                'officer_name': entry['officer_name'],
                'thresholds': list(thresholds),
                'values': [
                    (sum(bal for bal, days in entry['at_risk'] if days >= t) / total * 100.0)
                    if total else 0.0
                    for t in thresholds
                ],
                'outstanding_total': total,
            })
        result.sort(key=lambda r: r['officer_name'])
        return result

    @api.model
    def get_agent_due_dates_panel(self, officer_id_filter=None):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        today = fields.Date.context_today(self.env.user)
        Installment = self.env['microfinance.loan.installment']
        base = [
            ('company_id', 'in', company_ids),
            ('loan_id.state', 'in', self._AGENT_PORTFOLIO_STATES),
            ('loan_id.disbursement_date', '!=', False),
            ('officer_id', '!=', False),
        ]
        pay_domain = [
            ('company_id', 'in', company_ids), ('state', '=', 'posted'),
            ('payment_date', '=', today), ('officer_id', '!=', False),
        ]
        if officer:
            base.append(('officer_id', '=', officer))
            pay_domain.append(('officer_id', '=', officer))

        today_insts = Installment.search(base + [('due_date', '=', today)])
        attendu = sum(today_insts.mapped('total_amount'))
        pay = self.env['microfinance.loan.payment'].read_group(pay_domain, ['amount:sum'], [], lazy=False)
        encaisse = (pay and pay[0].get('amount')) or 0.0

        next_insts = Installment.search(base + [
            ('due_date', '>', today),
            ('due_date', '<=', today + relativedelta(days=7)),
        ])
        return {
            'today': {
                'nb_clients': len(today_insts.mapped('partner_id')),
                'montant_attendu': attendu,
                'montant_encaisse': encaisse,
                'reste_a_recouvrer': attendu - encaisse,
            },
            'next_7_days': {
                'nb_echeances': len(next_insts),
                'montant_a_recouvrer': sum(next_insts.mapped('residual_amount')),
            },
        }

    @api.model
    def get_agent_portfolio_table(self, officer_id_filter=None, search=None, offset=0, limit=20, order=None):
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        domain = self._agent_portfolio_domain(company_ids, officer)
        if search:
            domain = ['|', ('name', 'ilike', search), ('partner_id.name', 'ilike', search)] + domain
        total = self.search_count(domain)
        loans = self.search(domain, offset=offset or 0, limit=limit or 20, order=order or 'name asc')
        rows = [{
            'id': loan.id,
            'name': loan.name,
            'partner_id': loan.partner_id.id,
            'partner_name': loan.partner_id.display_name,
            'officer_name': loan.officer_id.display_name,
            'company_name': loan.company_id.display_name,
            'loan_amount': loan.loan_amount,
            'balance_total': loan.balance_total,
            'overdue_amount': loan.overdue_amount,
            'max_days_overdue': loan.max_days_overdue,
            'disbursement_date': loan.disbursement_date and loan.disbursement_date.isoformat(),
            'state': loan.state,
        } for loan in loans]
        return {'rows': rows, 'total': total, 'offset': offset or 0, 'limit': limit or 20}

    @api.model
    def get_par_history_by_agent(self, officer_id_filter=None, months=12):
        """Série mensuelle du PAR cumulatif lue depuis microfinance.portfolio.snapshot (§1.9).
        `has_data` = False tant que le cron mensuel n'a jamais tourné -> le Lot 2 affiche un
        état vide explicite plutôt qu'un graphe muet. En périmètre multi-agent/multi-agence,
        moyenne pondérée par l'encours figé de chaque snapshot."""
        company_ids, officer = self._resolve_agent_request(officer_id_filter)
        Snapshot = self.env['microfinance.portfolio.snapshot']
        start = (fields.Date.context_today(self.env.user).replace(day=1)
                 - relativedelta(months=(months or 12) - 1))
        domain = [('company_id', 'in', company_ids), ('date', '>=', start)]
        if officer:
            domain.append(('officer_id', '=', officer))
        by_month = {}
        for snap in Snapshot.search(domain, order='date asc'):
            bucket = by_month.setdefault(snap.date.strftime('%Y-%m'),
                                        {'w': 0.0, 30: 0.0, 60: 0.0, 90: 0.0, 120: 0.0})
            weight = snap.outstanding_total or 0.0
            bucket['w'] += weight
            bucket[30] += snap.par30 * weight
            bucket[60] += snap.par60 * weight
            bucket[90] += snap.par90 * weight
            bucket[120] += snap.par120 * weight
        labels = sorted(by_month)

        def _series(threshold):
            return [(by_month[k][threshold] / by_month[k]['w']) if by_month[k]['w'] else 0.0
                    for k in labels]

        return {
            'labels': labels,
            'has_data': bool(labels),
            'par30': _series(30), 'par60': _series(60),
            'par90': _series(90), 'par120': _series(120),
        }

    @api.model
    def cron_snapshot_portfolio_par(self):
        """Fige le PAR cumulatif par (agent, agence) au 1ᵉʳ du mois courant. Upsert : ré-exécuté
        le même mois, met à jour la ligne. À planifier APRÈS le cron quotidien des retards (pour
        que max_days_overdue soit à jour). Tourne en superuser -> voit toutes les agences."""
        Snapshot = self.env['microfinance.portfolio.snapshot']
        capture_date = Snapshot._cron_capture_date()
        for company in self.env['res.company'].search([]):
            loans = self.search([
                ('company_id', '=', company.id),
                ('state', 'in', self._AGENT_PORTFOLIO_STATES),
                ('disbursement_date', '!=', False),
                ('officer_id', '!=', False),
            ])
            by_officer = defaultdict(lambda: {'total': 0.0, 'at_risk': []})
            for loan in loans:
                entry = by_officer[loan.officer_id.id]
                entry['total'] += loan.balance_total
                if loan.max_days_overdue > 0:
                    entry['at_risk'].append((loan.balance_total, loan.max_days_overdue))
            for officer_id, entry in by_officer.items():
                total = entry['total']
                vals = {
                    'date': capture_date, 'officer_id': officer_id, 'company_id': company.id,
                    'outstanding_total': total,
                }
                for threshold, key in ((30, 'par30'), (60, 'par60'), (90, 'par90'), (120, 'par120')):
                    at_risk = sum(bal for bal, days in entry['at_risk'] if days >= threshold)
                    vals[key] = (at_risk / total * 100.0) if total else 0.0
                existing = Snapshot.search([
                    ('date', '=', capture_date), ('officer_id', '=', officer_id),
                    ('company_id', '=', company.id),
                ], limit=1)
                if existing:
                    existing.write(vals)
                else:
                    Snapshot.create(vals)
        return True

    @api.depends('state', 'disbursement_date', 'balance_total', 'company_id',
                 'installment_ids.due_date', 'installment_ids.state')
    def _compute_provision(self):
        Rule = self.env['microfinance.provision.rule']
        for loan in self:
            # Pas de provision sur un crédit non encore décaissé (état 'active' transitoire du
            # découplage activation / décaissement, AUDIT_decaissement.md) : aucun risque de
            # crédit tant que les fonds ne sont pas sortis.
            if loan.state not in ('active', 'defaulted') or not loan.disbursement_date:
                loan.provision_amount = 0.0
                continue
            max_days = loan._get_max_overdue_days()
            rule = Rule.search([
                ('company_id', '=', loan.company_id.id),
                ('min_days', '<=', max_days),
                '|', ('max_days', '=', 0), ('max_days', '>=', max_days),
            ], order='min_days desc', limit=1)
            rate = rule.provision_rate if rule else 0.0
            loan.provision_amount = min(loan.balance_total * rate / 100.0, loan.balance_total)

    def _compute_counts(self):
        for loan in self:
            loan.installment_count = len(loan.installment_ids)
            loan.payment_count = len(loan.payment_ids)
            loan.visit_count = len(loan.visit_ids)
            loan.move_count = len(loan.move_ids)
            loan.scoring_line_count = len(loan.scoring_line_ids)
            loan.application_count = len(loan.application_ids)

    def _get_scoring_profile(self):
        self.ensure_one()
        if self.scoring_profile_id and self.scoring_profile_id.active:
            return self.scoring_profile_id
        domain = [('company_id', '=', self.company_id.id), ('active', '=', True)]
        product_profile = self.env['microfinance.scoring.profile'].search(domain + [('product_id', '=', self.product_id.id)], limit=1)
        if product_profile:
            return product_profile
        return self.env['microfinance.scoring.profile'].search(domain + [('product_id', '=', False)], limit=1)

    def _get_external_scoring_metrics(self):
        self.ensure_one()
        return {}

    def _get_scoring_metrics(self):
        self.ensure_one()
        Loan = self.env['microfinance.loan']
        Payment = self.env['microfinance.loan.payment']
        today = fields.Date.context_today(self)
        loan_domain = [('company_id', '=', self.company_id.id), ('partner_id', '=', self.partner_id.id)]
        loans = Loan.search(loan_domain)
        posted_payments = Payment.search([
            ('company_id', '=', self.company_id.id),
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'posted'),
        ])
        installments = loans.mapped('installment_ids')
        overdue_installments = installments.filtered(lambda line: line.state == 'overdue')
        overdue_days = []
        for line in overdue_installments:
            if line.due_date:
                overdue_days.append(max((today - line.due_date).days, 0))
        total_due = sum(installments.mapped('total_amount'))
        total_paid = sum(posted_payments.mapped('amount'))
        partner_create_date = self.partner_id.create_date.date() if self.partner_id.create_date else today
        customer_age_months = max((today.year - partner_create_date.year) * 12 + today.month - partner_create_date.month, 0)
        metrics = {
            'baseline': 1.0,
            'total_loans': len(loans),
            'active_loans': len(loans.filtered(lambda loan: loan.state == 'active')),
            'closed_loans': len(loans.filtered(lambda loan: loan.state == 'closed')),
            'defaulted_loans': len(loans.filtered(lambda loan: loan.state == 'defaulted')),
            'overdue_installments': len(overdue_installments),
            'max_days_overdue': max(overdue_days) if overdue_days else 0.0,
            'average_days_overdue': sum(overdue_days) / len(overdue_days) if overdue_days else 0.0,
            'repayment_rate': total_due and (total_paid / total_due * 100.0) or 0.0,
            'total_borrowed_amount': sum(loans.mapped('loan_amount')),
            'total_paid_amount': total_paid,
            'partial_payment_count': len(installments.filtered(lambda line: line.state == 'partial')),
            'customer_age_months': customer_age_months,
            # Metrics scoped to this loan only (as opposed to the metrics above, aggregated over
            # every loan of the partner) — these reproduce the weights that used to be hardcoded
            # in the retired _compute_risk_score().
            'loan_overdue_installment_count': self.overdue_installment_count,
            'loan_max_days_overdue': self._get_max_overdue_days(),
            'loan_overdue_amount_ratio': self.loan_amount and (self.overdue_amount / self.loan_amount * 100.0) or 0.0,
            'loan_partial_payment_count': len(self.installment_ids.filtered(lambda line: line.state == 'partial')),
        }
        metrics.update(self._get_external_scoring_metrics())
        return metrics

    def _get_scoring_decision(self, profile, score):
        self.ensure_one()
        if score >= profile.approve_threshold:
            return 'recommended'
        if score >= profile.manual_review_threshold:
            return 'manual_review'
        return 'reject_recommended'

    def _get_scoring_risk_level(self, profile, score):
        self.ensure_one()
        span = max(profile.max_score - profile.min_score, 1.0)
        ratio = (score - profile.min_score) / span
        if ratio >= 0.75:
            return 'low'
        if ratio >= 0.5:
            return 'medium'
        if score >= profile.reject_threshold:
            return 'high'
        return 'critical'

    def action_calculate_scoring(self, silent=False):
        for loan in self:
            if loan.state == 'written_off':
                # Written-off loans are no longer part of the active risk/PAR calculations.
                loan.write({
                    'internal_score': 0.0,
                    'risk_level': 'critical',
                    'scoring_decision': 'reject_recommended',
                    'scoring_line_ids': [(5, 0, 0)],
                })
                continue
            profile = loan._get_scoring_profile()
            if not profile:
                if silent:
                    continue
                raise UserError(_('Configurez un profil de scoring crédit pour cette société ou ce produit.'))
            metrics = loan._get_scoring_metrics()
            score = 0.0
            line_values = []
            for rule in profile.rule_ids.filtered(lambda item: item.active).sorted(lambda item: (item.sequence, item.id)):
                metric_value = metrics.get(rule.metric, 0.0)
                if rule._matches(metric_value):
                    points = rule._get_points(metric_value)
                    score += points
                    line_values.append((0, 0, {
                        'rule_id': rule.id,
                        'metric_value': metric_value,
                        'points_applied': points,
                        'note': rule.description or rule.name,
                    }))
            score = min(max(score, profile.min_score), profile.max_score)
            loan.write({
                'scoring_profile_id': profile.id,
                'internal_score': score,
                'risk_level': loan._get_scoring_risk_level(profile, score),
                'scoring_decision': loan._get_scoring_decision(profile, score),
                'scoring_line_ids': [(5, 0, 0)] + line_values,
            })
        return True

    def _check_eligibility(self):
        for loan in self:
            product = loan.product_id
            today = fields.Date.context_today(loan)
            member_since = loan.partner_id.create_date.date() if loan.partner_id.create_date else today
            membership_days = (today - member_since).days
            if product.min_membership_days and membership_days < product.min_membership_days:
                missing_days = product.min_membership_days - membership_days
                raise UserError(_(
                    'Ancienneté client insuffisante pour ce produit : il manque %(missing)s jour(s) '
                    '(ancienneté requise : %(required)s jours, ancienneté actuelle : %(current)s jours).'
                ) % {'missing': missing_days, 'required': product.min_membership_days, 'current': membership_days})

            other_active_loans = self.search([
                ('company_id', '=', loan.company_id.id),
                ('partner_id', '=', loan.partner_id.id),
                ('id', '!=', loan.id),
                ('state', '=', 'active'),
            ])
            if other_active_loans:
                if not product.allow_second_loan:
                    raise UserError(_('Ce client a déjà un crédit actif. Ce produit n\'autorise pas de second crédit en parallèle.'))
                if product.block_second_if_arrears and any(other.overdue_installment_count > 0 for other in other_active_loans):
                    raise UserError(_('Ce client a déjà un crédit actif en arriérés. Un second crédit ne peut pas être soumis.'))

            if loan.co_borrower_id:
                co_borrower_active_loans = self.search([
                    ('company_id', '=', loan.company_id.id),
                    ('partner_id', '=', loan.co_borrower_id.id),
                    ('id', '!=', loan.id),
                    ('state', '=', 'active'),
                ])
                if co_borrower_active_loans:
                    raise UserError(_('Le co-emprunteur a déjà un crédit actif en cours.'))

            if product.guarantee_required and not loan.guarantee_ids.filtered(lambda g: g.state == 'validated'):
                raise UserError(_('Ce produit exige une garantie validée avant soumission.'))
            if product.min_guarantee_ratio > 0:
                required_guarantee = loan.loan_amount * product.min_guarantee_ratio / 100.0
                if loan.guarantee_total < required_guarantee:
                    missing = required_guarantee - loan.guarantee_total
                    raise UserError(_(
                        'Garanties insuffisantes : il manque %(missing).2f pour atteindre le ratio minimum requis '
                        '(%(ratio)s%% du montant du crédit, soit %(required).2f).'
                    ) % {'missing': missing, 'ratio': product.min_guarantee_ratio, 'required': required_guarantee})

    def action_start_enquete(self):
        # Filet de sécurité seulement : si installment_amount a déjà été calculé via l'onchange
        # normal du formulaire, cette boucle ne fait rien de plus (condition `not
        # loan.installment_amount` déjà fausse). Utile pour les crédits créés hors formulaire
        # standard (import, API), où l'onchange n'a jamais eu l'occasion de s'exécuter.
        for loan in self:
            if not loan.installment_amount and loan.loan_amount and loan.term and loan.repayment_frequency_id:
                loan._onchange_loan_amount_recompute_installment()
        self._check_eligibility()
        self.action_calculate_scoring(silent=True)
        self.write({'state': 'enquete'})

    def action_ca_review(self):
        # Valeurs par défaut posées ici (entrée en état 'avis_ca'), pas à la création du crédit :
        # loan_amount/term peuvent encore changer tant que le crédit n'a pas atteint cet état.
        # `if not loan.avis_ca_amount` : ne réécrase jamais une valeur déjà saisie - filet de
        # sécurité seulement (appel direct hors bouton, ex. tests/API), sans effet si l'onchange
        # normal du formulaire a déjà tout posé avant l'appel de ce bouton.
        for loan in self:
            if not loan.avis_ca_amount:
                loan.avis_ca_amount = loan.loan_amount
            if not loan.avis_ca_term:
                loan.avis_ca_term = loan.term
            loan._onchange_avis_ca_recompute_installment()
        self.write({'state': 'avis_ca', 'manager_id': self.env.user.id})

    def action_cdag_review(self):
        # Filet de sécurité seulement : en usage normal, avis_cdag_amount/term sont déjà remplis
        # par la cascade CA -> CDAG (cf. _onchange_avis_ca_recompute_installment) au moment où le
        # CA a été saisi. Repli sur avis_ca_amount/term puis loan_amount/term si, pour une raison
        # quelconque (import, crédit créé hors formulaire), aucun avis CA n'a encore été posé.
        for loan in self:
            if not loan.avis_cdag_amount:
                loan.avis_cdag_amount = loan.avis_ca_amount or loan.loan_amount
            if not loan.avis_cdag_term:
                loan.avis_cdag_term = loan.avis_ca_term or loan.term
            loan._onchange_avis_cdag_recompute_installment()
        self.write({'state': 'avis_cdag', 'finance_user_id': self.env.user.id})

    def action_approve(self):
        for loan in self:
            loan._check_committee_octroi_accepted()
        self.write({'state': 'approved', 'approval_date': fields.Date.context_today(self)})
        # Engagement comptable des frais de dossier (flux Option A, docs_dev/
        # frais_dossier_creance_pcec/) : débit "frais à recevoir" (208005) / crédit commission
        # (717003), au moment où fee_amount_due vient d'être figé (state 'approved' est dans
        # _FEE_FROZEN_STATES). Créé UNIQUEMENT pour les produits "frais exigés avant
        # décaissement" - en mode "frais nettés du décaissement" les frais restent comptabilisés
        # dans l'écriture de décaissement (crédit 717003), pas d'engagement (décision Micka,
        # AUDIT.md Q5 / issue 1). _prepare_disbursement_move n'est pas touché.
        for loan in self:
            if loan._is_fee_engagement_applicable():
                move = self.env['account.move'].with_context(
                    default_loan_id=False, default_loan_line_id=False,
                ).create(loan._prepare_fee_receivable_move())
                move.action_post()
                loan.fee_receivable_move_id = move.id
                loan.message_post(body=_(
                    'Engagement frais de dossier (%.2f). Écriture : %s') % (
                    loan.fee_amount_due, move.name))

    def _is_fee_engagement_applicable(self):
        """Vrai si ce dossier doit porter une écriture d'engagement de frais à l'approbation :
        frais dus non nuls, produit en mode "frais exigés avant décaissement", engagement pas
        déjà créé (garde de ré-entrance : une réapprobation ne doit pas doubler l'écriture), ET
        produit configuré pour le flux Option A (compte de créance + journal d'engagement +
        compte commission). Si le produit n'est PAS configuré, on ne bloque pas l'approbation :
        pas d'engagement, et l'encaissement retombera sur le repli historique (crédit 717003) -
        cf. _prepare_fee_settlement_move(). Le rattrapage reste possible plus tard via
        action_charge_fee() une fois le produit paramétré."""
        self.ensure_one()
        product = self.product_id
        return bool(
            self.fee_amount_due > 0
            and product.fee_charged_before_disbursement
            and not self.fee_receivable_move_id
            and product.fee_engagement_journal_id
            and product.account_fee_receivable_id
            and product.account_commission_credit_id
        )

    def _check_committee_octroi_accepted(self):
        """Bloque l'approbation tant que le Comité d'Octroi (Section VIII, docs_dev/
        blocage_approbation_comite_octroi/) n'a pas rendu une décision effectivement acceptée.
        Un seul dossier d'instruction est considéré (application_ids[:1], même choix que
        action_view_applications() - application_ids reste structurellement un One2many, aucun
        cas réel à plusieurs dossiers observé à l'audit, mais non garanti par contrainte)."""
        self.ensure_one()
        application = self.application_ids[:1]
        if not application:
            raise UserError(_(
                "Impossible d'approuver le crédit %(loan)s : aucun dossier d'instruction "
                "n'existe pour ce crédit, le comité d'octroi n'a donc rendu aucune décision. "
                "Contactez le support technique si cette décision doit être révisée."
            ) % {'loan': self.name})
        first = application.first_committee_review_id
        if not first or not first.decision:
            detail = _("aucune décision du comité d'octroi n'a encore été enregistrée sur le dossier d'instruction")
        elif first.decision == 'accepted':
            return
        elif first.decision == 'postponed':
            detail = _("le comité d'octroi a reporté sa décision")
        else:  # 'refused'
            second = application.second_committee_review_id
            if second and second.decision == 'accepted':
                return
            detail = _("le comité d'octroi a refusé ce dossier")
        raise UserError(_(
            "Impossible d'approuver le crédit %(loan)s : %(detail)s. Contactez le support "
            "technique si cette décision doit être révisée."
        ) % {'loan': self.name, 'detail': detail})

    def action_mark_default(self):
        self.write({'state': 'defaulted'})

    def action_close(self):
        for loan in self:
            if loan.balance_total > 0.01:
                raise UserError(_('Impossible de clôturer : solde restant à payer.'))
            loan.write({'state': 'closed', 'closed_date': fields.Date.context_today(loan)})
            guarantees_to_release = loan.guarantee_ids.filtered(lambda g: g.state != 'released')
            if guarantees_to_release:
                guarantees_to_release.write({'state': 'released'})
                loan.message_post(body=_('Garanties libérées suite à la clôture du crédit : %s') % (
                    ', '.join(guarantees_to_release.mapped('description'))
                ))

    def action_recompute_risk(self):
        self.action_calculate_scoring(silent=True)
        return True

    def _period_delta(self):
        """Each repayment frequency is either an exact number of calendar months (clean fraction
        of a year: the annual rate is prorated as months/12) or, when it doesn't evenly divide
        into months (daily/weekly/biweekly/four_weekly), a fixed number of days prorated as
        days/365 — the same day-based method already used for the grace-period interest bucket."""
        self.ensure_one()
        freq = self.repayment_frequency_id
        if not freq:
            raise UserError(_('Choisissez une périodicité de remboursement avant de générer l\'échéancier.'))
        return relativedelta(months=freq.period_value) if freq.period_kind == 'months' else relativedelta(days=freq.period_value)

    def _period_interest_factor(self):
        """Fraction of the annual interest rate to apply for one repayment period.
        Uses freq.periods_per_year (fixed conventional value, aligned with LPF) rather than
        a calendar-days-based ratio: e.g. weekly = 1/52, not 7/365. See decision note dated
        2026-08-18 in ecarts_lpf.md."""
        self.ensure_one()
        freq = self.repayment_frequency_id
        if not freq:
            raise UserError(_('Choisissez une périodicité de remboursement avant de générer l\'échéancier.'))
        return 1.0 / freq.periods_per_year

    def _compute_installment_target(self, loan_amount=None, term=None):
        """Cible d'échéance interest-first (arrondie) pour `loan_amount`/`term` (par défaut
        self.loan_amount/self.term) au taux/produit/périodicité actuels - même formule que
        action_generate_schedule. `loan_amount`/`term` paramétrables (Lot 1 du chantier Avis
        CA/CDAG) pour être réutilisable telle quelle sur les champs avis_ca_amount/avis_ca_term
        et avis_cdag_amount/avis_cdag_term ci-dessous, qui vivent sur ce même enregistrement
        (même produit/taux/périodicité que loan_amount/term - pas de généralisation supplémentaire
        nécessaire). Formule inchangée par rapport à avant ce paramétrage, comportement identique
        à l'identique quand appelée sans argument.

        Factorisé hors de l'onchange aller ci-dessous pour servir aussi de référence de cohérence
        à la garde anti-boucle des onchange retour : ces derniers comparent le champ "échéance"
        correspondant à ce que CETTE méthode produirait pour le "durée" actuelle, afin de
        distinguer une échéance recalculée automatiquement (aucune action requise) d'une échéance
        réellement modifiée à la main par l'utilisateur (cf. les onchange ci-dessous et
        docs_dev/regression_nb_echeances/ pour l'historique du bug que cette garde corrige)."""
        self.ensure_one()
        loan_amount = self.loan_amount if loan_amount is None else loan_amount
        term = self.term if term is None else term
        interest_factor = self._period_interest_factor()
        total_interest = (
            loan_amount * (self.interest_rate / 100.0)
            * interest_factor * term
        )
        target = (loan_amount + total_interest) / term
        rounding = self.product_id.installment_rounding_unit or 0
        if rounding and term > 1:
            # term == 1 : pas de tranche de reliquat pour absorber un dépassement d'arrondi
            # (ceiling peut dépasser le total dû) - l'échéance unique reste le montant exact,
            # cohérent avec _compute_installment_targets/_build_installment_commands qui, pour
            # une échéance unique, ne passe jamais par une cible arrondie (cf. leurs commentaires).
            target = self._round_installment_target(target, rounding, self.product_id.installment_rounding_mode)
        return target

    def _compute_term_from_installment_amount(self, installment_amount, loan_amount=None):
        """Sens inverse de _compute_installment_target ci-dessus : nombre d'échéances qui,
        combiné à `loan_amount` (par défaut self.loan_amount) et au taux/périodicité actuels,
        produirait `installment_amount` comme cible interest-first non arrondie. Factorisée hors
        de _onchange_installment_amount_recompute_terms (reprend sa formule à l'identique, aucun
        changement de calcul) pour être réutilisable par le bloc Avis CA/CDAG ci-dessous sans
        dupliquer la formule. Retourne None si `installment_amount` est trop faible pour couvrir
        même l'intérêt d'une période (dénominateur <= 0) - à l'appelant de décider quoi faire
        dans ce cas (ne rien changer, comme avant ce refactor)."""
        self.ensure_one()
        loan_amount = self.loan_amount if loan_amount is None else loan_amount
        interest_factor = self._period_interest_factor()
        rate_component = loan_amount * (self.interest_rate / 100.0) * interest_factor
        denominator = installment_amount - rate_component
        if denominator <= 0:
            return None
        computed_terms = loan_amount / denominator
        return max(1, round(computed_terms))

    @api.onchange('loan_amount', 'term', 'repayment_frequency_id', 'interest_rate')
    def _onchange_loan_amount_recompute_installment(self):
        # Aperçu avant génération de l'échéancier détaillé (action_generate_schedule) : même
        # formule que la cible interest-first calculée là-bas (total_dû / nombre d'échéances),
        # factorisée dans _compute_installment_target ci-dessus. Rafraîchit aussi installment_ids
        # en direct (même valeur de `term` que celle utilisée pour installment_amount ci-dessous,
        # pas de risque de désynchronisation) plutôt que de dépendre d'un onchange séparé
        # déclenché par les mêmes champs. Sans effet une fois le crédit actif (cf.
        # _EDITABLE_SCHEDULE_STATES).
        #
        # Garde anti-boucle (régression corrigée ici, cf. docs_dev/regression_nb_echeances/) :
        # n'écrire installment_amount que si la cible a réellement changé. Sans cette garde,
        # cet onchange réécrirait installment_amount même quand la valeur est déjà correcte
        # (ex. rafraîchissement d'un champ sans changement réel de valeur), ce qui redéclenche
        # inutilement _onchange_installment_amount_recompute_terms ci-dessous dans le même cycle.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if not loan.loan_amount or not loan.term or not loan.repayment_frequency_id:
                continue
            target = loan._compute_installment_target()
            if not (loan.installment_amount and abs(loan.installment_amount - target) < 0.01):
                loan.installment_amount = target
            # installment_ids ne porte aucun onchange propre (vérifié - seuls loan_amount, term,
            # repayment_frequency_id, interest_rate et installment_amount en ont un sur ce modèle) :
            # le reconstruire inconditionnellement ici ne peut donc pas retrigger la boucle, et
            # reste nécessaire même quand la garde ci-dessus saute l'écriture d'installment_amount
            # (term a pu changer sans que la cible arrondie change, cas rare mais possible).
            loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands()

    @api.onchange('installment_amount')
    def _onchange_installment_amount_recompute_terms(self):
        # Sens inverse du calcul ci-dessus : un aller-retour ne redonne pas nécessairement le
        # montant de départ exact du fait des arrondis des deux côtés (installment_rounding_unit
        # ici, entier le plus proche sur term) - comportement normal, pas un bug (cf. help du champ
        # installment_amount). Rafraîchit installment_ids ici même (avec le `term` fraîchement
        # recalculé juste au-dessus), pour la même raison que dans l'onchange aller : ne pas
        # dépendre de l'ordre d'exécution d'un onchange séparé déclenché sur `term`.
        #
        # Garde anti-boucle (corrige la régression Lot 1 où saisir `term` le faisait retomber à
        # une autre valeur dans le même cycle onchange, cf. docs_dev/regression_nb_echeances/
        # AUDIT.md) : avant de recalculer `term`, on vérifie si installment_amount correspond
        # déjà exactement à la cible que produirait _compute_installment_target() pour le `term`
        # actuel. Si oui, ce changement d'installment_amount vient du recalcul automatique de
        # l'onchange aller ci-dessus (pas d'une saisie manuelle de l'utilisateur dans CE champ) :
        # il ne faut alors surtout pas recalculer `term` en retour, sous peine d'écraser la valeur
        # que l'utilisateur vient de saisir. On ne recalcule `term` que quand installment_amount
        # diverge réellement de cette cible - c'est-à-dire quand l'utilisateur a modifié
        # installment_amount lui-même à la main.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if not loan.loan_amount or not loan.installment_amount or not loan.repayment_frequency_id:
                continue
            if loan.term:
                current_target = loan._compute_installment_target()
                if abs(loan.installment_amount - current_target) < 0.01:
                    continue
            new_term = loan._compute_term_from_installment_amount(loan.installment_amount)
            if new_term is None:
                continue  # échéance trop faible pour couvrir même l'intérêt d'une période
            if loan.term and loan.term == new_term:
                continue
            loan.term = new_term
            loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands()

    @api.onchange('avis_ca_term', 'avis_ca_amount')
    def _onchange_avis_ca_recompute_installment(self):
        # Même mécanisme que _onchange_loan_amount_recompute_installment ci-dessus, appliqué au
        # bloc Avis CA plutôt qu'à loan_amount/term (Lot 1 du chantier Avis CA/CDAG - réutilise
        # _compute_installment_target à l'identique, aucune nouvelle formule de calcul).
        #
        # Cascade vers le bloc Avis CDAG tant que celui-ci n'a pas été modifié explicitement par
        # le CDAG (avis_cdag_manually_set, cf. son help) : la cascade est volontairement
        # INCONDITIONNELLE, PAS seulement à l'intérieur du `if` d'écriture d'avis_ca_installment_
        # amount juste au-dessus. Si elle en dépendait, un aller-retour où avis_ca_installment_
        # amount se trouve déjà auto-cohérent avec le nouveau avis_ca_term/avis_ca_amount (ex.
        # juste après un passage par l'onchange inverse ci-dessous) sauterait la cascade alors
        # même que avis_ca_term/avis_ca_amount ont bien changé et doivent être répercutés.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if not loan.avis_ca_amount or not loan.avis_ca_term:
                continue
            target = loan._compute_installment_target(loan.avis_ca_amount, loan.avis_ca_term)
            if not (loan.avis_ca_installment_amount and abs(loan.avis_ca_installment_amount - target) < 0.01):
                loan.avis_ca_installment_amount = target
            if not loan.avis_cdag_manually_set:
                loan.avis_cdag_amount = loan.avis_ca_amount
                loan.avis_cdag_term = loan.avis_ca_term
                loan.avis_cdag_installment_amount = target

    @api.onchange('avis_ca_installment_amount')
    def _onchange_avis_ca_installment_recompute_term(self):
        # Sens inverse du calcul ci-dessus, même garde anti-boucle que
        # _onchange_installment_amount_recompute_terms (comparaison à la cible que produirait
        # _compute_installment_target pour le avis_ca_term actuel, pas à l'ancienne valeur du
        # champ - cf. son commentaire pour le raisonnement complet). Ne cascade pas directement
        # vers le CDAG ici : quand avis_ca_term change juste en dessous, Odoo redéclenche
        # automatiquement _onchange_avis_ca_recompute_installment dans le même cycle onchange
        # (avis_ca_term fait partie de ses champs déclencheurs), qui se charge alors de la
        # cascade - évite de dupliquer cette logique à deux endroits.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if not loan.avis_ca_installment_amount or not loan.avis_ca_amount:
                continue
            if loan.avis_ca_term:
                current_target = loan._compute_installment_target(loan.avis_ca_amount, loan.avis_ca_term)
                if abs(loan.avis_ca_installment_amount - current_target) < 0.01:
                    continue
            new_term = loan._compute_term_from_installment_amount(loan.avis_ca_installment_amount, loan.avis_ca_amount)
            if new_term is None:
                continue
            if loan.avis_ca_term and loan.avis_ca_term == new_term:
                continue
            loan.avis_ca_term = new_term

    @api.onchange('avis_cdag_term', 'avis_cdag_amount')
    def _onchange_avis_cdag_recompute_installment(self):
        # Symétrique du bloc CA ci-dessus, MAIS sans cascade retour vers le CA (le flux ne va
        # que CA -> CDAG, jamais l'inverse - décision actée du chantier).
        #
        # Détection d'une saisie manuelle réelle du CDAG (par opposition à l'écriture
        # programmatique de la cascade CA -> CDAG ci-dessus, qui pose toujours avis_cdag_amount/
        # avis_cdag_term à des valeurs IDENTIQUES à avis_ca_amount/avis_ca_term) : dès que ces
        # deux champs divergent du bloc CA, c'est nécessairement que l'utilisateur vient de les
        # modifier lui-même dans le formulaire (la cascade ne produit jamais cette divergence) -
        # on fige alors définitivement la cascade automatique via avis_cdag_manually_set (jamais
        # remis à False ensuite : une fois le CDAG intervenu, il reste seul maître de son propre
        # bloc). Même vérification dupliquée dans l'onchange inverse ci-dessous (au lieu de
        # compter sur le rebond de avis_cdag_term qui retriggerait cette méthode) : si
        # l'utilisateur modifie avis_cdag_installment_amount et que le nouveau avis_cdag_term
        # recalculé coïncide avec l'ancien, rien ne change de valeur et cette méthode ne serait
        # jamais redéclenchée dans le même cycle - la garde serait alors manquée sans ce doublon.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if (loan.avis_cdag_amount, loan.avis_cdag_term) != (loan.avis_ca_amount, loan.avis_ca_term):
                loan.avis_cdag_manually_set = True
            if not loan.avis_cdag_amount or not loan.avis_cdag_term:
                continue
            target = loan._compute_installment_target(loan.avis_cdag_amount, loan.avis_cdag_term)
            if not (loan.avis_cdag_installment_amount and abs(loan.avis_cdag_installment_amount - target) < 0.01):
                loan.avis_cdag_installment_amount = target

    @api.onchange('avis_cdag_installment_amount')
    def _onchange_avis_cdag_installment_recompute_term(self):
        # Sens inverse du calcul CDAG ci-dessus, même garde anti-boucle. La détection de saisie
        # manuelle (avis_cdag_manually_set) est dupliquée ici pour la même raison que documentée
        # dans _onchange_avis_cdag_recompute_installment ci-dessus (cf. son commentaire) : ne pas
        # dépendre du rebond de avis_cdag_term, qui peut ne pas se produire si le nouveau terme
        # recalculé coïncide avec l'ancien.
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                continue
            if (loan.avis_cdag_amount, loan.avis_cdag_term) != (loan.avis_ca_amount, loan.avis_ca_term):
                loan.avis_cdag_manually_set = True
            if not loan.avis_cdag_installment_amount or not loan.avis_cdag_amount:
                continue
            if loan.avis_cdag_term:
                current_target = loan._compute_installment_target(loan.avis_cdag_amount, loan.avis_cdag_term)
                if abs(loan.avis_cdag_installment_amount - current_target) < 0.01:
                    continue
            new_term = loan._compute_term_from_installment_amount(loan.avis_cdag_installment_amount, loan.avis_cdag_amount)
            if new_term is None:
                continue
            if loan.avis_cdag_term and loan.avis_cdag_term == new_term:
                continue
            loan.avis_cdag_term = new_term

    def _round_installment_target(self, value, unit, mode):
        """Arrondit une cible d'échéance au multiple de `unit` selon `mode` (valeur du champ
        produit installment_rounding_mode - à ne pas confondre avec le paramètre `rounding_mode`
        de _compute_installment_targets ci-dessous, qui porte sur la répartition du reliquat
        entre tranches, un sujet indépendant).

        'ceiling' (défaut, comportement LPF de référence - Lot 1, validé sur plusieurs
        échéanciers réels 1.XLS/IS_000289) : arrondi SUPÉRIEUR au multiple de `unit`. Réduit
        mécaniquement la dernière tranche (le reliquat), donc le risque de queue de crédit.
        'nearest' (ancien comportement par défaut, conservé pour comparaison/cas particulier
        uniquement) : arrondi au multiple le plus proche."""
        if not unit:
            return value
        if mode == 'ceiling':
            return math.ceil(value / unit) * unit
        return round(value / unit) * unit

    def _compute_installment_targets(self, total_due, rounding_unit, rounding_mode):
        """Retourne la liste des montants cibles pour les tranches 1..term-1 (la tranche
        `term`, la toute dernière, n'utilise jamais cette liste : elle absorbe toujours le
        reliquat exact restant, cf. _build_installment_commands - c'est ce qui garantit que la
        somme totale égale exactement total_due, quel que soit le mode choisi ici).

        `rounding_mode` ici concerne uniquement la RÉPARTITION du reliquat entre tranches (choix
        du wizard de génération), pas la direction d'arrondi de chaque cible (ce second réglage,
        installment_rounding_mode sur le produit, est appliqué via _round_installment_target
        ci-dessus - les deux notions de "mode" sont indépendantes, ne pas les confondre) :

        - rounding_mode == 'last_installment' (Absorption sur la dernière tranche,
          comportement historique) : toutes les tranches visent le même montant, arrondi selon
          installment_rounding_mode du produit (ceiling par défaut - Lot 1 ; nearest en option).
          Conforme au cas de référence IS/01913 (mensuel) et IS/000289 (hebdo, papier) déjà
          couverts par test_interest_first_schedule.py.
        - rounding_mode == 'distributed' (Répartition sur les dernières tranches) : la
          plupart des tranches visent le montant arrondi PAR DÉFAUT (floor, jamais nearest ni
          ceiling, pour ne jamais dépasser le total dû avant lissage - logique propre à ce mode,
          non affectée par installment_rounding_mode), et le reliquat est réparti en incréments
          de rounding_unit sur les dernières tranches de la liste (les plus proches de la fin),
          au lieu d'être concentré sur la tranche `term` seule."""
        self.ensure_one()
        n = self.term
        raw_target = total_due / n
        if not rounding_unit:
            return [raw_target] * (n - 1)
        if n == 1:
            # Pas de tranche de reliquat pour absorber un dépassement d'arrondi (ceiling peut
            # dépasser total_due) : la liste est de toute façon vide (n-1=0, jamais consultée
            # par _build_installment_commands pour une échéance unique, qui prend directement
            # la branche "dernière tranche = reliquat exact") - retournée explicitement ici pour
            # ne jamais calculer/exposer une cible arrondie qui dépasserait total_due.
            return []
        if rounding_mode == 'distributed':
            floor_target = math.floor(raw_target / rounding_unit) * rounding_unit
            remainder_amount = total_due - (floor_target * n)
            extra_units = min(int(remainder_amount // rounding_unit), n - 1)
            targets = [floor_target] * (n - 1)
            for i in range(1, extra_units + 1):
                targets[-i] += rounding_unit
            return targets
        # rounding_mode == 'last_installment' (défaut historique)
        base_target = self._round_installment_target(raw_target, rounding_unit, self.product_id.installment_rounding_mode)
        return [base_target] * (n - 1)

    def _build_installment_commands(self, rounding_mode='last_installment', raise_on_negative_reliquat=False):
        """Retourne une liste de commandes o2m (0, 0, vals) pour installment_ids, calculée avec
        la même logique interest-first que action_generate_schedule (délai de grâce, arrondi de
        la cible, branche reducing) - extrait ici pour être réutilisable à la fois par le bouton
        "Générer échéancier" (écriture réelle) et par l'onchange d'aperçu en direct (Lot E,
        recalcul en mémoire avant sauvegarde - toujours en mode 'last_installment', l'aperçu
        avant sauvegarde n'expose pas le choix du wizard). Ne lève aucune exception PAR DÉFAUT
        (contrairement à action_generate_schedule) : un onchange ne doit jamais planter sur un
        formulaire incomplet, retourne simplement [] si les prérequis ne sont pas réunis.

        `raise_on_negative_reliquat` (défaut False, préserve le comportement onchange
        ci-dessus) : si True, lève une ValidationError quand la dernière tranche (celle qui
        absorbe le reliquat, branche `interest_method == 'flat'` uniquement) serait négative -
        garde-fou Lot "garde_fou_reliquat_negatif", cf. docs_dev/garde_fou_reliquat_negatif/
        AUDIT.md pour la condition mathématique exacte. Effet de bord possible de l'arrondi
        `ceiling` (Lot 1) quand le nombre d'échéances est élevé par rapport au montant du
        crédit : le surplus d'arrondi cumulé sur les `n-1` premières tranches peut dépasser le
        total dû. Seul `action_generate_schedule()` passe `True` ici - c'est le point de
        convergence unique de tous les chemins qui persistent réellement l'échéancier (bouton
        "Générer échéancier", _propagate_avis_to_loan(), et l'écriture automatique de write()
        cf. _SCHEDULE_TRIGGER_FIELDS), donc suffisant pour couvrir tous les points d'entrée sans
        dupliquer le contrôle."""
        self.ensure_one()
        if not self.repayment_frequency_id or not self.loan_amount or not self.term:
            return []
        remaining = self.loan_amount
        # Ancre de l'échéancier : la date de décaissement réelle si elle est connue (crédit
        # déjà décaissé, régénération via _regenerate_schedule_from_disbursement), sinon
        # approval_date -> application_date -> jour courant, comme avant le découplage
        # activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md §3).
        start = self.disbursement_date or self.approval_date or self.application_date or fields.Date.context_today(self)
        delta = self._period_delta()
        interest_factor = self._period_interest_factor()
        grace_days = self.product_id.grace_period_days or 0
        schedule_start = start
        vals = []
        sequence_offset = 0
        if grace_days:
            schedule_start = fields.Date.add(start, days=grace_days)
            period_days = ((start + delta) - start).days
            if grace_days > period_days:
                grace_interest = self.loan_amount * (self.interest_rate / 100.0) / 365.0 * grace_days
                vals.append({
                    'sequence': 1,
                    'due_date': schedule_start,
                    'principal_amount': 0.0,
                    'interest_amount': grace_interest,
                })
                sequence_offset = 1
        if self.interest_method == 'flat':
            # Politique CEFOR "intérêt d'abord" (interest-first, toutes agences/produits en
            # taux uniforme confondus - pas une option par produit) : chaque tranche cible un
            # montant total identique (total_dû / nb_tranches) ; l'intérêt total du crédit
            # (taux uniforme, formule déjà en place : montant x taux annuel x période x nombre
            # de tranches) est consommé en priorité sur les premières tranches jusqu'à
            # épuisement, le principal ne comble que le reste de la cible. La dernière tranche
            # absorbe exactement le reliquat (principal restant, intérêt restant) plutôt que
            # de recalculer sa propre cible, pour que les totaux somment exactement au capital
            # et à l'intérêt total - aucun euro/ariary ne se perd à l'arrondi flottant.
            #
            # Le délai de grâce ci-dessus reste un mécanisme distinct et déjà pris en compte :
            # sa tranche dédiée (le cas échéant) est déjà ajoutée à `vals` avant cette boucle,
            # avec son propre intérêt calculé séparément ; cette boucle ne porte que sur les
            # `self.term` tranches "normales" restantes.
            total_interest = self.loan_amount * (self.interest_rate / 100.0) * interest_factor * self.term
            total_due = self.loan_amount + total_interest
            # Cible par tranche (arrondie au plus proche multiple de installment_rounding_unit,
            # champ de configuration du produit) : mode 'last_installment' historique (une
            # seule cible, la dernière tranche absorbe tout le reliquat) ou 'distributed'
            # (reliquat réparti en incréments de l'unité d'arrondi sur les dernières tranches),
            # au choix de l'utilisateur via le wizard de génération - cf.
            # _compute_installment_targets. Le reliquat réel (différence entre la somme des
            # cibles et le total dû exact) est de toute façon absorbé par la dernière tranche
            # ci-dessous, quel que soit le mode.
            rounding_unit = self.product_id.installment_rounding_unit
            installment_targets = self._compute_installment_targets(total_due, rounding_unit, rounding_mode)
            interest_remaining = total_interest
            principal_allocated = 0.0
            for idx in range(1, self.term + 1):
                due_date = schedule_start + (delta * idx)
                if idx == self.term:
                    principal_amount = self.loan_amount - principal_allocated
                    interest_amount = interest_remaining
                else:
                    target = installment_targets[idx - 1]
                    interest_amount = min(interest_remaining, target)
                    principal_amount = target - interest_amount
                    interest_remaining -= interest_amount
                    principal_allocated += principal_amount
                vals.append({
                    'sequence': idx + sequence_offset,
                    'due_date': due_date,
                    'principal_amount': principal_amount,
                    'interest_amount': interest_amount,
                })
            if raise_on_negative_reliquat and vals:
                last = vals[-1]
                reliquat = last['principal_amount'] + last['interest_amount']
                if reliquat < -0.01:
                    raise ValidationError(_(
                        "Impossible de générer cet échéancier : avec ce montant, ce nombre "
                        "d'échéances et l'arrondi actuel, la dernière échéance calculée serait "
                        "négative (%(reliquat).2f Ar). Cela arrive en général quand le nombre "
                        "d'échéances est élevé par rapport au montant du crédit. Contactez le "
                        "support technique pour ajuster le paramétrage (produit ou unité "
                        "d'arrondi) avant de continuer."
                    ) % {'reliquat': reliquat})
        else:
            # Méthode dégressive (solde restant dû) : hors périmètre de la Décision 1, qui ne
            # porte que sur le taux uniforme ("flat") - dans ce mode l'intérêt total n'est pas
            # connu à l'avance indépendamment de l'échéancier (il dépend du solde restant à
            # chaque période, lui-même fonction du rythme d'amortissement du principal), donc
            # la notion de "pool d'intérêt total à consommer en premier" de l'algorithme
            # interest-first ne s'y applique pas telle quelle. Logique dégressive existante
            # conservée à l'identique.
            principal = self.loan_amount / self.term
            for idx in range(1, self.term + 1):
                interest = remaining * (self.interest_rate / 100.0) * interest_factor
                due_date = schedule_start + (delta * idx)
                vals.append({
                    'sequence': idx + sequence_offset,
                    'due_date': due_date,
                    'principal_amount': principal,
                    'interest_amount': interest,
                })
                remaining -= principal
        return [(0, 0, v) for v in vals]

    def action_generate_schedule(self, rounding_mode='last_installment'):
        for loan in self:
            if loan.state not in loan._EDITABLE_SCHEDULE_STATES:
                raise UserError(_('Échéancier autorisé avant activation seulement.'))
            if not loan.repayment_frequency_id:
                raise UserError(_(
                    'Ce produit laisse le choix de la périodicité de remboursement : '
                    "choisissez-en une avant de générer l'échéancier."
                ))
            # (5, 0, 0) ("vider" l'o2m) plutôt que installment_ids.unlink() : équivalent
            # fonctionnel, mais passe par la même API o2m que les onchange d'aperçu en direct
            # ci-dessus, pour que tous les chemins utilisent exactement le même code sans
            # divergence.
            loan.installment_ids = [(5, 0, 0)] + loan._build_installment_commands(
                rounding_mode=rounding_mode, raise_on_negative_reliquat=True)
        return True

    def action_generate_schedule_button(self):
        """Point d'entrée UI (bouton en-tête « Générer l'échéancier ») de la génération
        manuelle. Nécessaire depuis le retrait du bouton historique + wizard
        (docs_dev/retrait_bouton_generer_echeancier/) : la persistance automatique passe par
        write()/_SCHEDULE_TRIGGER_FIELDS, qui ne se déclenche jamais sur un dossier créé puis
        approuvé sans qu'aucun champ source ne soit ré-écrit (ni flux avis, ni décaissement) -
        cas réel IS/003362, échéancier resté vide. Ce bouton rejoue exactement le même calcul
        que les onchange d'aperçu, mais via action_generate_schedule() (écriture serveur hors
        cycle onchange), donc persisté.

        Reproduit ici la garde de write() (loan_amount/term/repayment_frequency_id présents) :
        action_generate_schedule() ne la porte pas et, appelée nue sur un dossier incomplet,
        _build_installment_commands() retourne [] -> installment_ids = [(5, 0, 0)] + []
        VIDERAIT l'échéancier existant sans le recréer. Mode d'arrondi toujours
        'last_installment' (comme _propagate_avis_to_loan() et write()) - 'distributed' n'a
        plus d'accès UI depuis le retrait du wizard, mais reste joignable par code via
        action_generate_schedule(rounding_mode=...).

        Retour `soft_reload` (et non `display_notification`) : un retour notification
        n'entraîne PAS de rechargement du formulaire (cf. web/.../view_button_hook.js -
        `model.load()` uniquement dans le `onClose` d'une action absente/fermée), l'onglet
        Échéancier et le compteur resteraient donc figés à l'ouverture de la fiche, et le
        chatter n'afficherait pas le message posté ci-dessous (même limite que les boutons
        d'impression, contournée pour eux par MicrofinanceLoanFormController via
        MAIL:RELOAD-THREAD). `soft_reload` réinstancie le contrôleur courant : re-fetch de
        l'enregistrement (échéances + compteur) ET Chatter reconstruit (message visible),
        sans rechargement complet du navigateur. Le feedback utilisateur passe par le
        message chatter, pas par un toast."""
        self.ensure_one()
        if not (self.loan_amount and self.term and self.repayment_frequency_id):
            raise UserError(_(
                "Renseignez le montant, le nombre d'échéances et la périodicité de "
                "remboursement avant de générer l'échéancier."))
        self.action_generate_schedule()
        self.message_post(body=_(
            "Échéancier généré manuellement (%d échéances).") % len(self.installment_ids))
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_reschedule(self):
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Le rééchelonnement n\'est possible que pour un crédit actif.'))
        if not self.disbursement_date:
            # Découplage activation / décaissement (AUDIT_decaissement.md) : rien à rééchelonner
            # tant que le crédit n'est pas décaissé (l'échéancier est de toute façon recalé sur
            # la date de décaissement effective).
            raise UserError(_(
                "Ce crédit n'est pas encore décaissé : le rééchelonnement n'a de sens "
                "qu'après le décaissement effectif."))
        if not self.installment_ids.filtered(lambda inst: inst.state != 'paid'):
            raise UserError(_('Aucune échéance restante à rééchelonner.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rééchelonner le crédit'),
            'res_model': 'microfinance.loan.reschedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def _reschedule_installments(self, new_term, new_first_due_date, reason=False):
        self.ensure_one()
        unpaid = self.installment_ids.filtered(lambda inst: inst.state != 'paid').sorted(lambda inst: (inst.due_date, inst.sequence))
        if not unpaid:
            raise UserError(_('Aucune échéance restante à rééchelonner.'))

        def _summary(installments):
            return '<br/>'.join(
                _('Échéance %s : %s - Capital %.2f, Intérêt %.2f, Solde %.2f') % (
                    inst.sequence, inst.due_date, inst.principal_amount, inst.interest_amount, inst.residual_amount
                ) for inst in installments
            ) or _('Aucune échéance')

        old_summary = _summary(unpaid)
        # Structured snapshot of the schedule about to be dropped/rewritten below, kept
        # queryable (ORM/report/filter) instead of only readable in the chatter message.
        self.env['microfinance.loan.reschedule.history'].create({
            'loan_id': self.id,
            'reason': reason,
            'old_installment_ids': [(0, 0, {
                'sequence': inst.sequence,
                'due_date': inst.due_date,
                'principal_amount': inst.principal_amount,
                'interest_amount': inst.interest_amount,
                'penalty_amount': inst.penalty_amount,
                'paid_principal': inst.paid_principal,
                'paid_interest': inst.paid_interest,
                'paid_penalty': inst.paid_penalty,
                'residual_amount': inst.residual_amount,
            }) for inst in unpaid],
        })
        remaining_principal = sum(inst.principal_amount - inst.paid_principal for inst in unpaid)
        # Only arrears (overdue or partially paid) carry interest/penalty already accrued and due;
        # plain future pending installments have their interest recomputed fresh below.
        arrears = unpaid.filtered(lambda inst: inst.state in ('overdue', 'partial'))
        carried_interest = sum(inst.interest_amount - inst.paid_interest for inst in arrears)
        carried_penalty = sum(inst.penalty_amount - inst.paid_penalty for inst in arrears)
        term = new_term or len(unpaid)
        original_first_due_date = unpaid[0].due_date
        start = new_first_due_date or original_first_due_date
        delta = self._period_delta()
        interest_factor = self._period_interest_factor()

        # Partially paid installments keep their history (paid_* amounts stay untouched for
        # accounting purposes) but are locked to what was actually collected; the outstanding
        # part is carried into the new schedule instead. Untouched installments are dropped.
        partially_paid = unpaid.filtered(lambda inst: inst.paid_principal or inst.paid_interest or inst.paid_penalty)
        for inst in partially_paid:
            inst.write({
                'principal_amount': inst.paid_principal,
                'interest_amount': inst.paid_interest,
                'penalty_amount': inst.paid_penalty,
            })
        (unpaid - partially_paid).unlink()
        vals = []
        sequence = 1
        if carried_interest > 0.01 or carried_penalty > 0.01:
            # Interest/penalty already accrued before the reschedule keep their original due date,
            # in a dedicated line so they are not lost nor merged with the new principal schedule.
            vals.append((0, 0, {
                'sequence': sequence,
                'due_date': original_first_due_date,
                'principal_amount': 0.0,
                'interest_amount': max(carried_interest, 0.0),
                'penalty_amount': max(carried_penalty, 0.0),
            }))
            sequence += 1
        principal = remaining_principal / term
        remaining = remaining_principal
        for idx in range(term):
            if self.interest_method == 'flat':
                interest = remaining_principal * (self.interest_rate / 100.0) * interest_factor
            else:
                interest = remaining * (self.interest_rate / 100.0) * interest_factor
            due_date = start + (delta * idx)
            vals.append((0, 0, {
                'sequence': sequence,
                'due_date': due_date,
                'principal_amount': principal,
                'interest_amount': interest,
            }))
            remaining -= principal
            sequence += 1
        self.write({'installment_ids': vals})
        new_summary = _summary(self.installment_ids.filtered(lambda inst: inst.state != 'paid'))
        self.reschedule_count += 1
        self.message_post(body=_(
            'Rééchelonnement n°%(count)s effectué.<br/>Ancien échéancier restant :<br/>%(old)s'
            '<br/><br/>Nouvel échéancier :<br/>%(new)s'
        ) % {'count': self.reschedule_count, 'old': old_summary, 'new': new_summary})
        return True

    def _prepare_disbursement_move(self):
        self.ensure_one()
        product = self.product_id
        journal = product.disbursement_journal_id
        principal_account = product._get_account('principal', self.partner_id)
        if not journal or not principal_account or not journal.default_account_id:
            raise UserError(_('Configurez le journal de décaissement, son compte par défaut et le compte principal en cours du produit.'))
        credit_lines = [
            (0, 0, {'name': _('Sortie caisse/banque %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': 0.0, 'credit': self.net_disbursed_amount}),
        ]
        # Frais nettés du décaissement (fee_charged_before_disbursement=False) : le capital dû
        # (débit ci-dessous) reste plein, mais la sortie caisse est diminuée des frais, dont la
        # contrepartie est comptabilisée ici plutôt que via une écriture d'encaissement séparée
        # (action_charge_fee(), qui reste le mécanisme utilisé quand fee_charged_before_disbursement=True).
        if not product.fee_charged_before_disbursement and self.fee_amount_due > 0:
            if not product.account_commission_credit_id:
                raise UserError(_('Configurez le compte commission sur crédit du produit pour netter les frais de dossier du décaissement.'))
            credit_lines.append((0, 0, {
                'name': _('Frais de dossier %s') % self.name, 'partner_id': self.partner_id.id,
                'account_id': product.account_commission_credit_id.id, 'debit': 0.0, 'credit': self.fee_amount_due,
            }))
        return {
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Décaissement crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Crédit client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': principal_account.id, 'debit': self.loan_amount, 'credit': 0.0}),
            ] + credit_lines
        }

    def _prepare_fee_receivable_move(self):
        """Écriture d'ENGAGEMENT des frais de dossier, créée à l'approbation (flux Option A) :
        débit "frais de dossier à recevoir" (208005) / crédit "commission sur crédit" (717003),
        dans le journal d'opérations diverses du produit (pas un mouvement de trésorerie). Le
        crédit 717003 constate le produit dès l'engagement ; le débit 208005 ouvre la créance
        que _prepare_fee_settlement_move() soldera à l'encaissement effectif."""
        self.ensure_one()
        product = self.product_id
        journal = product.fee_engagement_journal_id
        if not journal or not product.account_fee_receivable_id or not product.account_commission_credit_id:
            raise UserError(_(
                "Configurez le journal d'engagement des frais (opérations diverses), le compte "
                "« Frais de dossier à recevoir » et le compte « Commission sur crédit » du "
                "produit avant d'approuver un dossier avec frais exigés avant décaissement."))
        return {
            'date': self.approval_date or fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Engagement frais de dossier crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Frais de dossier à recevoir %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.account_fee_receivable_id.id, 'debit': self.fee_amount_due, 'credit': 0.0}),
                (0, 0, {'name': _('Frais de dossier %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product.account_commission_credit_id.id, 'debit': 0.0, 'credit': self.fee_amount_due}),
            ]
        }

    def _prepare_fee_settlement_move(self):
        """Écriture de RÈGLEMENT des frais de dossier, créée au clic « Encaisser » : débit caisse
        (compte par défaut de fee_journal_id) / crédit la contrepartie. Depuis le flux Option A,
        la contrepartie est le compte de créance « frais à recevoir » (208005) quand une écriture
        d'engagement a été créée à l'approbation (cas normal des produits « frais exigés avant
        décaissement ») : le règlement SOLDE alors la créance, le produit ayant déjà été constaté
        à l'engagement. Repli sur « commission sur crédit » (717003) si aucun engagement n'existe
        (dossier antérieur au flux Option A non rattrapé, ou produit sans compte de créance
        configuré) - comportement identique à l'ancien _prepare_fee_move()."""
        self.ensure_one()
        product = self.product_id
        journal = product.fee_journal_id
        use_receivable = bool(self.fee_receivable_move_id and product.account_fee_receivable_id)
        counterpart = product.account_fee_receivable_id if use_receivable else product.account_commission_credit_id
        if not journal or not journal.default_account_id or not counterpart:
            raise UserError(_('Configurez le journal d\'encaissement des frais, son compte par défaut et le compte commission sur crédit du produit.'))
        counterpart_label = _('Solde créance frais %s') % self.name if use_receivable else _('Frais de dossier %s') % self.name
        return {
            'date': fields.Date.context_today(self),
            'journal_id': journal.id,
            'ref': _('Frais de dossier crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Encaissement frais %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': journal.default_account_id.id, 'debit': self.fee_amount_due, 'credit': 0.0}),
                (0, 0, {'name': counterpart_label, 'partner_id': self.partner_id.id, 'account_id': counterpart.id, 'debit': 0.0, 'credit': self.fee_amount_due}),
            ]
        }

    def action_send_fee_to_cashier(self):
        """Remplace le rôle de l'ancien bouton « Encaisser les frais de dossier » sur la fiche
        crédit : ne comptabilise RIEN, pose seulement le marqueur fee_sent_to_cashier qui fait
        apparaître le dossier dans l'onglet « Frais » du guichet. L'encaissement comptable réel
        (action_charge_fee) a lieu au passage en caisse. Mêmes gardes de garde-fou que
        action_charge_fee, plus l'exclusion des produits « frais nettés au décaissement »."""
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Les frais de dossier ne peuvent être envoyés en caisse que sur un crédit approuvé.'))
            if loan.fee_paid:
                raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
            if loan.fee_amount_due <= 0:
                raise UserError(_('Aucun frais de dossier à encaisser pour ce crédit.'))
            if not loan.product_id.fee_charged_before_disbursement:
                raise UserError(_("Les frais de ce produit sont nettés au décaissement, pas d'envoi en caisse nécessaire."))
            if loan.fee_sent_to_cashier:
                raise UserError(_('Ce dossier a déjà été envoyé en caisse.'))
            loan.fee_sent_to_cashier = True
            loan.message_post(body=_('Frais de dossier envoyés en caisse (%.2f).') % loan.fee_amount_due)
        return True

    @api.model
    def get_pending_fees(self, company_id):
        """Dossiers dont les frais ont été envoyés en caisse et restent à encaisser, pour
        l'onglet « Frais » du guichet (docs_dev/guichet_caisse/AUDIT_frais.md). Périmètre acté :
        approuvés, frais envoyés (fee_sent_to_cashier), non encore payés, frais dus > 0, et
        produit en mode « frais exigés avant décaissement » (les frais nettés au décaissement
        sont comptabilisés ailleurs, ils ne passent jamais en caisse). Filtre company_id
        explicite - défense en profondeur (cf. AUDIT.md §5)."""
        loans = self.search([
            ('state', '=', 'approved'),
            ('company_id', '=', company_id),
            ('fee_sent_to_cashier', '=', True),
            ('fee_paid', '=', False),
            ('fee_amount_due', '>', 0),
            ('product_id.fee_charged_before_disbursement', '=', True),
        ], order='id asc')
        return [{
            'id': loan.id,
            'partner_id': loan.partner_id.id,
            'partner_name': loan.partner_id.name,
            'dossier': loan.name,
            'product_name': loan.product_id.name,
            'amount': loan.fee_amount_due,
            'company_name': loan.company_id.name,
        } for loan in loans]

    def action_charge_fee(self):
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Les frais de dossier ne peuvent être encaissés que sur un crédit approuvé.'))
            if not loan.fee_sent_to_cashier:
                raise UserError(_("Les frais doivent d'abord être envoyés en caisse avant encaissement."))
            # Verrou pessimiste ligne (FOR UPDATE) posé AVANT la relecture de fee_paid /
            # fee_amount_due : sérialise deux requêtes « Encaisser les frais » concurrentes sur
            # le même dossier en prod multi-worker (docs_dev/refactor_frais_dossier_account_move/
            # AUDIT.md §6). La transaction perdante attend le commit de la gagnante sur ce SELECT,
            # puis invalide son cache et retombe sur la garde fee_paid ci-dessous - au lieu de
            # créer un second account.move sur un fee_paid encore lu à False. Verrou relâché
            # automatiquement au commit/rollback ; portée strictement limitée à la transaction du
            # clic bouton (aucun verrou tenu au-delà, aucun impact perf en usage normal où il n'y
            # a jamais de contention sur cette ligne).
            loan.env.cr.execute("SELECT id FROM microfinance_loan WHERE id = %s FOR UPDATE", (loan.id,))
            loan.invalidate_recordset(['fee_paid', 'fee_amount_due'])
            if loan.fee_paid:
                raise UserError(_('Les frais de dossier ont déjà été encaissés.'))
            if loan.fee_amount_due <= 0:
                raise UserError(_('Aucun frais de dossier à encaisser pour ce crédit.'))
            # Rattrapage de l'engagement manquant : un dossier approuvé AVANT que le produit
            # ne soit configuré pour le flux Option A (compte de créance + journal OD) n'a
            # pas reçu son écriture d'engagement à l'approbation, et la migration ne rejoue
            # pas. Sans ce rattrapage, _prepare_fee_settlement_move() basculerait sur le repli
            # (crédit 717003 direct), sans trace de créance. On crée donc l'engagement ici,
            # juste avant le règlement qui le soldera - même garde
            # (_is_fee_engagement_applicable) que action_approve().
            if loan._is_fee_engagement_applicable():
                engagement = self.env['account.move'].with_context(
                    default_loan_id=False, default_loan_line_id=False,
                ).create(loan._prepare_fee_receivable_move())
                engagement.action_post()
                loan.fee_receivable_move_id = engagement.id
                loan.message_post(body=_(
                    'Engagement frais de dossier (rattrapage à l\'encaissement, %.2f). '
                    'Écriture : %s') % (loan.fee_amount_due, engagement.name))
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_fee_settlement_move())
            move.action_post()
            loan.write({'fee_paid': True, 'fee_move_id': move.id})
            receivable_account = loan.product_id.account_fee_receivable_id
            if loan.fee_receivable_move_id and receivable_account.reconcile:
                # Lettrage engagement <-> règlement : le solde restant du compte 208005
                # ne reflète alors que les créances réellement ouvertes (dossiers approuvés
                # dont les frais ne sont pas encore encaissés).
                (loan.fee_receivable_move_id.line_ids + move.line_ids).filtered(
                    lambda l: l.account_id == receivable_account and not l.reconciled
                ).reconcile()
            loan.message_post(body=_('Frais de dossier encaissés (%.2f). Écriture : %s') % (loan.fee_amount_due, move.name))
        return True

    def _get_principal_outstanding(self):
        """Principal restant dû de ce crédit (hors intérêts/pénalités) : somme des
        principal_amount des échéances diminuée du principal déjà payé ; si aucune échéance
        n'existe encore (crédit approuvé, pas encore décaissé), retombe sur loan_amount (capital
        plein déjà réservé sur le fonds bailleur dès l'approbation). Partagé entre
        MicrofinanceFondCredit._compute_fond_totals() (agrégat par fonds) et
        _check_fond_disponibilite() ci-dessous (réservation du crédit en cours de traitement)."""
        self.ensure_one()
        if self.installment_ids:
            return sum(self.installment_ids.mapped('principal_amount')) - sum(self.installment_ids.mapped('paid_principal'))
        return self.loan_amount

    @api.depends('company_id')
    def _compute_has_active_fond(self):
        """Recalcule, pour chaque société, si au moins un fonds actif lui est visible - mêmes
        critères que le domaine de fond_credit_id (champ ci-dessus) : un fonds 'single_company'
        d'une autre société ne compte pas, un fonds 'multi_company' compte toujours. Ne dépend que
        de company_id (pas de fond_credit_id lui-même) : ce champ sert à décider si fond_credit_id
        doit être obligatoire, il ne doit donc pas varier quand on le renseigne."""
        Fond = self.env['microfinance.fond.credit']
        today = fields.Date.context_today(self)
        for loan in self:
            if not loan.company_id:
                loan.has_active_fond = False
                continue
            loan.has_active_fond = bool(Fond.search_count([
                ('active', '=', True),
                '|', ('date_cloture', '=', False), ('date_cloture', '>=', today),
                '|', '&', ('scope', '=', 'single_company'), ('company_id', '=', loan.company_id.id),
                ('scope', '=', 'multi_company'),
            ]))

    @api.constrains('fond_credit_id')
    def _check_fond_credit_id_locked_after_disbursement(self):
        """Une fois le crédit décaissé (disbursement_date renseigné - couvre 'active' et tout état
        ultérieur : closed, defaulted, written_off, ce champ n'est jamais effacé après le premier
        décaissement, cf. action_disburse() ci-dessous), fond_credit_id ne peut plus être modifié.

        Bug corrigé ici (constaté en test manuel) : le solde_disponible du fonds est déjà diminué
        du principal de ce crédit au moment du décaissement (écriture comptable posée sur ce
        fonds) ; vider ou changer fond_credit_id après coup restaurait artificiellement le solde
        affiché côté module SANS toucher à l'écriture comptable, qui reste posée sur l'ancien
        fonds - incohérence directe entre comptabilité et solde affiché. Contrôle serveur
        (constrains, pas seulement readonly vue, même raisonnement que le Lot 2bis) : un write()
        direct via ORM/API/import doit être bloqué exactement comme depuis le formulaire."""
        for loan in self:
            if loan.disbursement_date:
                raise ValidationError(_(
                    "Le fonds de crédit rotatif d'un crédit déjà décaissé ne peut plus être modifié."
                ))

    def _check_fond_disponibilite(self):
        """Vérifie la disponibilité du fonds de crédit rotatif rattaché (fond_credit_id), selon
        fond_credit_id.verification_disponibilite. Méthode réutilisable, mais avec un seul point
        d'ancrage réel pour l'instant : action_disburse() ci-dessous, qui ne déclenche un contrôle
        que si verification_disponibilite == 'at_disbursement'. 'never' ET 'at_request' laissent
        donc tous deux passer le décaissement sans contrôle ici : 'at_request' n'a et ne doit avoir
        AUCUN effet observable tant que microfinance.loan.application (son point d'ancrage prévu,
        la transition vers l'état "submitted") reste hors-périmètre, non câblé au module. Ne pas
        le traiter comme un repli silencieux vers 'at_disbursement' : ce serait un comportement de
        blocage non documenté et non voulu par la configuration choisie par l'utilisateur.

        Avant tout ça : si le crédit n'a AUCUN fond_credit_id mais qu'un fonds actif existe pour sa
        société, on bloque par oubli probable - sauf si l'agence ne dispose d'aucun fonds bailleur,
        auquel cas le décaissement sans rattachement reste le fonctionnement mutualiste normal
        (non-régression du Lot 2)."""
        for loan in self:
            fond = loan.fond_credit_id
            if not fond:
                if loan.has_active_fond:
                    raise UserError(_(
                        'Un fonds de crédit rotatif actif existe pour cette agence. Veuillez le '
                        'sélectionner avant de décaisser.'
                    ))
                continue
            if fond.verification_disponibilite != 'at_disbursement':
                continue
            today = fields.Date.context_today(loan)
            if fond.date_debut > today:
                raise UserError(_(
                    'Le fonds "%(fond)s" n\'est pas encore actif (date de début : %(date)s).'
                ) % {'fond': fond.name, 'date': fond.date_debut})
            if fond.date_cloture and fond.date_cloture < today:
                raise UserError(_(
                    'Le fonds "%(fond)s" est clôturé depuis le %(date)s.'
                ) % {'fond': fond.name, 'date': fond.date_cloture})
            # fond.solde_disponible a déjà déduit la réservation de CE crédit lui-même (déjà à
            # l'état 'approved', donc déjà compté dans l'encours agrégé du fonds) : on la
            # rajoute pour obtenir le solde réellement disponible AVANT ce crédit, seule base de
            # comparaison correcte pour distinguer "fonds vide" de "solde insuffisant".
            solde_avant_ce_credit = fond.solde_disponible + loan._get_principal_outstanding()
            if solde_avant_ce_credit <= 0:
                raise UserError(_(
                    "Ce fonds ne dispose d'aucun solde disponible. Veuillez l'approvisionner via "
                    "une contribution avant de poursuivre."
                ))
            if solde_avant_ce_credit < loan.loan_amount:
                raise UserError(_(
                    'Solde insuffisant sur le fonds « %(fond)s » (disponible : %(disponible)s, demandé : %(demande)s).'
                ) % {'fond': fond.name, 'disponible': solde_avant_ce_credit, 'demande': loan.loan_amount})

    def _check_disbursement_limit(self):
        """Plafond de décaissement en espèces (product_id.disbursement_limit_amount) : blocage
        simple par décaissement individuel, pas de cumul sur une période — même principe que
        _check_withdrawal_limit côté épargne (microfinance_savings_transaction.py). Ne s'applique
        que si le journal de décaissement est de type 'cash' : un décaissement par banque n'est
        pas soumis à ce plafond, la contrainte étant liée à la manipulation physique d'espèces."""
        for loan in self:
            product = loan.product_id
            limit = product.disbursement_limit_amount
            if not limit:
                continue
            journal = product.disbursement_journal_id
            if not journal or journal.type != 'cash':
                continue
            if loan.net_disbursed_amount > limit + 0.01:
                raise UserError(_(
                    'Décaissement refusé : le montant net remis au client (%(amount).2f) '
                    'dépasse le plafond de décaissement en espèces du produit (%(limit).2f).'
                ) % {'amount': loan.net_disbursed_amount, 'limit': limit})

    def _check_cash_journal_balance(self):
        """Solde comptable réel du journal de décaissement (disbursement_journal_id.
        default_account_id.current_balance, champ calculé standard Odoo sur account.account) :
        blocage dur si le décaissement ferait passer ce compte sous zéro, sauf dérogation
        explicite (bypass_cash_balance). Ne s'applique que si le journal est de type 'cash' et
        si le produit a explicitement activé check_cash_balance_at_disbursement (désactivé par
        défaut : voir le help de ce champ pour la raison — même principe que
        _check_disbursement_limit ci-dessus."""
        for loan in self:
            product = loan.product_id
            if loan.bypass_cash_balance or not product.check_cash_balance_at_disbursement:
                continue
            journal = product.disbursement_journal_id
            if not journal or journal.type != 'cash' or not journal.default_account_id:
                continue
            account = journal.default_account_id
            projected_balance = account.current_balance - loan.net_disbursed_amount
            if projected_balance < 0:
                raise UserError(_(
                    'Décaissement refusé : solde insuffisant sur le journal de caisse '
                    '« %(journal)s » (disponible : %(balance).2f, demandé : %(amount).2f).'
                ) % {'journal': journal.name, 'balance': account.current_balance, 'amount': loan.net_disbursed_amount})

    def action_activate(self):
        """Activation du crédit (bouton fiche « Activer ») : rejoue TOUS les contrôles
        d'éligibilité de l'ancien action_disburse (contrat signé, frais payés, plafond de
        décaissement, solde de caisse, disponibilité du fonds), puis fait passer le crédit à
        'active' — SANS créer d'écriture comptable ni poser disbursement_date. Le décaissement
        effectif (sortie de caisse) a lieu séparément via le Guichet Caisse
        (action_process_disbursement, appelée par register_operation type decaissement_credit).
        Décision Micka (docs_dev/guichet_caisse/AUDIT_decaissement.md) : découplage
        activation / décaissement, contrôles conservés au clic « Activer » (même si l'argent ne
        sort qu'ensuite), jamais rejoués au décaissement effectif."""
        for loan in self:
            if loan.state != 'approved':
                raise UserError(_('Le crédit doit être approuvé avant activation.'))
            if not loan.signed_contract:
                raise UserError(_(
                    "Le contrat signé doit être téléversé avant l'activation du crédit."
                ))
            if loan.product_id.fee_charged_before_disbursement and not loan.fee_paid and loan.fee_amount_due > 0:
                raise UserError(_('Les frais de dossier doivent être encaissés avant le décaissement.'))
            loan._check_disbursement_limit()
            loan._check_cash_journal_balance()
            loan._check_fond_disponibilite()
            if not loan.installment_ids:
                loan.action_generate_schedule()
            loan.write({'state': 'active', 'activation_date': fields.Date.context_today(loan)})
            loan.message_post(body=_('Crédit activé, en attente de décaissement en caisse.'))
        return True

    def action_process_disbursement(self):
        """Décaissement effectif : crée et poste l'écriture de sortie de caisse/banque
        (_prepare_disbursement_move, inchangée), pose disbursement_date, puis re-cale
        l'échéancier sur la date de décaissement réelle. Appelée depuis le Guichet Caisse
        (register_operation type decaissement_credit, via _run_posting_sudo) — jamais depuis un
        bouton de fiche. Ne rejoue AUCUN contrôle d'éligibilité : ils ont tous été passés à
        action_activate (décision Micka, cf. AUDIT_decaissement.md)."""
        for loan in self:
            if loan.state != 'active':
                raise UserError(_('Le crédit doit être activé avant le décaissement effectif.'))
            # Verrou pessimiste ligne (FOR UPDATE) posé AVANT la relecture de state /
            # disbursement_date : sérialise deux décaissements concurrents du même crédit en
            # prod multi-worker (bouton fiche déprécié + guichet register_operation), sur le
            # modèle exact de action_charge_fee (docs_dev/guichet_caisse/AUDIT_decaissement.md
            # §4). La transaction perdante attend le commit de la gagnante sur ce SELECT, puis
            # invalide son cache et retombe sur la garde disbursement_date ci-dessous - au lieu
            # de créer un second account.move de décaissement. Verrou relâché au commit/rollback.
            loan.env.cr.execute("SELECT id FROM microfinance_loan WHERE id = %s FOR UPDATE", (loan.id,))
            loan.invalidate_recordset(['state', 'disbursement_date'])
            if loan.state != 'active':
                raise UserError(_('Le crédit doit être activé avant le décaissement effectif.'))
            if loan.disbursement_date:
                raise UserError(_('Ce crédit a déjà été décaissé.'))
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_disbursement_move())
            move.action_post()
            loan.write({'disbursement_date': fields.Date.context_today(loan)})
            loan._regenerate_schedule_from_disbursement()
            loan.message_post(body=_('Crédit décaissé. Écriture : %s') % move.name)
        return True

    def _regenerate_schedule_from_disbursement(self):
        """Re-cale l'échéancier sur disbursement_date (qui vient d'être posé par
        action_process_disbursement). Avant le découplage, l'échéancier généré à l'approbation
        était ancré sur approval_date (_build_installment_commands) et jamais recalculé ; un
        crédit resté « activé, non décaissé » plusieurs jours aurait donc des due_date déjà
        échues au moment de la remise des fonds (docs_dev/guichet_caisse/AUDIT_decaissement.md
        §3). Ici on régénère avec la même mécanique interne que action_generate_schedule()
        (microfinance_loan.py, `installment_ids = [(5, 0, 0)] + _build_installment_commands(...)`),
        mais sans son contrôle d'état public (_EDITABLE_SCHEDULE_STATES exclut 'active').

        Garde anti-écrasement : action_generate_schedule() n'a pas de garde dédiée contre la
        régénération d'un échéancier déjà remboursé (elle s'appuie sur _EDITABLE_SCHEDULE_STATES,
        qui exclut tout état où un paiement est possible). En 'active' on la pose donc
        explicitement, avec la même détection « de l'argent a déjà été imputé » que
        _reschedule_installments (`inst.paid_principal or inst.paid_interest or inst.paid_penalty`)."""
        self.ensure_one()
        if any(inst.paid_principal or inst.paid_interest or inst.paid_penalty
               for inst in self.installment_ids):
            raise UserError(_(
                "Impossible de recaler l'échéancier sur la date de décaissement : des "
                "remboursements ont déjà été imputés sur ce crédit."))
        commands = self._build_installment_commands(
            rounding_mode='last_installment', raise_on_negative_reliquat=True)
        if not commands:
            # loan_amount / term / repayment_frequency_id manquants : ne pas vider un
            # échéancier existant. Ne devrait pas arriver ici (échéancier déjà généré à
            # l'approbation), garde défensive.
            return
        self.installment_ids = [(5, 0, 0)] + commands
        return True

    def action_disburse(self):
        """DÉPRÉCIÉ (docs_dev/guichet_caisse/AUDIT_decaissement.md) : conservé uniquement comme
        enchaînement action_activate() + action_process_disbursement() pour les appelants et
        tests pas encore migrés vers le découplage. À supprimer une fois le sous-lot F et la
        migration des tests directs (test_disbursement_limit, test_cash_balance_check,
        test_fond_bailleur, test_fee, test_reschedule, test_repayment_accounting,
        test_caisse_pos) terminés. Ne PAS l'utiliser dans du code nouveau."""
        self.action_activate()
        self.action_process_disbursement()
        return True

    @api.model
    def get_pending_disbursements(self, company_id):
        """Crédits activés en attente de décaissement effectif, pour l'onglet « Décaissements
        en attente » du guichet (Lot 1.2). Depuis le découplage activation / décaissement
        (docs_dev/guichet_caisse/AUDIT_decaissement.md) : state == 'active' ET
        disbursement_date encore vide (seul cas accepté par action_process_disbursement).
        Filtre société explicite (le caissier est mono-agence, mais l'ir.rule ne borne qu'aux
        sociétés autorisées — défense en profondeur, cf. docs_dev/guichet_caisse/AUDIT.md §5).
        Montant = net_disbursed_amount (net des frais nettés), décision actée. File FIFO sur
        activation_date (date du clic « Activer »). Extraite en méthode de modèle pour rester
        testable directement, comme get_par_buckets / get_due_today."""
        loans = self.search([
            ('state', '=', 'active'),
            ('disbursement_date', '=', False),
            ('company_id', '=', company_id),
        ], order='activation_date asc, id asc')
        return [{
            'id': loan.id,
            'partner_id': loan.partner_id.id,
            'partner_name': loan.partner_id.name,
            'dossier': loan.name,
            'product_name': loan.product_id.name,
            'amount': loan.net_disbursed_amount,
            'approval_date': loan.approval_date,
            'activation_date': loan.activation_date,
            'company_name': loan.company_id.name,
        } for loan in loans]

    def action_write_off(self):
        self.ensure_one()
        if self.state not in ('active', 'defaulted'):
            raise UserError(_('La radiation n\'est possible que pour un crédit actif ou en défaut.'))
        if not self.disbursement_date:
            raise UserError(_(
                "Ce crédit n'est pas encore décaissé : il n'y a aucune créance à radier."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Radier le crédit'),
            'res_model': 'microfinance.loan.writeoff.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def _prepare_writeoff_move(self, write_off_date):
        self.ensure_one()
        product = self.product_id
        write_off_account = product._get_account('credits_perte', self.partner_id)
        if not write_off_account:
            raise UserError(_('Configurez le compte de crédits passés en perte pour ce produit avant de radier ce crédit.'))
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Aucun journal des opérations diverses n\'est configuré pour cette société.'))
        return {
            'date': write_off_date,
            'journal_id': journal.id,
            'ref': _('Radiation crédit %s') % self.name,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, {'name': _('Perte sur créance %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': write_off_account.id, 'debit': self.balance_total, 'credit': 0.0}),
                (0, 0, {'name': _('Sortie prêt client %s') % self.name, 'partner_id': self.partner_id.id, 'account_id': product._get_account('principal', self.partner_id).id, 'debit': 0.0, 'credit': self.balance_total}),
            ]
        }

    def action_confirm_write_off(self, reason, write_off_date):
        self.ensure_one()
        if self.state not in ('active', 'defaulted'):
            raise UserError(_('La radiation n\'est possible que pour un crédit actif ou en défaut.'))
        if not self.disbursement_date:
            # Rempart serveur (le bouton action_write_off porte la même garde) : découplage
            # activation / décaissement, AUDIT_decaissement.md.
            raise UserError(_(
                "Ce crédit n'est pas encore décaissé : il n'y a aucune créance à radier."))
        if self.balance_total <= 0.01:
            raise UserError(_('Aucun solde restant à radier. Utilisez la clôture normale.'))
        move = self.env['account.move'].with_context(
            default_loan_id=False,
            default_loan_line_id=False,
        ).create(self._prepare_writeoff_move(write_off_date))
        move.action_post()
        self.write({'state': 'written_off'})
        self.message_post(body=_('Crédit radié le %(date)s. Motif : %(reason)s. Écriture : %(move)s') % {
            'date': write_off_date, 'reason': reason, 'move': move.name,
        })
        return move

    def _get_misc_operations_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            raise UserError(_('Aucun journal des opérations diverses n\'est configuré pour cette société.'))
        return journal

    def _prepare_provision_move(self, delta, as_of_date):
        self.ensure_one()
        product = self.product_id
        provision_cout_account = product._get_account('provision_cout', self.partner_id)
        provision_contra_account = product._get_account('provision', self.partner_id)
        if not provision_cout_account or not provision_contra_account:
            raise UserError(_(
                'Configurez les comptes de provision (coût et contrepartie) pour le produit %s '
                'avant de comptabiliser une provision.'
            ) % product.display_name)
        journal = self._get_misc_operations_journal()
        amount = abs(delta)
        if delta > 0:
            label = _('Dotation provision %s') % self.name
            charge_vals = {'debit': amount, 'credit': 0.0}
            contra_vals = {'debit': 0.0, 'credit': amount}
        else:
            label = _('Reprise provision %s') % self.name
            charge_vals = {'debit': 0.0, 'credit': amount}
            contra_vals = {'debit': amount, 'credit': 0.0}
        return {
            'date': as_of_date,
            'journal_id': journal.id,
            'ref': label,
            'microfinance_loan_id': self.id,
            'line_ids': [
                (0, 0, dict(charge_vals, name=label, partner_id=self.partner_id.id, account_id=provision_cout_account.id)),
                (0, 0, dict(contra_vals, name=label, partner_id=self.partner_id.id, account_id=provision_contra_account.id)),
            ],
        }

    def action_post_provisions(self, as_of_date=None):
        """Comptabilise, pour chaque crédit actif ou en défaut de la sélection, le delta entre la
        provision déjà comptabilisée (provision_posted_amount) et la provision requise recalculée
        (provision_amount). Une écriture dédiée par crédit : plus facile à tracer/auditer une par
        une dans le chatter qu'une écriture consolidée, au prix d'un nombre d'écritures plus élevé
        lors d'une campagne mensuelle sur tout le portefeuille."""
        as_of_date = as_of_date or fields.Date.context_today(self)
        # disbursement_date : cohérent avec _compute_provision, qui renvoie 0 pour un crédit
        # 'active' non encore décaissé (découplage activation / décaissement).
        for loan in self.filtered(lambda l: l.state in ('active', 'defaulted') and l.disbursement_date):
            delta = loan.provision_amount - loan.provision_posted_amount
            if abs(delta) < 0.01:
                continue
            move = self.env['account.move'].with_context(
                default_loan_id=False,
                default_loan_line_id=False,
            ).create(loan._prepare_provision_move(delta, as_of_date))
            move.action_post()
            old_amount = loan.provision_posted_amount
            loan.write({'provision_posted_amount': loan.provision_amount})
            loan.message_post(body=_(
                'Provision ajustée au %(date)s : %(old)s → %(new)s (delta %(delta)s). Écriture : %(move)s'
            ) % {
                'date': as_of_date, 'old': '%.2f' % old_amount, 'new': '%.2f' % loan.provision_amount,
                'delta': '%.2f' % delta, 'move': move.name,
            })
        return True

    @api.model
    def cron_post_provisions(self):
        self.search([
            ('state', 'in', ('active', 'defaulted')), ('disbursement_date', '!=', False),
        ]).action_post_provisions()
        return True

    def action_open_payment_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Enregistrer remboursement'), 'res_model': 'microfinance.loan.payment.wizard',
            'view_mode': 'form', 'target': 'new', 'context': {'default_loan_id': self.id, 'default_journal_id': self.product_id.payment_journal_id.id}
        }

    def action_open_contract_signature_wizard(self):
        """Ouvre le wizard de dépôt du contrat signé (bouton header "Téléverser le contrat
        signé", invisible dès que contract_signature_date est renseigné - docs_dev/
        date_signature_contrat/). Remplace l'ancien upload direct (widget signed_contract_upload
        / binary natif) : le fichier et sa date de signature ne sont plus écrits que via ce
        wizard, en un seul write() verrouillé définitivement ensuite
        (_check_contract_signature_locked())."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Téléverser le contrat signé'),
            'res_model': 'microfinance.loan.contract.signature.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id},
        }

    def action_print_repayment_schedule(self):
        """Génère le calendrier de remboursement en PDF (rapport QWeb dédié, pas le reçu de
        décaissement) et le poste comme pièce jointe dans le chatter du crédit, sans jamais
        déclencher de téléchargement/ouverture côté navigateur - contrairement au bouton
        "Imprimer le reçu" (action_report_microfinance_loan_disbursement_receipt), qui reste un
        print action standard. Le PDF et son attachment restent rattachés à self.company_id (la
        société du crédit), jamais à self.env.company, pour ne pas fuiter un document entre
        agences si l'utilisateur courant a plusieurs sociétés sélectionnées."""
        self.ensure_one()
        report = self.env.ref('microfinance_loan_management.action_report_microfinance_loan_repayment_schedule')
        pdf_content, _report_format = report._render_qweb_pdf(report.report_name, self.ids)
        attachment = self.env['ir.attachment'].create({
            'name': _('Calendrier de remboursement - %s.pdf') % self.name,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'company_id': self.company_id.id,
            'mimetype': 'application/pdf',
        })
        self.message_post(
            body=_('Calendrier de remboursement généré.'),
            attachment_ids=[attachment.id],
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Calendrier de remboursement'),
                'message': _('Le document a été ajouté au fil de communication de ce crédit.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_print_carnet_remboursement(self):
        """Génère le carnet de remboursement en PDF et le poste en pièce jointe dans le
        chatter du crédit, sans jamais déclencher de téléchargement côté navigateur -
        même principe que action_print_repayment_schedule() et
        action_print_contrat_to_chatter(). Le PDF et son attachment restent rattachés à
        self.company_id (la société du crédit), jamais à self.env.company : un
        message_post(attachments=[...]) direct laisserait ir.attachment.company_id
        prendre la société ACTIVE de l'utilisateur courant par défaut (champ
        `default=lambda self: self.env.company` sur ir.attachment), ce qui fuiterait le
        document entre agences si l'utilisateur courant a plusieurs sociétés
        sélectionnées - même risque déjà écarté sur les deux méthodes soeurs."""
        self.ensure_one()
        report = self.env.ref('microfinance_loan_management.action_report_carnet_remboursement')
        pdf_content, _report_format = report._render_qweb_pdf(report.report_name, self.ids)
        attachment = self.env['ir.attachment'].create({
            'name': _('Carnet de remboursement - %s.pdf') % self.name,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'company_id': self.company_id.id,
            'mimetype': 'application/pdf',
        })
        self.message_post(body=_('Carnet de remboursement généré.'), attachment_ids=[attachment.id])
        # Le rafraîchissement du chatter est pris en charge côté client par
        # MicrofinanceLoanFormController.afterExecuteActionButton (MAIL:RELOAD-THREAD),
        # exactement comme pour action_print_repayment_schedule/action_print_contrat_to_chatter -
        # un seul mécanisme, sans recharger tout le formulaire (préserve une saisie en cours
        # ailleurs). Nécessite l'ajout de ce nom de bouton dans CHATTER_REFRESH_BUTTONS
        # (static/src/js/microfinance_loan_form_view.js).
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Carnet de remboursement'),
                'message': _('Le document a été ajouté au fil de communication de ce crédit.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Rapport « Contrat de Crédit » (report/report_contrat_credit.xml)
    # Reproduction du document Word de référence Contrat_de_Crédit_IS_02131.doc.
    # Décisions fonctionnelles : docs_dev/contrat_credit/AUDIT.md (validées Micka
    # le 2026-09-01). Toutes ces méthodes sont appelées uniquement depuis le
    # template QWeb et ne doivent jamais lever d'exception sur un champ vide.
    # ------------------------------------------------------------------
    def _format_contrat_date(self, date_value):
        """Date au format JJ/MM/AAAA (jamais ISO) pour le contrat de crédit.
        Chaîne vide si la date est absente, pour ne pas casser le rendu QWeb."""
        return date_value.strftime('%d/%m/%Y') if date_value else ''

    def _contrat_sorted_installments(self):
        """Échéances triées par date d'échéance puis séquence — ligne de délai de
        grâce éventuelle incluse (décision Micka : la « première échéance » du
        contrat n'exclut pas la ligne d'intérêt de grâce)."""
        self.ensure_one()
        return self.installment_ids.sorted(lambda inst: (inst.due_date or fields.Date.today(), inst.sequence))

    def get_contrat_guarantor(self):
        """Garant (mpiantoka) à faire figurer sur le contrat : porté par le dossier
        d'instruction (microfinance.loan.application.guarantor_partner_id), pas par
        la fiche client ni par le crédit — constaté sur les données réelles
        (docs_dev/contrat_credit/AUDIT.md §3.3, correction Micka). Un dossier
        d'instruction n'a qu'un seul garant (guarantor_count vaut 0 ou 1, pas de
        One2many). On prend application_ids[:1], même convention que
        action_view_applications()/_check_committee_octroi_accepted(). Retourne un
        res.partner vide si aucun garant — le template garde le bloc sous t-if."""
        self.ensure_one()
        return self.application_ids[:1].guarantor_partner_id

    def get_amount_in_words(self):
        """Montant emprunté (loan_amount) en toutes lettres françaises, capitalisé —
        paragraphe 1 du contrat. Arrondi à l'ariary entier (devise sans subdivision
        d'usage ici)."""
        self.ensure_one()
        if num2words is None:
            return ''
        words = num2words(int(round(self.loan_amount or 0.0)), lang='fr')
        return words[:1].upper() + words[1:]

    def get_total_interest(self):
        """Total des intérêts sur toute la durée du crédit. Réutilise interest_total
        (somme des interest_amount de l'échéancier, moteur interest-first déjà en
        place) — aucun calcul dupliqué. Repli sur la formule flat uniquement si
        l'échéancier n'existe pas encore (ne se produit pas à l'état 'approved')."""
        self.ensure_one()
        if self.installment_ids:
            return self.interest_total
        return self.loan_amount * (self.interest_rate / 100.0) * self._period_interest_factor() * self.term

    def get_monthly_interest_rate(self):
        """Taux d'intérêt mensuel = taux annuel du produit / 12 (décision Micka) —
        paragraphe 2 du contrat (« zana-bola X% isam-bolana »)."""
        self.ensure_one()
        return (self.interest_rate or 0.0) / 12.0

    def get_first_installment_date(self):
        """Date (JJ/MM/AAAA) de la première échéance de l'échéancier."""
        self.ensure_one()
        return self._format_contrat_date(self._contrat_sorted_installments()[:1].due_date)

    def get_last_installment_date(self):
        """Date (JJ/MM/AAAA) de la dernière échéance de l'échéancier."""
        self.ensure_one()
        return self._format_contrat_date(self._contrat_sorted_installments()[-1:].due_date)

    def get_loan_duration_days(self):
        """Durée du crédit en jours, calculée uniquement depuis l'échéancier (première
        échéance à dernière échéance) - indépendante du décaissement, disponible même
        avant disbursement_date. 0 si l'échéancier n'a pas encore été généré (jamais
        d'exception, cf. carnet de remboursement)."""
        self.ensure_one()
        installments = self._contrat_sorted_installments()
        if not installments:
            return 0
        return (installments[-1].due_date - installments[0].due_date).days

    def get_loan_rank_for_partner(self):
        """Rang de ce crédit dans l'historique du client (1 = premier), tous produits et
        toutes sociétés confondus (un client microfinance n'est rattaché qu'à une seule
        agence, cf. docs_dev/carnet_remboursement/AUDIT_compteur_findramana_faha.md). Ne
        compte que les crédits réellement engagés (mêmes états que le bouton "Imprimer le
        reçu"), sauf le dossier courant lui-même qui compte toujours dans son propre rang,
        quel que soit son état."""
        self.ensure_one()
        prior_engaged_count = self.search_count([
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', ('active', 'closed', 'defaulted', 'written_off')),
            ('id', '<', self.id),
        ])
        return prior_engaged_count + 1

    def get_guarantee_amount(self):
        """Épargne de garantie exigée, recalculée depuis le pourcentage du produit
        de crédit (guarantee_savings_percent) — décision Micka : toujours calculée,
        jamais figée. Équivaut à guarantee_savings_required lorsque
        microfinance_savings_management est installé ; getattr défensif pour rester
        fonctionnel si ce module ne l'est pas."""
        self.ensure_one()
        percent = getattr(self.product_id, 'guarantee_savings_percent', 0.0) or 0.0
        return (self.loan_amount or 0.0) * percent / 100.0

    def get_signature_date(self):
        """Date de signature du contrat = date d'approbation si renseignée, sinon
        date du jour à l'impression. Format JJ/MM/AAAA."""
        self.ensure_one()
        return self._format_contrat_date(self.approval_date or fields.Date.context_today(self))

    def action_print_contrat_to_chatter(self):
        """Génère le contrat de crédit en PDF et le poste en pièce jointe dans le
        chatter du crédit, sans jamais déclencher de téléchargement côté navigateur
        (décision Micka) — même principe que action_print_repayment_schedule(). Le
        PDF et son attachment restent rattachés à self.company_id (la société du
        crédit), jamais à self.env.company, pour ne pas fuiter un document entre
        agences si l'utilisateur courant a plusieurs sociétés sélectionnées."""
        self.ensure_one()
        report = self.env.ref('microfinance_loan_management.action_report_contrat_credit')
        pdf_content, _report_format = report._render_qweb_pdf(report.report_name, self.ids)
        attachment = self.env['ir.attachment'].create({
            'name': _('Contrat de crédit - %s.pdf') % self.name,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'company_id': self.company_id.id,
            'mimetype': 'application/pdf',
        })
        self.message_post(body=_('Contrat de crédit généré.'), attachment_ids=[attachment.id])
        # Le rafraîchissement du chatter est pris en charge côté client par
        # MicrofinanceLoanFormController.afterExecuteActionButton (MAIL:RELOAD-THREAD),
        # exactement comme pour action_print_repayment_schedule - un seul mécanisme,
        # sans recharger tout le formulaire (préserve une saisie en cours ailleurs).
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contrat de crédit'),
                'message': _('Le document a été ajouté au fil de communication de ce crédit.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _post_signed_contract_to_chatter(self):
        """Poste une copie du contrat signé fraîchement téléversé dans le fil de
        communication du dossier (comme « Contrat de crédit généré. » /
        « Calendrier de remboursement généré. »). Copie indépendante (res_field
        vide) : elle n'est pas soumise à la protection anti-suppression du champ
        signed_contract lui-même et survit à un remplacement ultérieur du champ."""
        self.ensure_one()
        field_att = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('res_field', '=', 'signed_contract'),
        ], limit=1)
        if not field_att:
            return
        chatter_att = self.env['ir.attachment'].create({
            'name': self.signed_contract_filename or (_('Contrat signé - %s') % self.name),
            'type': 'binary',
            'datas': field_att.datas,
            'res_model': self._name,
            'res_id': self.id,
            'company_id': self.company_id.id,
            'mimetype': field_att.mimetype or 'application/octet-stream',
        })
        self.message_post(body=_('Contrat signé téléversé.'), attachment_ids=[chatter_att.id])

    def action_view_installments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Échéances'), 'res_model': 'microfinance.loan.installment', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)]}

    def action_view_payments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Remboursements'), 'res_model': 'microfinance.loan.payment', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)]}

    def action_view_visits(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Visites'), 'res_model': 'microfinance.collection.visit', 'view_mode': 'tree,form,calendar', 'domain': [('loan_id', '=', self.id)]}

    def action_view_moves(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Écritures'), 'res_model': 'account.move', 'view_mode': 'tree,form', 'domain': [('microfinance_loan_id', '=', self.id)]}

    def action_view_applications(self):
        """Ouvre l'enquête déjà rattachée à ce crédit (loan_id), ou en crée une (rattachée
        directement via loan_id) s'il n'y en a encore aucune — le crédit et le dossier
        d'instruction se créent désormais indépendamment (cf. réversion du point d'entrée
        unique), ce bouton comble l'absence de tout mécanisme automatique de rattachement."""
        self.ensure_one()
        application = self.application_ids[:1]
        if not application:
            application = self.env['microfinance.loan.application'].create({
                'partner_id': self.partner_id.id,
                'loan_product_id': self.product_id.id,
                'company_id': self.company_id.id,
                'loan_id': self.id,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enquête'),
            'res_model': 'microfinance.loan.application',
            'view_mode': 'form',
            'res_id': application.id,
        }

    def action_view_scoring_lines(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Scoring'), 'res_model': 'microfinance.scoring.line', 'view_mode': 'tree,form', 'domain': [('loan_id', '=', self.id)], 'context': {'default_loan_id': self.id}}

    @api.model
    def cron_update_overdue_and_penalties(self):
        # Domaine étendu par rapport aux seules échéances pending/partial/overdue : inclut aussi
        # celles ayant un épisode de retard ouvert (arrears_onset_date posé, pas encore soldé côté
        # historique) pour que _sync_arrears_state() capture aussi les régularisations (passage à
        # 'paid') et pose arrears_cured_date. La portée de action_apply_penalty() reste identique
        # à avant (filtrée sur pending/partial/overdue juste après).
        # loan_id.disbursement_date renseigné : un crédit 'active' (ou avec un échéancier généré
        # à l'approbation) mais pas encore décaissé n'a AUCUN arriéré réel — ses échéances
        # pré-générées, ancrées sur approval_date puis recalées au décaissement, ne doivent ni
        # passer 'overdue', ni générer de pénalité, ni dégrader le score. Corrige aussi le bug
        # préexistant (le cron ne filtrait pas l'état du crédit), cf.
        # docs_dev/guichet_caisse/AUDIT_decaissement.md §2 / §8.5.
        installments = self.env['microfinance.loan.installment'].search([
            ('loan_id.disbursement_date', '!=', False),
            '|',
            ('state', 'in', ('pending', 'partial', 'overdue')),
            '&', ('arrears_onset_date', '!=', False), ('arrears_cured_date', '=', False),
        ])
        installments._sync_arrears_state()
        installments.filtered(lambda inst: inst.state in ('pending', 'partial', 'overdue')).action_apply_penalty()
        self.search([
            ('state', '=', 'active'), ('disbursement_date', '!=', False),
        ]).action_calculate_scoring(silent=True)
        self._refresh_max_days_overdue()
        return True

    def _refresh_max_days_overdue(self):
        """Rafraîchit le champ figé max_days_overdue à partir de _get_max_overdue_days(). Portée
        sur le portefeuille décaissé (active/defaulted) PLUS tout crédit ayant encore une valeur
        non nulle, pour la remettre à 0 après régularisation. Appelé par
        cron_update_overdue_and_penalties, juste après _sync_arrears_state() (donc installment.state
        est déjà à jour). Écrit uniquement les crédits dont la valeur change."""
        loans = self.search([
            '|',
            '&', ('state', 'in', ('active', 'defaulted')), ('disbursement_date', '!=', False),
            ('max_days_overdue', '!=', 0),
        ])
        for loan in loans:
            days = loan._get_max_overdue_days()
            if days != loan.max_days_overdue:
                loan.max_days_overdue = days
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'
    microfinance_loan_id = fields.Many2one('microfinance.loan', string='Crédit microfinance', index=True, copy=False)
    microfinance_payment_id = fields.Many2one('microfinance.loan.payment', string='Paiement microfinance', index=True, copy=False)
