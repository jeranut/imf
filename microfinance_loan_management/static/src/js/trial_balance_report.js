/** @odoo-module **/
// Balance générale interactive : étend le composant du Grand livre (qui étend celui du Journal de banque) pour garder la
// même barre de filtres, la même bannière, les mêmes formats de montants et exports. Changent : les données (une ligne
// par compte avec soldes débit/crédit), le regroupement par classe et le témoin d'équilibre.

import { registry } from "@web/core/registry";

const actions = registry.category("actions");
const GeneralLedgerReport = actions.get("microfinance_loan_management.general_ledger");

class TrialBalanceReport extends GeneralLedgerReport {
    setup() {
        super.setup();
        Object.assign(this.state, {
            title: "Balance générale",
            groupByClass: true,
        });
    }

    // ------------------------------------------------------------------ chargement
    async loadReport() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await this.rpc("/microfinance/trial_balance/data", {
                ...this.filterParams(),
                search: this.state.search || false,
                display_account: this.state.displayAccount,
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
                this.state.reportData = result.data;
                // classes dépliées par défaut
                const unfolded = {};
                for (const group of result.data.classes) {
                    unfolded[`class_${group.key}`] = true;
                }
                this.state.unfolded = unfolded;
            }
        } catch (error) {
            this.state.error = "Impossible de charger la balance générale.";
            this.state.reportData = null;
        }
        this.state.loading = false;
    }

    classes() {
        return (this.state.reportData && this.state.reportData.classes) || [];
    }

    totals() {
        return (this.state.reportData && this.state.reportData.totals) || {};
    }

    balanceCheck() {
        return (this.state.reportData && this.state.reportData.balance_check) || { balanced: true, gap: 0 };
    }

    toggleGroupByClass() {
        this.state.groupByClass = !this.state.groupByClass;
    }

    toggleClass(group) {
        this.toggleFold(`class_${group.key}`);
    }

    // Clic sur un compte : Grand livre de la même société, filtré sur ce compte, mêmes période, journaux et pièces
    openLedger(account) {
        const allJournals = this.state.selectedJournalIds.length === this.state.journals.length;
        this.action.doAction({
            type: "ir.actions.client",
            tag: "microfinance_loan_management.general_ledger",
            name: "Grand livre",
            params: {
                report_title: "Grand livre",
                initial: {
                    dateFrom: this.state.dateFrom,
                    dateTo: this.state.dateTo,
                    periodPreset: "specific",
                    targetMove: this.state.targetMove,
                    selectedJournalIds: allJournals ? [] : [...this.state.selectedJournalIds],
                    initBalance: this.state.initBalance,
                    displayAccount: "all",
                    accountId: account.id,
                    search: account.code,
                },
            },
        });
    }

    // ------------------------------------------------------------------ exports
    exportParams() {
        const params = super.exportParams();
        delete params.account_id;
        delete params.sortby;
        return params;
    }

    printPdf() {
        window.open(this._exportUrl("/microfinance/trial_balance/pdf"), "_blank");
    }

    exportXlsx() {
        window.open(this._exportUrl("/microfinance/trial_balance/xlsx"), "_blank");
    }
}

TrialBalanceReport.template = "microfinance_loan_management.TrialBalanceReport";

actions.add("microfinance_loan_management.trial_balance", TrialBalanceReport);
