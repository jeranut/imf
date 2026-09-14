/** @odoo-module **/

/*
 * Extension du guichet caisse (microfinance_loan_management) pour le transfert de
 * remboursement inter-agences. Vit ICI (pas dans le module crédit) : dépendance à sens
 * unique préservée, l'ensemble reste désinstallable d'un bloc.
 *
 * On NE quitte JAMAIS l'écran guichet. Deux points d'accroche seulement :
 *
 *  1. POINT D'ENTRÉE d'un nouveau transfert = la barre de recherche principale.
 *     refreshOtherClients() est patché pour interroger AUSSI
 *     res.partner.search_other_agency_clients et fusionner le résultat dans la
 *     section « Autres clients » (badge agence). Cliquer une telle ligne ->
 *     mini-sélecteur du crédit -> assistant de confirmation (register_transfert).
 *     search_caisse_clients et le flux des clients de l'agence courante sont
 *     inchangés.
 *
 *  2. L'onglet central « Transfert » (5e onglet, à côté de Décaissements en
 *     attente / Échéances du jour / Épargne en attente / Frais) sert UNIQUEMENT à
 *     la gestion des lots : regrouper les transferts encaissés, les remettre au
 *     coursier, valider les transferts reçus.
 */
import { patch } from "@web/core/utils/patch";
// Import inter-module : force le chargeur de modules Odoo à évaluer d'abord le
// fichier du guichet (microfinance_loan_management) — la classe doit exister avant
// ce patch.
import { MicrofinanceCaissePos } from "@microfinance_loan_management/js/microfinance_caisse_pos";

patch(MicrofinanceCaissePos.prototype, {
    setup() {
        super.setup();
        // Sous-arbre d'état isolé — n'altère aucun champ d'état existant.
        this.state.transfert = {
            view: "source", // "source" | "destination"
            loading: false,
            pending: [],
            draftLots: [],
            incoming: [],
            selectedPendingIds: [],
            coursierId: null,
            coursiers: [],
            picked: null, // client d'une autre agence choisi dans « Autres clients »
            pickedLoans: [],
            working: false,
        };
    },

    // Onglet central : à l'activation de « transfert », charge les listes de lots.
    setCentralTab(tabId) {
        super.setCentralTab(tabId);
        if (tabId === "transfert") {
            this._loadTransfertData();
        }
    },

    // Barre de recherche principale : on garde la recherche mono-agence
    // (search_caisse_clients, partie (b) de l'existant) ET on y ajoute les clients
    // d'une AUTRE agence (search_other_agency_clients, sudo ciblé, retour minimal).
    // Les deux jeux sont fusionnés dans state.otherClients ; les lignes cross-agence
    // portent is_other_agency=true (badge + flux transfert au clic).
    async refreshOtherClients() {
        const query = this.state.searchQuery.trim();
        // Toute nouvelle frappe annule un éventuel client cross-agence en cours de choix.
        this.state.transfert.picked = null;
        this.state.transfert.pickedLoans = [];
        if (!this.state.session || query.length < 2) {
            this.state.otherClients = [];
            return;
        }
        this.state.searching = true;
        try {
            const companyId = this.state.session.company_id[0];
            const [local, other] = await Promise.all([
                this.orm.call("res.partner", "search_caisse_clients", [query, companyId]),
                this.orm.call("res.partner", "search_other_agency_clients", [query, companyId]),
            ]);
            const listed = this.currentTabPartnerIds;
            const localRows = local
                .filter((r) => !listed.has(r.id))
                .map((r) => ({ ...r, is_other_agency: false }));
            const otherRows = other.map((r) => ({ ...r, is_other_agency: true }));
            this.state.otherClients = [...localRows, ...otherRows];
        } finally {
            this.state.searching = false;
        }
    },

    // Clic sur une ligne « Autres clients ».
    async selectOtherClient(result) {
        if (!result.is_other_agency) {
            // Client de l'agence courante : comportement d'origine inchangé.
            return this.selectClient(result.id);
        }
        // Client d'une autre agence -> flux transfert (pas selectClient : ses comptes
        // sont dans une autre société, invisibles au caissier).
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        const t = this.state.transfert;
        t.picked = result;
        t.pickedLoans = await this.orm.call(
            "microfinance.transfert.remboursement",
            "get_other_agency_client_loans",
            [result.id]
        );
    },

    clearTransfertPick() {
        const t = this.state.transfert;
        t.picked = null;
        t.pickedLoans = [];
    },

    async startTransfert(loan) {
        const action = await this.orm.call(
            "microfinance.transfert.remboursement",
            "get_transfert_confirm_action",
            [this.state.session.id, loan.id, 0]
        );
        this.env.services.action.doAction(action, {
            onClose: () => {
                const t = this.state.transfert;
                t.picked = null;
                t.pickedLoans = [];
                this.state.searchQuery = "";
                this.state.otherClients = [];
                this.loadSession();
                if (this.state.centralTab === "transfert") {
                    this._loadTransfertData();
                }
            },
        });
    },

    // --- Onglet central « Transfert » : gestion des lots ---
    async _loadTransfertData() {
        const t = this.state.transfert;
        if (!this.state.session) {
            return;
        }
        t.loading = true;
        try {
            const companyId = this.state.session.company_id[0];
            if (t.view === "source") {
                const data = await this.orm.call(
                    "microfinance.transfert.remboursement",
                    "get_transfert_source_data",
                    [this.state.session.id]
                );
                t.pending = data.pending;
                t.draftLots = data.draft_lots;
                t.selectedPendingIds = [];
                if (!t.coursiers.length) {
                    // Liste large de partenaires candidats coursier (agence courante ou
                    // partenaires partagés). Le domaine « nature du coursier » n'est pas
                    // tranché (cf. audit §5) — affinage possible ultérieurement.
                    t.coursiers = await this.orm.searchRead(
                        "res.partner",
                        ["|", ["company_id", "=", companyId], ["company_id", "=", false]],
                        ["id", "name"],
                        { limit: 80, order: "name" }
                    );
                }
            } else {
                const data = await this.orm.call(
                    "microfinance.transfert.remboursement",
                    "get_transfert_destination_data",
                    [this.state.session.id]
                );
                t.incoming = data.incoming;
            }
        } finally {
            t.loading = false;
        }
    },

    setTransfertView(view) {
        this.state.transfert.view = view;
        this._loadTransfertData();
    },

    togglePendingSelected(id) {
        const sel = this.state.transfert.selectedPendingIds;
        const i = sel.indexOf(id);
        if (i >= 0) {
            sel.splice(i, 1);
        } else {
            sel.push(id);
        }
    },

    isPendingSelected(id) {
        return this.state.transfert.selectedPendingIds.includes(id);
    },

    async createLot() {
        const t = this.state.transfert;
        if (t.working) {
            return;
        }
        if (!t.selectedPendingIds.length) {
            this.notification.add("Sélectionnez au moins un transfert.", { type: "warning" });
            return;
        }
        if (!t.coursierId) {
            this.notification.add("Sélectionnez le coursier.", { type: "warning" });
            return;
        }
        t.working = true;
        try {
            await this.orm.call(
                "microfinance.transfert.remboursement",
                "action_create_lot",
                [this.state.session.id, t.selectedPendingIds, Number(t.coursierId)]
            );
            this.notification.add("Lot créé.", { type: "success" });
            await this._loadTransfertData();
        } catch (error) {
            this.notification.add(error.data?.message || "Échec de la création du lot.", {
                type: "danger",
            });
        } finally {
            t.working = false;
        }
    },

    async validateLot(lotId) {
        const t = this.state.transfert;
        if (t.working) {
            return;
        }
        t.working = true;
        try {
            const action = await this.orm.call(
                "microfinance.transfert.remboursement",
                "validate_lot",
                [lotId]
            );
            this.notification.add("Lot remis au coursier.", { type: "success" });
            await Promise.all([this._loadTransfertData(), this.loadSession()]);
            if (action) {
                this.env.services.action.doAction(action);
            }
        } catch (error) {
            this.notification.add(error.data?.message || "Échec de la validation du lot.", {
                type: "danger",
            });
        } finally {
            t.working = false;
        }
    },

    async validateIncoming(transfertId) {
        const t = this.state.transfert;
        if (t.working) {
            return;
        }
        t.working = true;
        try {
            await this.orm.call(
                "microfinance.transfert.remboursement",
                "validate_transfert_destination",
                [transfertId, this.state.session.id]
            );
            this.notification.add(
                "Transfert validé — remboursement du crédit comptabilisé.",
                { type: "success" }
            );
            await Promise.all([this._loadTransfertData(), this.loadSession()]);
        } catch (error) {
            this.notification.add(error.data?.message || "Échec de la validation.", {
                type: "danger",
            });
        } finally {
            t.working = false;
        }
    },
});
