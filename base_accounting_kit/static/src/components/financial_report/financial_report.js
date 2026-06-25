/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class BaseAccountingFinancialReport extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");

        const today = new Date().toISOString().slice(0, 10);

        this.state = useState({
            loading: true,
            error: null,
            reportName: "Balance Sheet",
            title: "Bilan",
            dateTo: today,
            targetMove: "posted",
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
            }
        } catch (error) {
            this.state.error = "Impossible de charger le bilan.";
            this.state.lines = [];
        }

        this.state.loading = false;
    }

    formatAmount(value) {
        const amount = Number(value || 0);
        return amount.toLocaleString("fr-FR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    lineClass(line) {
        const classes = ["bak-line"];
        if (line.level <= 1) classes.push("bak-section");
        if (line.level === 2) classes.push("bak-subsection");
        if (line.balance < 0) classes.push("bak-negative");
        return classes.join(" ");
    }

    paddingLeft(line) {
        return `${Math.min((line.level || 1) * 16, 80)}px`;
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

    exportXlsx() {
        alert("Export XLSX à connecter dans le prochain lot.");
    }
}

BaseAccountingFinancialReport.template = "base_accounting_kit.FinancialReport";

registry.category("actions").add("base_accounting_kit.financial_report", BaseAccountingFinancialReport);