/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";

export class MicrofinanceLoanDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.state = useState({ loading: true, error: false, data: null });
        this.charts = [];
        this.shouldRenderCharts = false;
        this.stateChartRef = useRef("stateChart");
        this.disbursementChartRef = useRef("disbursementChart");
        this.repaymentChartRef = useRef("repaymentChart");
        this.defaultRateChartRef = useRef("defaultRateChart");
        this.parChartRef = useRef("parChart");

        onMounted(async () => {
            await this.loadDashboard();
        });

        onPatched(() => {
            if (this.shouldRenderCharts) {
                this.shouldRenderCharts = false;
                this.renderCharts();
            }
        });

        onWillUnmount(() => {
            this.destroyCharts();
        });
    }

    async loadDashboard() {
        try {
            this.state.data = await this.rpc("/microfinance/dashboard/data", {});
            this.shouldRenderCharts = true;
            this.state.loading = false;
        } catch (error) {
            this.state.loading = false;
            this.state.error = true;
            console.error("Microfinance dashboard data loading failed", error);
        }
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }

    get topOverdueLoans() {
        return this.state.data?.top_overdue_loans || [];
    }

    formatNumber(value) {
        return new Intl.NumberFormat().format(value || 0);
    }

    formatMoney(value) {
        const currency = this.state.data?.currency || "";
        return `${this.formatNumber(Math.round(value || 0))} ${currency}`.trim();
    }

    formatPercent(value) {
        return `${(value || 0).toFixed(1)}%`;
    }

    destroyCharts() {
        for (const chart of this.charts) {
            chart.destroy();
        }
        this.charts = [];
    }

    mountChart(ref, options) {
        if (!ref.el) {
            return;
        }
        const chart = new this.ApexCharts(ref.el, options);
        this.charts.push(chart);
        chart.render();
    }

    renderCharts() {
        if (!this.state.data) {
            return;
        }
        const ApexChartsLib = window.ApexCharts;
        if (!ApexChartsLib) {
            console.warn("Microfinance dashboard: ApexCharts is not loaded; charts were skipped.");
            return;
        }

        this.ApexCharts = ApexChartsLib;
        this.destroyCharts();
        const data = this.state.data;
        const baseChart = {
            fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            toolbar: { show: false },
            foreColor: "#475569",
        };
        const palette = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#7c3aed", "#0891b2", "#64748b"];

        this.mountChart(this.stateChartRef, {
            chart: { ...baseChart, type: "donut", height: 300 },
            series: data.loans_by_state.values,
            labels: data.loans_by_state.labels,
            colors: palette,
            legend: { position: "bottom" },
            dataLabels: { enabled: true },
            plotOptions: { pie: { donut: { size: "68%" } } },
        });

        this.mountChart(this.disbursementChartRef, {
            chart: { ...baseChart, type: "bar", height: 320 },
            series: [{ name: "Decaissements", data: data.monthly.disbursement }],
            xaxis: { categories: data.monthly.labels },
            colors: ["#2563eb"],
            plotOptions: { bar: { borderRadius: 5, columnWidth: "48%" } },
            dataLabels: { enabled: false },
            grid: { borderColor: "#e2e8f0" },
        });

        this.mountChart(this.repaymentChartRef, {
            chart: { ...baseChart, type: "line", height: 320 },
            series: [
                { name: "Remboursements", data: data.monthly.repayment },
                { name: "Impayes", data: data.monthly.overdue },
            ],
            xaxis: { categories: data.monthly.labels },
            colors: ["#10b981", "#ef4444"],
            stroke: { width: 3, curve: "smooth" },
            dataLabels: { enabled: false },
            markers: { size: 4 },
            grid: { borderColor: "#e2e8f0" },
        });

        this.mountChart(this.parChartRef, {
            chart: { ...baseChart, type: "bar", height: 280 },
            series: [{ name: "PAR", data: (data.par_buckets?.values || []).map((value) => Number(value.toFixed(1))) }],
            xaxis: { categories: data.par_buckets?.labels || [] },
            colors: ["#22c55e", "#eab308", "#f97316", "#ef4444"],
            plotOptions: {
                bar: {
                    borderRadius: 5,
                    columnWidth: "55%",
                    distributed: true,
                    dataLabels: { position: "top" },
                },
            },
            dataLabels: {
                enabled: true,
                formatter: (value) => `${value}%`,
                offsetY: -20,
                style: { colors: ["#475569"] },
            },
            legend: { show: false },
            yaxis: { labels: { formatter: (value) => `${value}%` } },
            grid: { borderColor: "#e2e8f0" },
        });

        this.mountChart(this.defaultRateChartRef, {
            chart: { ...baseChart, type: "radialBar", height: 280 },
            series: [Number((data.kpis.default_rate || 0).toFixed(1))],
            labels: ["Taux defaut"],
            colors: ["#ef4444"],
            plotOptions: {
                radialBar: {
                    hollow: { size: "62%" },
                    dataLabels: {
                        value: { formatter: (value) => `${value}%` },
                    },
                },
            },
        });
    }
}

MicrofinanceLoanDashboard.template = "microfinance_loan_management.MicrofinanceLoanDashboard";
registry.category("actions").add("microfinance_loan_dashboard", MicrofinanceLoanDashboard);
