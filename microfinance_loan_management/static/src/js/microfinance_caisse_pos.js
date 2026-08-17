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
    ];

    setup() {
        this.orm = useService("orm");
        this.company = useService("company");
        this.notification = useService("notification");
        this.tabs = MicrofinanceCaissePos.TABS;
        this.state = useState({
            loadingSession: true,
            session: null,
            noSession: false,
            searchQuery: "",
            searchResults: [],
            searching: false,
            client: null,
            loadingClient: false,
            activeTab: "depot_epargne",
            selectedAccountId: null,
            amountStr: "",
            ventilation: null,
            mouvements: [],
            submitting: false,
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
            ["id", "journal_id", "cashier_id", "date", "company_id", "currency_id", "opening_balance", "total_debit", "total_credit", "closing_balance"],
            { order: "date desc", limit: 1 }
        );
        if (sessions.length) {
            this.state.session = sessions[0];
            this.state.noSession = false;
            await this.loadMouvements();
        } else {
            this.state.session = null;
            this.state.noSession = true;
            this.state.mouvements = [];
        }
        this.state.loadingSession = false;
    }

    openSessionForm() {
        this.env.services.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "microfinance.caisse.session",
                name: "Ouvrir une session de caisse",
                views: [[false, "form"]],
                target: "new",
                context: { default_company_id: this.company.currentCompany.id },
            },
            { onClose: () => this.loadSession() }
        );
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

    get ticketTotals() {
        const totals = { depot_epargne: 0, retrait_epargne: 0, remboursement_credit: 0, decaissement_credit: 0 };
        for (const m of this.state.mouvements) {
            if (m.type in totals) {
                totals[m.type] += m.amount;
            }
        }
        return totals;
    }

    // --- Recherche client ---

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        if (!this.state.searchQuery) {
            this.state.searchResults = [];
            return;
        }
        this._searchTimer = setTimeout(() => this.performSearch(), 300);
    }

    async performSearch() {
        this.state.searching = true;
        try {
            this.state.searchResults = await this.orm.call(
                "res.partner", "search_caisse_clients",
                [this.state.searchQuery, this.state.session.company_id[0]]
            );
        } finally {
            this.state.searching = false;
        }
    }

    async selectClient(partnerId) {
        this.state.loadingClient = true;
        this.state.searchResults = [];
        this.state.searchQuery = "";
        this.state.selectedAccountId = null;
        this.state.amountStr = "";
        this.state.ventilation = null;
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
    }

    // --- Onglet opération ---

    setActiveTab(tabId) {
        this.state.activeTab = tabId;
        this.state.selectedAccountId = null;
        this.state.amountStr = "";
        this.state.ventilation = null;
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
        return [];
    }

    selectAccount(id) {
        this.state.selectedAccountId = id;
        if (this.state.activeTab === "remboursement_credit") {
            this.updateVentilationPreview();
        }
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
        if (this.amount <= 0 || !this.state.selectedAccountId) {
            return false;
        }
        return true;
    }

    async submitOperation() {
        if (!this.canSubmit) {
            return;
        }
        this.state.submitting = true;
        const tab = this.state.activeTab;
        const isLoanOp = tab === "remboursement_credit" || tab === "decaissement_credit";
        try {
            await this.orm.call("microfinance.caisse.mouvement", "register_operation", [
                this.state.session.id,
                tab,
                this.state.client.id,
                this.amount,
                isLoanOp ? false : this.state.selectedAccountId,
                isLoanOp ? this.state.selectedAccountId : false,
            ]);
            this.notification.add("Opération enregistrée.", { type: "success" });
            this.state.amountStr = "";
            this.state.ventilation = null;
            this.state.selectedAccountId = null;
            await Promise.all([
                this.loadSession(),
                this.selectClient(this.state.client.id),
            ]);
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
