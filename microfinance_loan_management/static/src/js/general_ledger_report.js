/** @odoo-module **/
// Grand livre interactif : étend le composant du Journal de banque (base_accounting_kit.journal_ledger_report) pour
// garder la même barre de filtres, les mêmes menus déroulants, la même bannière et les mêmes exports. Seuls changent les
// données (un compte par ligne, lignes d'écriture chargées à la dépliage par pages) et quelques filtres propres.

import { registry } from "@web/core/registry";

const actions = registry.category("actions");
const JournalLedgerReport = actions.get("base_accounting_kit.journal_ledger_report");

class GeneralLedgerReport extends JournalLedgerReport {
    setup() {
        super.setup();
        Object.assign(this.state, {
            title: "Grand livre",
            periodPreset: "year",
            dateFrom: this.toISODate(new Date(new Date().getFullYear(), 0, 1)),
            dateTo: this.toISODate(new Date(new Date().getFullYear(), 11, 31)),
            displayAccount: "all",
            initBalance: true,
            sortby: "sort_date",
            pageSize: 80,
            accountLines: {},
            accountId: false,
        });
        // Ouverture depuis un autre écran (Balance générale) : filtres de départ transmis par l'action
        const initial = ((this.props.action || {}).params || {}).initial;
        if (initial) {
            Object.assign(this.state, initial);
        }
    }

    // ------------------------------------------------------------------ filtres propres
    displayAccountLabel() {
        return {
            all: "Tous les comptes",
            movement: "Avec mouvements",
            not_zero: "Solde différent de 0",
        }[this.state.displayAccount];
    }

    sortLabel() {
        return this.state.sortby === "sort_date" ? "Tri : date" : "Tri : journal et tiers";
    }

    async setDisplayAccount(value) {
        this.state.displayAccount = value;
        this.closeDropdown();
        await this.loadReport();
    }

    async setSortby(value) {
        this.state.sortby = value;
        this.closeDropdown();
        await this.loadReport();
    }

    async toggleInitBalance() {
        this.state.initBalance = !this.state.initBalance;
        await this.loadReport();
    }

    // Format « En .Ar » comme les autres rapports
    formatAmount(value) {
        const format = this.state.currencyFormat;
        const divisor = format === "kar" ? 1000 : format === "mar" ? 1000000 : 1;
        const digits = format === "full" ? 2 : 0;
        return (Number(value || 0) / divisor).toLocaleString("fr-FR", {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }

    currencyButtonLabel() {
        return { full: "En .Ar", ar: "En Ar", kar: "En KAr", mar: "En MAr" }[this.state.currencyFormat] || "En .Ar";
    }

    setCurrencyFormat(format) {
        this.state.currencyFormat = format;
        this.closeDropdown();
    }

    // ------------------------------------------------------------------ chargement
    filterParams() {
        return {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
            target_move: this.state.targetMove,
            journal_ids: this.state.selectedJournalIds,
            company_id: this.companyService.currentCompany.id,
            sortby: this.state.sortby,
            init_balance: this.state.initBalance,
        };
    }

    async loadReport() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await this.rpc("/microfinance/general_ledger/data", {
                ...this.filterParams(),
                search: this.state.search || false,
                display_account: this.state.displayAccount,
                account_id: this.state.accountId || false,
            });
            if (!result.success) {
                this.state.error = result.error || "Erreur de chargement.";
                this.state.reportData = null;
            } else {
                this.state.title = result.title;
                this.state.currency = result.currency || "";
                this.state.companyName = result.company_name || "";
                this.state.targetMoveLabel = result.target_move_label || "";
                this.state.journalsLabel = result.journals_label || "Tous les journaux";
                this.state.journals = result.journals || [];
                this.state.selectedJournalIds = result.selected_journal_ids || [];
                this.state.unpostedEntriesExist = result.unposted_entries_exist || false;
                this.state.pageSize = result.page_size || 80;
                this.state.reportData = result.data;
                this.state.unfolded = {};
                this.state.accountLines = {}; // les filtres ont changé : lignes à recharger au dépliage
            }
        } catch (error) {
            this.state.error = "Impossible de charger le grand livre.";
            this.state.reportData = null;
        }
        this.state.loading = false;
    }

    async toggleAccount(account) {
        const key = `account_${account.id}`;
        this.toggleFold(key);
        if (!this.isFolded(key) && !this.state.accountLines[account.id] && account.count) {
            await this.loadMore(account);
        }
    }

    async loadMore(account) {
        const current = this.state.accountLines[account.id] || { rows: [], hasMore: true, loading: false };
        if (current.loading) return;
        this.state.accountLines[account.id] = { ...current, loading: true };
        try {
            const page = await this.rpc("/microfinance/general_ledger/lines", {
                ...this.filterParams(),
                account_id: account.id,
                offset: current.rows.length,
            });
            this.state.accountLines[account.id] = {
                rows: current.rows.concat(page.rows),
                hasMore: page.has_more,
                total: page.total_rows,
                loading: false,
            };
        } catch (error) {
            this.state.accountLines[account.id] = { ...current, loading: false, error: true };
        }
    }

    lines(account) {
        return this.state.accountLines[account.id] || { rows: [], hasMore: false, loading: false };
    }

    accounts() {
        return (this.state.reportData && this.state.reportData.accounts) || [];
    }

    // ------------------------------------------------------------------ exports
    exportParams() {
        return {
            ...this.filterParams(),
            journal_ids: this.state.selectedJournalIds.join(","),
            search: this.state.search || "",
            display_account: this.state.displayAccount,
            account_id: this.state.accountId || "",
        };
    }

    printPdf() {
        window.open(this._exportUrl("/microfinance/general_ledger/pdf"), "_blank");
    }

    exportXlsx() {
        window.open(this._exportUrl("/microfinance/general_ledger/xlsx"), "_blank");
    }

    async onSearchInput(ev) {
        this.state.accountId = false; // une recherche libre remplace le filtre de compte venu de l'extérieur
        return super.onSearchInput(ev);
    }

    onSearchPlaceholder() {
        return "Code ou libellé du compte...";
    }
}

GeneralLedgerReport.template = "microfinance_loan_management.GeneralLedgerReport";

actions.add("microfinance_loan_management.general_ledger", GeneralLedgerReport);
