/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class BaseAccountingFinancialReport extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.toggleLine = this.toggleLine.bind(this);

        const today = new Date().toISOString().slice(0, 10);

        this.state = useState({
            loading: true,
            error: null,
            reportName: "Balance Sheet",
            title: "Bilan",
            dateTo: today,
            targetMove: "posted",
            targetMoveLabel: "Pièces comptabilisées",
            journalsLabel: "Tous les journaux",
            currency: "",
            companyName: "",
            lines: [],
            unfolded: {},
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
                date_to: this.state.dateTo,
                target_move: this.state.targetMove,
            });

            if (!result.success) {
                this.state.error = result.error || "Erreur de chargement du rapport.";
                this.state.lines = [];
            } else {
                this.state.lines = result.lines || [];
                this.state.currency = result.currency || "";
                this.state.companyName = result.company_name || "";
                this.state.targetMoveLabel = result.target_move_label || "";
                this.state.journalsLabel = result.journals_label || "";
                this.initializeUnfolded();
            }
        } catch (error) {
            this.state.error = "Impossible de charger le bilan.";
            this.state.lines = [];
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

    visibleLines() {
        return this.state.lines.filter((line) => this.isVisible(line));
    }

    toggleLine(line) {
        if (this.hasChildren(line)) {
            this.state.unfolded[line.id] = !this.state.unfolded[line.id];
        }
    }

    formatAmount(value) {
        const amount = Number(value || 0);
        return amount.toLocaleString("fr-FR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
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

    async onDateChange(ev) {
        this.state.dateTo = ev.target.value;
        await this.loadReport();
    }

    async onTargetMoveChange(ev) {
        this.state.targetMove = ev.target.value;
        await this.loadReport();
    }

    printPdf() {
        this.action.doAction("base_accounting_kit.action_balance_sheet_report");
    }

}

BaseAccountingFinancialReport.template = "base_accounting_kit.FinancialReport";

registry.category("actions").add("base_accounting_kit.financial_report", BaseAccountingFinancialReport);
