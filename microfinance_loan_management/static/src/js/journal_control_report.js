/** @odoo-module **/
// Contrôle des journaux interactif : étend le composant du Grand livre (qui étend celui du Journal de banque) pour garder
// la même barre de filtres, la même bannière, les mêmes formats de montants et exports. Changent : les données (une ligne
// par journal avec compteurs d'anomalies), les pièces d'un journal (pages de 80) et les lignes d'une pièce (au dépliage).

import { registry } from "@web/core/registry";

const actions = registry.category("actions");
const GeneralLedgerReport = actions.get("microfinance_loan_management.general_ledger");

const ANOMALY_LABELS = {
    unbalanced: "Pièces déséquilibrées",
    draft: "Pièces en brouillon",
    cancel: "Pièces annulées",
};

class JournalControlReport extends GeneralLedgerReport {
    setup() {
        super.setup();
        Object.assign(this.state, {
            title: "Contrôle des journaux",
            sortby: "sort_date",
            journalMoves: {},
            moveLines: {},
            anomalyFilter: {},
            gapsOpen: {},
        });
    }

    sortLabel() {
        return this.state.sortby === "sort_number" ? "Tri : numéro de pièce" : "Tri : date";
    }

    onSearchPlaceholder() {
        return "Numéro de pièce...";
    }

    anomalyLabel(kind) {
        return ANOMALY_LABELS[kind];
    }

    statusLabel(status) {
        return { ok: "OK", info: "À noter", anomaly: "Anomalie" }[status];
    }

    // ------------------------------------------------------------------ chargement
    async loadReport() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await this.rpc("/microfinance/journal_control/data", {
                ...this.filterParams(),
                search: this.state.search || false,
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
                // les filtres ont changé : pièces et lignes à recharger au dépliage
                this.state.journalMoves = {};
                this.state.moveLines = {};
                this.state.anomalyFilter = {};
                this.state.gapsOpen = {};
            }
        } catch (error) {
            this.state.error = "Impossible de charger le contrôle des journaux.";
            this.state.reportData = null;
        }
        this.state.loading = false;
    }

    journalRows() {
        return (this.state.reportData && this.state.reportData.journals) || [];
    }

    totals() {
        return (this.state.reportData && this.state.reportData.totals) || { anomalies: {} };
    }

    isBalanced() {
        return !this.state.reportData || this.state.reportData.balanced;
    }

    // ------------------------------------------------------------------ pièces d'un journal
    async toggleJournalRow(journal) {
        const key = `journal_${journal.id}`;
        this.toggleFold(key);
        if (!this.isFolded(key) && !this.state.journalMoves[journal.id] && journal.count + journal.anomalies.cancel) {
            await this.loadMoves(journal);
        }
    }

    async loadMoves(journal, reset = false) {
        const current = reset
            ? { rows: [], hasMore: true, loading: false }
            : this.state.journalMoves[journal.id] || { rows: [], hasMore: true, loading: false };
        if (current.loading) return;
        this.state.journalMoves[journal.id] = { ...current, loading: true };
        try {
            const page = await this.rpc("/microfinance/journal_control/moves", {
                ...this.filterParams(),
                journal_id: journal.id,
                search: this.state.search || false,
                anomaly: this.state.anomalyFilter[journal.id] || false,
                offset: current.rows.length,
            });
            this.state.journalMoves[journal.id] = {
                rows: current.rows.concat(page.rows),
                hasMore: page.has_more,
                total: page.total_rows,
                loading: false,
            };
        } catch (error) {
            this.state.journalMoves[journal.id] = { ...current, loading: false, error: true };
        }
    }

    moves(journal) {
        return this.state.journalMoves[journal.id] || { rows: [], hasMore: false, loading: false };
    }

    // Compteur d'anomalie cliquable : déplie le journal et filtre la liste des pièces concernées
    async openAnomaly(journal, kind) {
        if (!journal.anomalies[kind]) return;
        this.state.anomalyFilter[journal.id] = kind;
        this.state.unfolded[`journal_${journal.id}`] = true;
        await this.loadMoves(journal, true);
    }

    async clearAnomaly(journal) {
        this.state.anomalyFilter[journal.id] = false;
        await this.loadMoves(journal, true);
    }

    toggleGaps(journal) {
        this.state.gapsOpen[journal.id] = !this.state.gapsOpen[journal.id];
        this.state.unfolded[`journal_${journal.id}`] = true;
        if (!this.state.journalMoves[journal.id]) {
            this.loadMoves(journal);
        }
    }

    // ------------------------------------------------------------------ lignes d'une pièce
    async toggleMove(move) {
        const key = `move_${move.move_id}`;
        this.toggleFold(key);
        if (!this.isFolded(key) && !this.state.moveLines[move.move_id]) {
            this.state.moveLines[move.move_id] = [];
            try {
                this.state.moveLines[move.move_id] = await this.rpc("/microfinance/journal_control/move_lines", {
                    move_id: move.move_id,
                    company_id: this.companyService.currentCompany.id,
                });
            } catch (error) {
                delete this.state.moveLines[move.move_id];
            }
        }
    }

    linesOf(move) {
        return this.state.moveLines[move.move_id] || [];
    }

    // ------------------------------------------------------------------ exports
    exportParams() {
        const params = super.exportParams();
        delete params.account_id;
        delete params.display_account;
        delete params.init_balance;
        return params;
    }

    printPdf() {
        window.open(this._exportUrl("/microfinance/journal_control/pdf"), "_blank");
    }

    exportXlsx() {
        window.open(this._exportUrl("/microfinance/journal_control/xlsx"), "_blank");
    }
}

JournalControlReport.template = "microfinance_loan_management.JournalControlReport";

actions.add("microfinance_loan_management.journal_control", JournalControlReport);
