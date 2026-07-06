/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

class BaseAccountingFinancialReport extends Component {
    static components = { Dropdown, DropdownItem };
    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.companyService = useService("company");
        this.toggleLine = this.toggleLine.bind(this);
        this.toggleDropdown = this.toggleDropdown.bind(this);
        this.isDropdownOpen = this.isDropdownOpen.bind(this);
        this.closeDropdown = this.closeDropdown.bind(this);
        this.unfoldAll = this.unfoldAll.bind(this);
        this.toggleHideZero = this.toggleHideZero.bind(this);
        this.toggleHorizontalSplit = this.toggleHorizontalSplit.bind(this);
        this.onSpecificDateChange = this.onSpecificDateChange.bind(this);
        this.onDateChange = this.onDateChange.bind(this);
        this.clearJournals = this.clearJournals.bind(this);
        this.selectDatePreset = this.selectDatePreset.bind(this);
        this.setComparisonMode = this.setComparisonMode.bind(this);
        this.setComparisonOrder = this.setComparisonOrder.bind(this);
        this.toggleJournal = this.toggleJournal.bind(this);
        this.setTargetMove = this.setTargetMove.bind(this);
        this.setCurrencyFormat = this.setCurrencyFormat.bind(this);
        this.toggleBudget = this.toggleBudget.bind(this);
        this.exportXlsx = this.exportXlsx.bind(this);
        this.printPdf = this.printPdf.bind(this);
        this.openUnpostedEntries = this.openUnpostedEntries.bind(this);
        this.onComparisonDateChange = this.onComparisonDateChange.bind(this);
        this.onAccountClick = this.onAccountClick.bind(this);

        const action = this.props.action || {};
        const params = action.params || {};
        const context = action.context || {};
        const today = this.toISODate(new Date());

        this.state = useState({
            loading: true,
            error: null,
            reportName: params.report_name || context.report_name || "Balance Sheet",
            reportXmlId: params.report_xml_id || context.report_xml_id || "base_accounting_kit.account_financial_report_balancesheet0",
            title: params.report_title || context.report_title || "Bilan",
            pdfActionXmlId: params.pdf_action_xml_id || context.pdf_action_xml_id || "base_accounting_kit.action_balance_sheet_report",
            xlsxActionXmlId: params.xlsx_action_xml_id || context.xlsx_action_xml_id || false,
            dateTo: today,
            datePreset: "today",
            targetMove: "posted",
            targetMoveLabel: "Pièces comptabilisées",
            journalsLabel: "Tous les journaux",
            selectedJournalIds: [],
            journals: [],
            currency: "",
            currencyFormat: "full",
            companyName: "",
            customCashData: false,
            lines: [],
            unfolded: {},
            openDropdown: null,
            comparisonMode: "none",
            comparisonOrder: "desc",
            comparisonDateTo: false,
            comparisonDateToUsed: false,
            hideZero: false,
            horizontalSplit: false,
            showBudget: false,
            unpostedEntriesExist: false,
            balanceCheck: false,
        });

        onWillStart(async () => {
            await this.loadReport();
        });
    }

    async loadReport() {
        this.state.loading = true;
        this.state.error = null;

        try {
            const result = await this.rpc("/base_accounting_kit/financial_report/data", {
                report_name: this.state.reportName,
                report_xml_id: this.state.reportXmlId,
                date_to: this.state.dateTo,
                target_move: this.state.targetMove,
                journal_ids: this.state.selectedJournalIds,
                enable_comparison: this.state.comparisonMode !== "none",
                comparison_mode: this.state.comparisonMode,
                comparison_date_to: this.state.comparisonDateTo || false,
                company_id: this.companyService.currentCompany.id,
            });

            if (!result.success) {
                this.state.error = result.error || "Erreur de chargement du rapport.";
                this.state.lines = [];
                this.state.customCashData = false;
            } else {
                this.state.lines = result.lines || [];
                this.state.reportName = result.report_name || this.state.reportName;
                this.state.reportXmlId = result.report_xml_id || this.state.reportXmlId;
                this.state.title = result.report_title || this.state.title;
                this.state.pdfActionXmlId = result.pdf_action_xml_id || this.state.pdfActionXmlId;
                this.state.xlsxActionXmlId = result.xlsx_action_xml_id || this.state.xlsxActionXmlId;
                this.state.currency = result.currency || "";
                this.state.companyName = result.company_name || "";
                this.state.customCashData = result.custom_cash_data || false;
                this.state.targetMoveLabel = result.target_move_label || "";
                this.state.journalsLabel = result.journals_label || "Tous les journaux";
                this.state.journals = result.journals || [];
                this.state.selectedJournalIds = result.selected_journal_ids || this.state.selectedJournalIds;
                this.state.comparisonDateToUsed = result.comparison_date_to || false;
                this.state.unpostedEntriesExist = result.unposted_entries_exist || false;
                this.state.balanceCheck = result.balance_check || false;
                this.initializeUnfolded();
            }
        } catch (error) {
            this.state.error = "Impossible de charger le rapport.";
            this.state.lines = [];
            this.state.customCashData = false;
        }

        this.state.loading = false;
    }

    initializeUnfolded() {
        const unfolded = {};
        for (const line of this.state.lines) {
            if ((line.level || 0) <= 2) {
                unfolded[line.id] = true;
            }
        }
        this.state.unfolded = unfolded;
    }

    toggleDropdown(name) {
        this.state.openDropdown = this.state.openDropdown === name ? null : name;
    }

    isDropdownOpen(name) {
        return this.state.openDropdown === name;
    }

    closeDropdown() {
        this.state.openDropdown = null;
    }

    childrenOf(lineId) {
        return this.state.lines.filter((line) => line.parent === lineId);
    }

    hasChildren(line) {
        return this.state.lines.some((candidate) => candidate.parent === line.id);
    }

    isVisible(line) {
        let parentId = line.parent;
        while (parentId) {
            if (!this.state.unfolded[parentId]) {
                return false;
            }
            const parent = this.state.lines.find((candidate) => candidate.id === parentId);
            parentId = parent ? parent.parent : false;
        }
        return true;
    }

    hasNonZeroVisibleChild(line) {
        return this.childrenOf(line.id).some((child) => {
            const amount = Number(child.balance || 0);
            return amount !== 0 || this.hasNonZeroVisibleChild(child);
        });
    }

    visibleLines() {
        return this.state.lines.filter((line) => {
            if (!this.isVisible(line)) {
                return false;
            }
            if (!this.state.hideZero) {
                return true;
            }
            return Number(line.balance || 0) !== 0 || this.hasNonZeroVisibleChild(line);
        });
    }

    toggleLine(line) {
        if (this.hasChildren(line)) {
            this.state.unfolded[line.id] = !this.state.unfolded[line.id];
        }
    }

    unfoldAll() {
        const unfolded = {};
        for (const line of this.state.lines) {
            if (this.hasChildren(line)) {
                unfolded[line.id] = true;
            }
        }
        this.state.unfolded = unfolded;
        this.closeDropdown();
    }

    async setTargetMove(targetMove) {
        this.state.targetMove = targetMove;
        this.closeDropdown();
        await this.loadReport();
    }

    toggleHideZero() {
        this.state.hideZero = !this.state.hideZero;
    }

    toggleHorizontalSplit() {
        this.state.horizontalSplit = !this.state.horizontalSplit;
    }

    toggleBudget() {
        this.state.showBudget = !this.state.showBudget;
    }

    async selectDatePreset(preset) {
        const date = new Date();
        this.state.datePreset = preset;
        if (preset === "today") {
            this.state.dateTo = this.toISODate(date);
        } else if (preset === "month_end") {
            this.state.dateTo = this.toISODate(new Date(date.getFullYear(), date.getMonth() + 1, 0));
        } else if (preset === "quarter_end") {
            const quarterEndMonth = Math.floor(date.getMonth() / 3) * 3 + 2;
            this.state.dateTo = this.toISODate(new Date(date.getFullYear(), quarterEndMonth + 1, 0));
        } else if (preset === "year_end") {
            this.state.dateTo = this.toISODate(new Date(date.getFullYear(), 11, 31));
        } else if (preset === "specific") {
            return;
        }
        this.closeDropdown();
        await this.loadReport();
    }

    async onSpecificDateChange(ev) {
        this.state.datePreset = "specific";
        this.state.dateTo = ev.target.value;
        await this.loadReport();
    }

    async onDateChange(ev) {
        await this.onSpecificDateChange(ev);
    }

    async setComparisonMode(mode) {
        this.state.comparisonMode = mode;
        if (mode === "none" || mode !== "specific") {
            this.closeDropdown();
        }
        if (mode !== "specific" || this.state.comparisonDateTo) {
            await this.loadReport();
        }
    }

    async onComparisonDateChange(ev) {
        this.state.comparisonDateTo = ev.target.value;
        this.closeDropdown();
        await this.loadReport();
    }

    hasComparisonColumn() {
        return this.state.comparisonMode !== "none" && !this.state.loading && !this.state.error;
    }

    comparisonColumnLabel() {
        if (this.state.comparisonDateToUsed) {
            return `Au ${this.formatDate(this.state.comparisonDateToUsed)}`;
        }
        return "Comparaison";
    }

    amountCmpClass(line) {
        const amount = Number(line.balance_cmp || 0);
        const classes = ["bak-line-amount"];
        if (amount < 0) classes.push("bak-negative");
        if (amount === 0) classes.push("bak-zero");
        return classes.join(" ");
    }

    deltaClass(line) {
        const delta = Number(line.balance || 0) - Number(line.balance_cmp || 0);
        const classes = ["bak-line-amount", "bak-delta"];
        if (delta < 0) classes.push("bak-negative");
        if (delta > 0) classes.push("bak-positive");
        return classes.join(" ");
    }

    formatDelta(line) {
        const delta = Number(line.balance || 0) - Number(line.balance_cmp || 0);
        const sign = delta > 0 ? "+" : "";
        return `${sign}${this.formatAmount(delta)}`;
    }

    setComparisonOrder(order) {
        this.state.comparisonOrder = order;
    }

    async toggleJournal(journalId) {
        const selected = [...this.state.selectedJournalIds];
        const index = selected.indexOf(journalId);
        if (index >= 0) {
            selected.splice(index, 1);
        } else {
            selected.push(journalId);
        }
        this.state.selectedJournalIds = selected;
        await this.loadReport();
    }

    async clearJournals() {
        this.state.selectedJournalIds = [];
        this.closeDropdown();
        await this.loadReport();
    }

    isJournalSelected(journalId) {
        return this.state.selectedJournalIds.includes(journalId);
    }

    setCurrencyFormat(format) {
        this.state.currencyFormat = format;
        this.closeDropdown();
    }

    currencyButtonLabel() {
        const labels = {
            full: "En .Ar",
            ar: "En Ar",
            kar: "En KAr",
            mar: "En MAr",
        };
        return labels[this.state.currencyFormat] || "En .Ar";
    }

    comparisonButtonLabel() {
        const labels = {
            none: "% Comparaison",
            previous_period: "Période précédente",
            previous_year: "Exercice passé",
            specific: "Date spécifique",
        };
        return labels[this.state.comparisonMode] || "% Comparaison";
    }

    dateButtonLabel() {
        return `À la date du ${this.formatDate(this.state.dateTo)}`;
    }

    formatAmount(value) {
        const rawAmount = Number(value || 0);
        const format = this.state.currencyFormat;
        const divisor = format === "kar" ? 1000 : format === "mar" ? 1000000 : 1;
        const amount = rawAmount / divisor;
        const digits = format === "full" ? 2 : 0;
        return amount.toLocaleString("fr-FR", {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }

    lineClass(line) {
        const classes = ["bak-line", `bak-level-${line.level || 0}`];
        if ((line.level || 0) === 0) classes.push("bak-section");
        if ((line.level || 0) === 1) classes.push("bak-subsection");
        if (line.type === "account") classes.push("bak-account-line");
        if (line.total) classes.push("bak-total-line");
        return classes.join(" ");
    }

    reportClass() {
        const classes = ["o_bak_financial_report"];
        if (this.state.horizontalSplit) {
            classes.push("bak-horizontal-split");
        }
        return classes.join(" ");
    }

    amountClass(line) {
        const amount = Number(line.balance || 0);
        const classes = ["bak-line-amount"];
        if (amount < 0) classes.push("bak-negative");
        if (amount === 0) classes.push("bak-zero");
        return classes.join(" ");
    }

    paddingLeft(line) {
        return `${Math.min((line.level || 0) * 24, 112)}px`;
    }

    gridTemplateColumns() {
        const cols = ["minmax(0, 1fr)"];
        if (this.state.showBudget) {
            cols.push("140px");
        }
        if (this.hasComparisonColumn()) {
            cols.push("160px", "140px");
        }
        cols.push("180px");
        return `grid-template-columns: ${cols.join(" ")};`;
    }

    formatDate(value) {
        if (!value) return "";
        const parts = value.split("-");
        if (parts.length !== 3) return value;
        return `${parts[2]}/${parts[1]}/${parts[0]}`;
    }

    toISODate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    printPdf() {
        if (this.state.pdfActionXmlId) {
            this.action.doAction(this.state.pdfActionXmlId);
        }
    }

    exportXlsx() {
        if (this.state.xlsxActionXmlId) {
            this.action.doAction(this.state.xlsxActionXmlId);
        }
    }

    openUnpostedEntries() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pièces non comptabilisées",
            res_model: "account.move",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["state", "!=", "posted"],
                ["date", "<=", this.state.dateTo],
                ["company_id", "=", this.companyService.currentCompany.id],
            ],
        });
    }

    balanceCheckClass() {
        if (!this.state.balanceCheck) {
            return "";
        }
        return this.state.balanceCheck.ok ? "bak-balance-ok" : "bak-balance-warning";
    }

    onAccountClick(line) {
        if (line.type !== "account" || !line.account_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: line.name,
            res_model: "account.move.line",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["account_id", "=", line.account_id],
                ["date", "<=", this.state.dateTo],
                ["company_id", "=", this.companyService.currentCompany.id],
                ["parent_state", this.state.targetMove === "posted" ? "=" : "!=", this.state.targetMove === "posted" ? "posted" : "cancel"],
            ],
            context: { search_default_group_by_move: 0 },
        });
    }
}

BaseAccountingFinancialReport.template = "base_accounting_kit.FinancialReport";

registry.category("actions").add("base_accounting_kit.financial_report", BaseAccountingFinancialReport);
