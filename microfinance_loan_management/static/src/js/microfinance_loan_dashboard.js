/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";

export class MicrofinanceLoanDashboard extends Component {
    // Config generique du panneau d'onglets (Lot 7, deplacement Lot 9bis) : source unique pour la
    // nav (boucle t-foreach dans le template, plus de bouton duplique par onglet) ET pour
    // setActiveTopic() ci-dessous (plus de chaine 'analyses' codee en dur pour decider qui a des
    // graphiques ApexCharts a detruire/remonter - hasCharts le porte explicitement, "fonds" en a
    // besoin depuis qu'il recoit les graphiques fonds bailleurs deplaces hors de "analyses").
    static TOPICS = [
        { id: "apercu", label: "Vue d'ensemble", icon: "fa-tachometer" },
        { id: "analyses", label: "Analyses", icon: "fa-bar-chart", hasCharts: true },
        { id: "fonds", label: "Fonds bailleurs", icon: "fa-university", hasCharts: true },
        { id: "activite", label: "Activite recente", icon: "fa-history" },
    ];

    setup() {
        this.rpc = useService("rpc");
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.topics = MicrofinanceLoanDashboard.TOPICS;
        // activeTopic : vrai systeme d'onglets (un seul topic rendu a la fois via t-if dans le
        // template, pas juste une ancre/scroll) - "apercu" (Vue d'ensemble) est le topic par
        // defaut au chargement.
        this.state = useState({ loading: true, error: false, data: null, activeTopic: "apercu" });
        this.charts = [];
        this.shouldRenderCharts = false;
        this.stateChartRef = useRef("stateChart");
        this.disbursementChartRef = useRef("disbursementChart");
        this.repaymentChartRef = useRef("repaymentChart");
        this.overdueTrendChartRef = useRef("overdueTrendChart");
        this.parChartRef = useRef("parChart");
        this.fondMultiChartRef = useRef("fondMultiChart");
        this.fondSingleChartRef = useRef("fondSingleChart");

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

    /**
     * Bascule vers un autre onglet (topic). Seuls les onglets marques hasCharts (config TOPICS
     * ci-dessus : "analyses" et "fonds") contiennent des graphiques ApexCharts (aucun sur
     * "apercu"/"activite") : c'est le seul cas ou l'ordre de rendu compte.
     *
     * Strategie retenue : lazy render, pas resize(). ApexCharts rend du SVG dans le <div>
     * reference (t-ref) au moment de chart.render() ; tant qu'un onglet hasCharts n'est pas le
     * topic actif, son contenu est retire du DOM par le t-if du template (pas seulement masque en
     * CSS), donc les refs des graphiques sont "null" et mountChart() (qui verifie deja "if
     * (!ref.el) return") les ignore silencieusement - aucun graphique n'est jamais monte dans un
     * conteneur a largeur nulle. On force simplement un nouveau passage de renderCharts() a chaque
     * fois qu'un onglet hasCharts redevient actif (via shouldRenderCharts + onPatched, meme
     * mecanisme que le chargement initial), pour re-creer les graphiques avec la taille reelle du
     * conteneur desormais visible. Les instances existantes sont detruites en quittant un onglet
     * hasCharts (elles pointeraient sinon vers des noeuds DOM deja retires par le t-if).
     */
    setActiveTopic(topic) {
        if (this.state.activeTopic === topic) {
            return;
        }
        const previousTopic = this.topics.find((t) => t.id === this.state.activeTopic);
        if (previousTopic?.hasCharts) {
            this.destroyCharts();
        }
        this.state.activeTopic = topic;
        const nextTopic = this.topics.find((t) => t.id === topic);
        if (nextTopic?.hasCharts) {
            this.shouldRenderCharts = true;
        }
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }

    get companyInfo() {
        return this.state.data?.company || {};
    }

    get topOverdueLoans() {
        return this.state.data?.top_overdue_loans || [];
    }

    get recentLoans() {
        return this.state.data?.recent_loans || [];
    }

    get todayInstallments() {
        return this.state.data?.today_installments || [];
    }

    get todayInstallmentsCount() {
        return this.state.data?.today_installments_count || 0;
    }

    get fondMultiChart() {
        return this.state.data?.fond_multi_chart || { visible: false, labels: [], contributions: [], decaissements: [] };
    }

    get fondSingleChart() {
        return this.state.data?.fond_single_chart || { labels: [], values: [] };
    }

    get fondMatrix() {
        return this.state.data?.fond_matrix || { companies: [], funds: [] };
    }

    /**
     * Montant décaissé sur ce fonds par cette agence, ou null si aucun décaissement (rendu par
     * le template comme un tiret plutôt qu'un "0" trompeur - une cellule à 0 littéral serait
     * indiscernable d'une agence qui n'utilise simplement pas ce fonds).
     */
    fondMatrixAmount(fund, companyId) {
        const amount = fund.amounts[companyId];
        return amount ? amount : null;
    }

    fondMatrixIsDefault(fund, companyId) {
        return fund.is_default_for.includes(companyId);
    }

    formatNumber(value) {
        return new Intl.NumberFormat().format(value || 0);
    }

    formatDate(value) {
        if (!value) {
            return "";
        }
        return new Intl.DateTimeFormat("fr-FR").format(new Date(value));
    }

    formatMoney(value) {
        const currency = this.state.data?.currency || "";
        return `${this.formatNumber(Math.round(value || 0))} ${currency}`.trim();
    }

    formatPercent(value) {
        return `${(value || 0).toFixed(1)}%`;
    }

    /**
     * Ouvre la liste filtrée correspondant à une tuile KPI (aucune action n'existait sur ces
     * tuiles auparavant : navigation ajoutée vers la vue liste déjà existante la plus proche de
     * chaque indicateur, sans toucher aux valeurs/calculs affichés sur le tableau de bord).
     */
    openKpiAction(model, domain, name) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            name,
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openNewLoan() {
        // Le dossier d'instruction (microfinance.loan.application) est le seul point
        // d'entrée de création d'un crédit : microfinance.loan.create() est verrouillé
        // côté serveur (contexte microfinance_loan_creation_allowed, cf.
        // action_create_loan()/le wizard dédié) et ne doit plus être créable directement
        // depuis le tableau de bord.
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "microfinance.loan.application",
            name: "Nouveau dossier",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllLoans() {
        this.actionService.doAction("microfinance_loan_management.action_microfinance_loan");
    }

    openAllInstallments() {
        this.actionService.doAction("microfinance_loan_management.action_microfinance_installment");
    }

    /**
     * Réutilise action_open_payment_wizard (déjà en place côté microfinance.loan, avec son
     * pré-remplissage montant/journal) plutôt que de reconstruire le contexte de l'assistant en
     * JS : le bouton "Encaisser" du panneau "Échéances du jour" ouvre ainsi exactement le même
     * assistant que le bouton équivalent sur la fiche crédit.
     */
    async openPaymentWizard(loanId) {
        const action = await this.orm.call("microfinance.loan", "action_open_payment_wizard", [[loanId]]);
        this.actionService.doAction(action);
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

        this.mountChart(this.overdueTrendChartRef, {
            chart: { ...baseChart, type: "line", height: 280 },
            series: [{ name: "Nouveaux impayes", data: data.monthly.new_overdue }],
            xaxis: { categories: data.monthly.labels },
            colors: ["#f59e0b"],
            stroke: { width: 3, curve: "smooth" },
            dataLabels: { enabled: false },
            markers: { size: 4 },
            yaxis: { labels: { formatter: (value) => Math.round(value) } },
            grid: { borderColor: "#e2e8f0" },
        });

        if (data.fond_multi_chart?.visible) {
            this.mountChart(this.fondMultiChartRef, {
                chart: { ...baseChart, type: "bar", height: 300 },
                series: [
                    { name: "Contributions", data: data.fond_multi_chart.contributions },
                    { name: "Decaissements", data: data.fond_multi_chart.decaissements },
                ],
                xaxis: { categories: data.fond_multi_chart.labels },
                colors: ["#0891b2", "#2563eb"],
                plotOptions: { bar: { borderRadius: 5, columnWidth: "55%" } },
                dataLabels: { enabled: false },
                grid: { borderColor: "#e2e8f0" },
            });
        }

        this.mountChart(this.fondSingleChartRef, {
            chart: { ...baseChart, type: "bar", height: 300 },
            series: [{ name: "Solde disponible", data: data.fond_single_chart?.values || [] }],
            xaxis: { categories: data.fond_single_chart?.labels || [] },
            colors: ["#0891b2"],
            plotOptions: { bar: { borderRadius: 5, columnWidth: "48%" } },
            dataLabels: { enabled: false },
            grid: { borderColor: "#e2e8f0" },
        });
    }
}

MicrofinanceLoanDashboard.template = "microfinance_loan_management.MicrofinanceLoanDashboard";
registry.category("actions").add("microfinance_loan_dashboard", MicrofinanceLoanDashboard);
