/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";

export class MicrofinanceCaissePos extends Component {
    static TABS = [
        { id: "depot_epargne", label: "Dépôt épargne", icon: "fa-arrow-down", kind: "savings" },
        { id: "retrait_epargne", label: "Retrait épargne", icon: "fa-arrow-up", kind: "savings" },
        { id: "remboursement_credit", label: "Remboursement crédit", icon: "fa-arrow-down", kind: "loan" },
        { id: "decaissement_credit", label: "Décaissement crédit", icon: "fa-arrow-up", kind: "loan" },
        { id: "frais_dossier", label: "Frais de dossier", icon: "fa-file-text-o", kind: "fee" },
    ];

    // Le journal représente la banque/caisse, pas le moyen de paiement (clarification Micka,
    // Sous-lot D) : un journal 'cash' n'est réglé qu'en espèces (posé automatiquement, jamais
    // choisi manuellement, cf. selectDisbursementJournal) ; un journal 'bank' propose seulement
    // ce sous-choix entre les deux moyens de sortie pertinents pour une banque. Mêmes valeurs
    // que microfinance.loan.disbursement_payment_method — cf.
    // docs_dev/guichet_caisse/AUDIT_decaissement_journal_cheque.md §3/§7.
    static BANK_JOURNAL_PAYMENT_METHODS = [
        { id: "cheque", label: "Chèque" },
        { id: "bank_transfer", label: "Virement" },
    ];

    setup() {
        this.orm = useService("orm");
        this.company = useService("company");
        this.notification = useService("notification");
        this.tabs = MicrofinanceCaissePos.TABS;
        this.bankJournalPaymentMethods = MicrofinanceCaissePos.BANK_JOURNAL_PAYMENT_METHODS;
        this.state = useState({
            loadingSession: true,
            session: null,
            noSession: false,
            searchQuery: "",
            searching: false,
            client: null,
            loadingClient: false,
            activeTab: "depot_epargne",
            selectedAccountId: null,
            amountStr: "",
            ventilation: null,
            mouvements: [],
            submitting: false,
            // Bloc liste central. Onglet par défaut : "Décaissements en attente" (décision
            // actée). pendingDisbursements / pendingInstallments : listes brutes chargées une
            // fois par session (loadLists), filtrées à l'affichage par la barre de recherche
            // (getters filtered*). otherClients : résultats search_caisse_clients hors liste
            // filtrée (partie (b) de la recherche).
            centralTab: "decaissements",
            pendingDisbursements: [],
            pendingInstallments: [],
            pendingFees: [],
            otherClients: [],
            listLoading: false,
            // Flux "Décaissements en attente" : la ligne cliquée identifie déjà le crédit, on
            // affiche son calendrier d'échéance + le montant net figé (pas de sélection de
            // compte, pas de pavé numérique). disbursementFlow gouverne le rendu et le verrou.
            disbursementFlow: false,
            disbursementAmount: 0,
            // Choix fait au guichet juste avant la validation du décaissement (Sous-lot D,
            // docs_dev/guichet_caisse/AUDIT_decaissement_journal_cheque.md) : transmis à
            // register_operation, qui les écrit sur le prêt avant d'appeler
            // action_process_disbursement (qui ne prend lui-même aucun paramètre). Reset à
            // chaque nouvelle sélection de décaissement (selectDisbursement) et à la sortie du
            // flux (_resetDisbursementFlow). disbursementPaymentMethod n'est jamais choisi
            // directement : posé à "cash" automatiquement pour un journal 'cash', laissé vide
            // (sous-choix obligatoire) pour un journal 'bank' — cf. selectDisbursementJournal.
            disbursementJournalId: null,
            disbursementPaymentMethod: "",
            disbursementChequeNumber: "",
            disbursementChequeDate: "",
            // Journaux bank/cash de l'agence de la session, chargés une fois (loadLists) pour la
            // liste cliquable de choix du journal de décaissement. Le type de chacun pilote
            // l'affichage du sous-choix moyen de paiement (selectedDisbursementJournalType).
            availableJournals: [],
            // Calendrier d'échéance (lecture seule) du crédit sélectionné. Partagé par deux
            // onglets : "Décaissement crédit" (flux liste, montant figé) et "Remboursement
            // crédit" (sélection panneau, pavé numérique éditable). Alimenté par
            // _loadLoanSchedule (RPC get_loan_schedule, inchangé).
            loanSchedule: [],
            // Onglets "Dépôt épargne" / "Retrait épargne" : historique des transactions du
            // compte sélectionné (affiché sous le compte ; le pavé reste éditable).
            accountTransactions: [],
        });
        this._searchTimer = null;

        onMounted(async () => {
            await this.loadSession();
        });
        onWillUnmount(() => {
            if (this._searchTimer) {
                clearTimeout(this._searchTimer);
            }
        });
    }

    // --- Session ---

    async loadSession() {
        this.state.loadingSession = true;
        const sessions = await this.orm.searchRead(
            "microfinance.caisse.session",
            [["state", "=", "open"], ["company_id", "=", this.company.currentCompany.id]],
            ["id", "journal_id", "cashier_id", "date", "company_id", "currency_id", "opening_balance", "total_debit", "total_credit", "theoretical_balance"],
            { order: "date desc", limit: 1 }
        );
        if (sessions.length) {
            this.state.session = sessions[0];
            this.state.noSession = false;
            await this.loadMouvements();
            await this.loadLists();
        } else {
            this.state.session = null;
            this.state.noSession = true;
            this.state.mouvements = [];
        }
        this.state.loadingSession = false;
    }

    // Seul point d'entrée de l'ouverture de session depuis l'écran bloquant "Aucune session de
    // caisse ouverte" : appelle directement le wizard d'ouverture (qui trouve/crée la session
    // du jour et l'ouvre), sans détour par le formulaire backend générique de
    // microfinance.caisse.session (cf. AUDIT_session_zigzag §3).
    openSessionWizard() {
        this.env.services.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "microfinance.caisse.open.session.wizard",
                name: "Ouvrir une session de caisse",
                views: [[false, "form"]],
                target: "new",
                context: { default_company_id: this.company.currentCompany.id },
            },
            { onClose: () => this.loadSession() }
        );
    }

    // Bouton "Fermer la caisse" de l'en-tête (visible en permanence tant que la session est
    // ouverte, à l'emplacement de "Solde caisse : ...") : seul point d'entrée de la fermeture
    // (cf. AUDIT_session_zigzag §7 pt 2/3 - le bouton équivalent du formulaire backend
    // "Sessions de caisse" a été retiré). Réutilise action_open_close_wizard, déjà responsable
    // de construire l'action d'ouverture du wizard de comptage — un seul endroit qui sait
    // comment ouvrir la clôture, appelé soit par ce bouton, soit (garde d'état) par du code
    // serveur, jamais dupliqué côté client.
    async openCloseSessionWizard() {
        const action = await this.orm.call(
            "microfinance.caisse.session", "action_open_close_wizard", [this.state.session.id]
        );
        this.env.services.action.doAction(action, { onClose: () => this.loadSession() });
    }

    async loadMouvements() {
        if (!this.state.session) {
            return;
        }
        this.state.mouvements = await this.orm.searchRead(
            "microfinance.caisse.mouvement",
            [["session_id", "=", this.state.session.id]],
            ["id", "type", "partner_id", "amount", "interest_amount", "principal_amount", "penalty_amount", "create_date"],
            { order: "id desc" }
        );
    }

    // Listes du bloc central. Chargées une fois par session (onMounted via loadSession) et
    // rafraîchies après chaque opération validée (loadSession rappelé par submitOperation) :
    // l'élément traité disparaît alors de la liste. Changer d'onglet central ne recharge rien
    // (les deux listes sont déjà en mémoire ; l'onglet "epargne" n'a pas de données à
    // charger). company_id = celui de la session ouverte, jamais la société active de l'UI.
    async loadLists() {
        if (!this.state.session) {
            return;
        }
        const companyId = this.state.session.company_id[0];
        this.state.listLoading = true;
        try {
            const [disbursements, installments, fees, journals, companies] = await Promise.all([
                this.orm.call("microfinance.loan", "get_pending_disbursements", [companyId]),
                this.orm.call("microfinance.loan.installment", "get_pending_or_late", [companyId]),
                this.orm.call("microfinance.loan", "get_pending_fees", [companyId]),
                this.orm.searchRead(
                    "account.journal",
                    [["type", "in", ["bank", "cash"]], ["company_id", "=", companyId]],
                    ["id", "name", "code", "type"]
                ),
                this.orm.read("res.company", [companyId], ["disbursement_journal_ids"]),
            ]);
            this.state.pendingDisbursements = disbursements;
            this.state.pendingInstallments = installments;
            this.state.pendingFees = fees;
            // Restreint aux journaux explicitement autorisés au décaissement par l'agence
            // (company.disbursement_journal_ids) quand cette liste est configurée, en plus du
            // filtre type/société déjà appliqué côté serveur ci-dessus : évite de proposer des
            // journaux sans rapport avec le crédit (ex. Épargne, Banque-Épargne). Liste vide =
            // agence pas encore configurée -> aucun filtre supplémentaire (rétrocompatibilité).
            const allowedJournalIds = companies[0]?.disbursement_journal_ids || [];
            this.state.availableJournals = allowedJournalIds.length
                ? journals.filter((journal) => allowedJournalIds.includes(journal.id))
                : journals;
        } finally {
            this.state.listLoading = false;
        }
    }

    get ticketTotals() {
        const totals = { depot_epargne: 0, retrait_epargne: 0, remboursement_credit: 0, decaissement_credit: 0, frais_dossier: 0 };
        for (const m of this.state.mouvements) {
            if (m.type in totals) {
                totals[m.type] += m.amount;
            }
        }
        return totals;
    }

    // --- Recherche : double comportement ---
    // (a) filtre côté client la liste de l'onglet central actif (getters filtered*, aucun
    //     appel serveur) ; (b) en parallèle, cherche les clients de l'agence via
    //     search_caisse_clients (RPC existant, inchangé) et affiche ceux qui ne sont PAS
    //     déjà dans la liste filtrée, sous "Autres clients".

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        // Si un client est déjà sélectionné, taper dans la recherche = sortie implicite du
        // panneau de sélection : sans ça, la liste filtrée ET "Autres clients" (rendus
        // uniquement sous t-elif="!state.client") ne réapparaissent jamais et la saisie
        // semble sans effet (bug rapporté : recherche bloquée après sélection d'un client
        // sans compte). Même reset que le bouton "Liste" / le changement d'onglet.
        // clearClient() ne touche NI searchQuery (qu'on vient de poser) NI otherClients
        // (repeuplé par refreshOtherClients ci-dessous).
        if (this.state.client) {
            this.clearClient();
        }
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        // Partie (a) : purement réactive via les getters, rien à déclencher ici.
        // Partie (b) : débounce identique à l'existant (300 ms).
        this._searchTimer = setTimeout(() => this.refreshOtherClients(), 300);
    }

    async refreshOtherClients() {
        const query = this.state.searchQuery.trim();
        if (!this.state.session || query.length < 2) {
            this.state.otherClients = [];
            return;
        }
        this.state.searching = true;
        try {
            const results = await this.orm.call(
                "res.partner", "search_caisse_clients",
                [query, this.state.session.company_id[0]]
            );
            const listed = this.currentTabPartnerIds;
            this.state.otherClients = results.filter((r) => !listed.has(r.id));
        } finally {
            this.state.searching = false;
        }
    }

    _matchesQuery(row) {
        const query = this.state.searchQuery.trim().toLowerCase();
        if (!query) {
            return true;
        }
        return (row.partner_name || "").toLowerCase().includes(query)
            || (row.dossier || "").toLowerCase().includes(query);
    }

    get filteredDisbursements() {
        return this.state.pendingDisbursements.filter((r) => this._matchesQuery(r));
    }

    get filteredInstallments() {
        return this.state.pendingInstallments.filter((r) => this._matchesQuery(r));
    }

    get filteredFees() {
        return this.state.pendingFees.filter((r) => this._matchesQuery(r));
    }

    get currentTabPartnerIds() {
        const rows = this.state.centralTab === "echeances" ? this.filteredInstallments
            : this.state.centralTab === "decaissements" ? this.filteredDisbursements
            : this.state.centralTab === "frais" ? this.filteredFees
            : [];
        return new Set(rows.map((r) => r.partner_id));
    }

    async selectClient(partnerId) {
        this.state.loadingClient = true;
        this.state.otherClients = [];
        this.state.searchQuery = "";
        this.state.selectedAccountId = null;
        this.state.amountStr = "";
        this.state.ventilation = null;
        this.state.accountTransactions = [];
        this.state.loanSchedule = [];
        try {
            const summary = await this.orm.call(
                "res.partner", "get_client_accounts_summary",
                [partnerId, this.state.session.company_id[0]]
            );
            this.state.client = { id: partnerId, ...summary };
        } finally {
            this.state.loadingClient = false;
        }
    }

    clearClient() {
        this.state.client = null;
        this.state.selectedAccountId = null;
        this.state.amountStr = "";
        this.state.ventilation = null;
        this.state.accountTransactions = [];
        this.state.loanSchedule = [];
        this._resetDisbursementFlow();
    }

    _resetDisbursementFlow() {
        this.state.disbursementFlow = false;
        this.state.disbursementAmount = 0;
        this.state.disbursementJournalId = null;
        this.state.disbursementPaymentMethod = "";
        this.state.disbursementChequeNumber = "";
        this.state.disbursementChequeDate = "";
    }

    // Calendrier d'échéance d'un crédit (get_loan_schedule, lecture seule, aucun impact
    // comptable). Factorisé pour être appelé par le décaissement (selectDisbursement) comme
    // par le remboursement (selectAccount).
    async _loadLoanSchedule(loanId) {
        return this.orm.call(
            "microfinance.loan.installment", "get_loan_schedule",
            [loanId, this.state.session.company_id[0]]
        );
    }

    // Clic sur une ligne de l'onglet "Décaissements en attente" : la ligne identifie déjà
    // précisément le crédit à décaisser (aucun choix à faire). On garde le fil client
    // existant (selectClient), puis on cible directement ce crédit, on pré-remplit le montant
    // net (déjà dans la ligne — aucun appel serveur pour ça) et on charge son échéancier.
    async selectDisbursement(row) {
        this.state.activeTab = "decaissement_credit";
        await this.selectClient(row.partner_id);
        this.state.selectedAccountId = row.id;
        this.state.disbursementAmount = row.amount;
        this.state.amountStr = String(row.amount);
        this.state.disbursementFlow = true;
        // Choix journal / moyen de paiement / chèque : jamais reportés d'un crédit à l'autre.
        this.state.disbursementJournalId = null;
        this.state.disbursementPaymentMethod = "";
        this.state.disbursementChequeNumber = "";
        this.state.disbursementChequeDate = "";
        this.state.loanSchedule = await this._loadLoanSchedule(row.id);
    }

    // Journal représente la banque/caisse (clarification Micka) : le choix du journal détermine
    // le moyen de paiement, pas l'inverse. Un journal 'cash' pose "Espèces" automatiquement (rien
    // d'autre à choisir) ; un journal 'bank' laisse le moyen de paiement à vide pour forcer le
    // sous-choix explicite Chèque/Virement (cf. template, bloc affiché seulement si
    // selectedDisbursementJournalType === 'bank').
    selectDisbursementJournal(journalId) {
        this.state.disbursementJournalId = journalId;
        const journal = this.state.availableJournals.find((j) => j.id === journalId);
        this.state.disbursementPaymentMethod = journal && journal.type === "cash" ? "cash" : "";
        this.state.disbursementChequeNumber = "";
        this.state.disbursementChequeDate = "";
    }

    get selectedDisbursementJournalType() {
        const journal = this.state.availableJournals.find((j) => j.id === this.state.disbursementJournalId);
        return journal ? journal.type : null;
    }

    selectDisbursementPaymentMethod(method) {
        this.state.disbursementPaymentMethod = method;
        if (method !== "cheque") {
            this.state.disbursementChequeNumber = "";
            this.state.disbursementChequeDate = "";
        }
    }

    onDisbursementChequeNumberInput(ev) {
        this.state.disbursementChequeNumber = ev.target.value;
    }

    onDisbursementChequeDateInput(ev) {
        this.state.disbursementChequeDate = ev.target.value;
    }

    // --- Onglet opération ---

    setActiveTab(tabId) {
        // Re-clic sur l'onglet déjà actif : no-op, aucun reset (non-régression AUDIT §6.4).
        if (tabId === this.state.activeTab) {
            return;
        }
        this.state.activeTab = tabId;
        // Changement réel d'opération : on revient à la liste centrale du nouvel onglet
        // (vide le client sélectionné, comme le bouton « Liste »), pas seulement le montant.
        this.state.client = null;
        this.state.selectedAccountId = null;
        this.state.amountStr = "";
        this.state.ventilation = null;
        this.state.accountTransactions = [];
        this.state.loanSchedule = [];
        this._resetDisbursementFlow();
    }

    // Onglet du bloc liste central. Distinct de setActiveTab (onglet d'opération) : ne touche
    // ni au client sélectionné, ni au montant. Ne recharge pas les listes (déjà en mémoire) ;
    // ré-évalue seulement "Autres clients" si une recherche est en cours, car la base de
    // dédoublonnage (liste de l'onglet actif) change.
    setCentralTab(tabId) {
        this.state.centralTab = tabId;
        if (this.state.searchQuery.trim().length >= 2) {
            this.refreshOtherClients();
        }
    }

    get activeTabKind() {
        return this.tabs.find((t) => t.id === this.state.activeTab)?.kind;
    }

    get actionableSavingsAccounts() {
        return this.state.client?.savings_accounts || [];
    }

    get actionableLoans() {
        const loans = this.state.client?.loans || [];
        if (this.state.activeTab === "decaissement_credit") {
            return loans.filter((l) => l.state === "approved");
        }
        if (this.state.activeTab === "remboursement_credit") {
            return loans.filter((l) => l.state === "active" || l.state === "defaulted");
        }
        if (this.state.activeTab === "frais_dossier") {
            // Frais envoyés en caisse et pas encore encaissés (cf. get_pending_fees serveur).
            return loans.filter((l) => l.fee_sent_to_cashier && !l.fee_paid);
        }
        return [];
    }

    // Kinds dont la sélection se fait dans la liste "Crédits" du panneau client.
    get isLoanSelectionKind() {
        return this.activeTabKind === "loan" || this.activeTabKind === "fee";
    }

    // Crédits listés dans le panneau client : sur l'onglet frais, uniquement ceux dont les
    // frais sont à encaisser ; sinon la liste complète renvoyée par le serveur (comportement
    // 1.4 inchangé pour les onglets crédit/épargne).
    get displayedLoans() {
        return this.activeTabKind === "fee" ? this.actionableLoans : (this.state.client?.loans || []);
    }

    async selectAccount(id) {
        this.state.selectedAccountId = id;
        if (this.state.activeTab === "remboursement_credit") {
            this.updateVentilationPreview();
            // Même calendrier d'échéance que le décaissement, en lecture seule. N'affecte ni
            // le pavé numérique (qui reste éditable : remboursement partiel), ni la
            // ventilation ci-dessus.
            this.state.loanSchedule = await this._loadLoanSchedule(id);
        } else {
            this.state.loanSchedule = [];
        }
        // Onglets épargne : historique des transactions du compte sélectionné (info en
        // lecture, le pavé reste éditable). Réutilise deposit_amount / withdrawal_amount déjà
        // calculés côté modèle (colonnes Dépôt / Retrait de la fiche compte).
        if (this.activeTabKind === "savings") {
            this.state.accountTransactions = await this.orm.call(
                "microfinance.savings.account", "get_account_transactions",
                [id, this.state.session.company_id[0]]
            );
        } else {
            this.state.accountTransactions = [];
        }
    }

    // Montant figé des frais du crédit sélectionné (onglet frais_dossier) : jamais saisi au
    // pavé, non éditable.
    get selectedFeeAmount() {
        if (this.state.activeTab !== "frais_dossier" || !this.state.selectedAccountId) {
            return 0.0;
        }
        const loan = (this.state.client?.loans || []).find((l) => l.id === this.state.selectedAccountId);
        return loan ? loan.fee_amount_due : 0.0;
    }

    // Montant affiché / soumis : frais figés sur l'onglet frais_dossier, montant net figé sur
    // le flux "Décaissements en attente", saisie pavé ailleurs.
    get effectiveAmount() {
        if (this.state.activeTab === "frais_dossier") {
            return this.selectedFeeAmount;
        }
        if (this.state.disbursementFlow) {
            return this.state.disbursementAmount;
        }
        return this.amount;
    }

    get numpadDisabled() {
        return this.state.activeTab === "frais_dossier" || this.state.disbursementFlow;
    }

    // Libellé de l'aide affichée sous le montant quand le pavé est verrouillé.
    get numpadHint() {
        if (this.state.disbursementFlow) {
            return "Montant figé : montant net à décaisser du crédit sélectionné.";
        }
        if (this.state.activeTab === "frais_dossier") {
            return "Montant figé : frais de dossier du crédit sélectionné.";
        }
        return "";
    }

    // --- Pavé numérique ---

    pressDigit(digit) {
        if (this.state.amountStr.replace(".", "").length >= 12) {
            return;
        }
        this.state.amountStr += digit;
        this.updateVentilationPreview();
    }

    pressDecimal() {
        if (this.state.amountStr.includes(".")) {
            return;
        }
        this.state.amountStr += this.state.amountStr ? "." : "0.";
        this.updateVentilationPreview();
    }

    pressBackspace() {
        this.state.amountStr = this.state.amountStr.slice(0, -1);
        this.updateVentilationPreview();
    }

    pressClear() {
        this.state.amountStr = "";
        this.state.ventilation = null;
    }

    get amount() {
        return parseFloat(this.state.amountStr) || 0.0;
    }

    async updateVentilationPreview() {
        if (this.state.activeTab !== "remboursement_credit" || !this.state.selectedAccountId || this.amount <= 0) {
            this.state.ventilation = null;
            return;
        }
        this.state.ventilation = await this.orm.call(
            "microfinance.loan.payment", "preview_repayment_allocation",
            [this.state.selectedAccountId, this.amount]
        );
    }

    // --- Validation ---

    get canSubmit() {
        if (!this.state.session || !this.state.client || this.state.submitting) {
            return false;
        }
        if (!this.state.selectedAccountId) {
            return false;
        }
        // frais_dossier : montant figé (fee_amount_due), pas de saisie pavé requise.
        if (this.state.activeTab === "frais_dossier") {
            return this.selectedFeeAmount > 0;
        }
        // décaissement depuis la liste : montant net figé (pas de saisie pavé requise), mais
        // journal obligatoire ; pour un journal 'bank', le sous-choix Chèque/Virement est
        // également obligatoire (disbursementPaymentMethod reste vide tant qu'il n'est pas fait,
        // cf. selectDisbursementJournal) et, si "Chèque", numéro + date obligatoires
        // (docs_dev/guichet_caisse/AUDIT_decaissement_journal_cheque.md §7 : ne jamais poster un
        // décaissement chèque sans ces deux informations).
        if (this.state.disbursementFlow) {
            if (!(this.state.disbursementAmount > 0) || !this.state.disbursementJournalId) {
                return false;
            }
            if (!this.state.disbursementPaymentMethod) {
                return false;
            }
            if (this.state.disbursementPaymentMethod === "cheque"
                && (!this.state.disbursementChequeNumber.trim() || !this.state.disbursementChequeDate)) {
                return false;
            }
            return true;
        }
        return this.amount > 0;
    }

    async submitOperation() {
        if (!this.canSubmit) {
            return;
        }
        this.state.submitting = true;
        const tab = this.state.activeTab;
        const isLoanOp = tab === "remboursement_credit" || tab === "decaissement_credit" || tab === "frais_dossier";
        try {
            // Remboursement crédit : avant toute comptabilisation, demander au serveur si la
            // situation impose une confirmation (cascade sur plusieurs échéances en retard,
            // ou surplus une fois le dû immédiat soldé -> anticiper / verser en épargne).
            // Si oui, on ouvre l'assistant renvoyé ; il comptabilise lui-même
            // (register_repayment_confirmed) et son onClose rafraîchit le guichet.
            // register_operation N'EST PAS appelé dans ce cas.
            if (tab === "remboursement_credit") {
                const flow = await this.orm.call(
                    "microfinance.caisse.mouvement", "get_repayment_flow_action",
                    [this.state.session.id, this.state.selectedAccountId, this.effectiveAmount]
                );
                if (flow && flow.type === "ir.actions.act_window") {
                    const clientId = this.state.client?.id;
                    this.env.services.action.doAction(flow, {
                        onClose: () => {
                            this.state.amountStr = "";
                            this.state.ventilation = null;
                            this.state.selectedAccountId = null;
                            this.loadSession();
                            if (clientId) {
                                this.selectClient(clientId);
                            }
                        },
                    });
                    return;
                }
            }
            await this.orm.call("microfinance.caisse.mouvement", "register_operation", [
                this.state.session.id,
                tab,
                this.state.client.id,
                this.effectiveAmount,
                isLoanOp ? false : this.state.selectedAccountId,
                isLoanOp ? this.state.selectedAccountId : false,
            ], {
                // Sans effet hors décaissement_credit (register_operation ne les lit que dans
                // cette branche) : toujours transmis pour ne pas complexifier cet appel selon
                // l'onglet actif.
                journal_id: this.state.disbursementFlow ? this.state.disbursementJournalId : false,
                payment_method: this.state.disbursementFlow ? this.state.disbursementPaymentMethod : "cash",
                cheque_number: this.state.disbursementFlow && this.state.disbursementPaymentMethod === "cheque"
                    ? this.state.disbursementChequeNumber : false,
                cheque_date: this.state.disbursementFlow && this.state.disbursementPaymentMethod === "cheque"
                    ? this.state.disbursementChequeDate : false,
            });
            this.notification.add("Opération enregistrée.", { type: "success" });
            this.state.amountStr = "";
            this.state.ventilation = null;
            this.state.selectedAccountId = null;
            if (this.state.disbursementFlow) {
                // Décaissement one-shot : le crédit disparaît de la liste, retour à la liste.
                this.clearClient();
                await this.loadSession();
            } else {
                await Promise.all([
                    this.loadSession(),
                    this.selectClient(this.state.client.id),
                ]);
            }
        } catch (error) {
            this.notification.add(error.data?.message || "L'opération a échoué.", { type: "danger" });
        } finally {
            this.state.submitting = false;
        }
    }

    // --- Formatage ---

    formatMoney(value) {
        const currency = this.state.session?.currency_id?.[1] || "";
        return `${new Intl.NumberFormat().format(Math.round(value || 0))} ${currency}`.trim();
    }

    formatDateTime(value) {
        if (!value) {
            return "";
        }
        return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value.replace(" ", "T")));
    }

    typeLabel(type) {
        return this.tabs.find((t) => t.id === type)?.label || type;
    }
}

MicrofinanceCaissePos.template = "microfinance_loan_management.MicrofinanceCaissePos";
registry.category("actions").add("microfinance_caisse_pos", MicrofinanceCaissePos);
