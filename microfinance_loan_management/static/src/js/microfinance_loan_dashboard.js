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
    // "portefeuille" est marque hidden : retire de la navigation interne du Tableau de bord
    // (accès désormais uniquement via le menu Crédits > Mon portefeuille, action
    // action_microfinance_agent_portfolio qui ouvre ce même composant avec le contexte
    // {'dashboard_topic': 'portefeuille'}) mais reste un topic valide pour setActiveTopic()/le
    // t-if de contenu - hidden ne fait que l'exclure de visibleTopics (nav), pas de TOPICS.
    static TOPICS = [
        { id: "apercu", label: "Vue d'ensemble", icon: "fa-tachometer" },
        { id: "portefeuille", label: "Mon portefeuille", icon: "fa-briefcase", hasCharts: true, hidden: true },
        { id: "analyses", label: "Analyses", icon: "fa-bar-chart", hasCharts: true },
        { id: "fonds", label: "Fonds bailleurs", icon: "fa-university", hasCharts: true },
        { id: "activite", label: "Activite recente", icon: "fa-history" },
    ];

    static PAGE_SIZE = 20;

    // Les 6 boutons "Mes ..." de la barre d'actions "Mon portefeuille" : anciennement des
    // redirections (ir.actions.act_window via openAgentShortcut/_openList, cf. git history),
    // maintenant des onglets rendus dans le dashboard (onPortfolioTabClick ci-dessous), servis
    // par la méthode unique microfinance.loan.get_portfolio_tab (whitelist + domaine résolus
    // côté serveur). `clickable` : seules les lignes client/crédit/visite ouvrent leur fiche,
    // remboursements/impayés/échéances restent en lecture seule (cf. consigne métier).
    static TABS = [
        { id: "my_clients", label: "Mes clients", model: "res.partner", clickable: true },
        { id: "my_loans", label: "Mes crédits", model: "microfinance.loan", clickable: true },
        { id: "my_payments", label: "Mes remboursements", model: "microfinance.loan.payment", clickable: false },
        { id: "my_overdue", label: "Mes impayés", model: "microfinance.loan", clickable: false },
        { id: "my_installments", label: "Mes échéances", model: "microfinance.loan.installment", clickable: false },
        { id: "my_visits", label: "Mes visites", model: "microfinance.collection.visit", clickable: true },
        // 7e onglet : pas un simple search_read (cf. _PORTFOLIO_TAB_CONFIG côté serveur), rendu
        // par un panneau dédié (cf. XML) plutôt que le tableau générique - clickable n'a pas de
        // sens ici, chaque ligne sait déjà ouvrir sa propre fiche via res_model/res_id (loan ou
        // allocation) renvoyés par le serveur.
        { id: "my_funds", label: "Fonds de crédit", model: null, clickable: false },
    ];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.topics = MicrofinanceLoanDashboard.TOPICS;
        this.portfolioTabs = MicrofinanceLoanDashboard.TABS;
        // Liste utilisee par la nav (t-foreach) : exclut les topics hidden (cf. "portefeuille"
        // ci-dessus), sans retirer leur entree de this.topics dont setActiveTopic()/onMounted()
        // ont besoin pour l'ouverture directe via contexte dashboard_topic.
        this.visibleTopics = this.topics.filter((t) => !t.hidden);
        // activeTopic : vrai systeme d'onglets (un seul topic rendu a la fois via t-if dans le
        // template, pas juste une ancre/scroll) - "apercu" (Vue d'ensemble) est le topic par
        // defaut au chargement.
        this.state = useState({
            loading: true,
            error: false,
            data: null,
            activeTopic: "apercu",
            // --- Onglet "Mon portefeuille" (Lot 2) : chargé paresseusement à la 1re activation
            // et rafraîchi à chaque changement d'agent dans le sélecteur d'en-tête. Données
            // servies par des méthodes @api.model dédiées de microfinance.loan avec un scope
            // par agent validé serveur, distinctes de get_dashboard_data qui alimente les
            // autres onglets.
            agent: {
                loaded: false,
                loading: false,
                agents: [],
                selectedOfficerId: null,
                // true seulement quand ce portefeuille est consulté via le menu "Portefeuille"
                // (liste) par quelqu'un d'autre que l'agent lui-même (portfolio_is_own=False
                // renvoyé par get_dashboard_data) : masque "Nouveau client" (seule action de
                // mutation de cette barre - les 6 autres boutons sont déjà des onglets lecture
                // seule, cf. onPortfolioTabClick).
                readOnly: false,
                kpis: {},
                monthly: {},
                par: null,
                cumulPar: null,
                dueDates: null,
                history: { labels: [], has_data: false },
                table: { rows: [], total: 0, offset: 0 },
                tableLoading: false,
                search: "",
                // Onglets "Mes clients/crédits/remboursements/impayés/échéances/visites" :
                // chargement paresseux au 1er clic, mis en cache par onglet (cache vidé au
                // changement d'agent par onSelectAgent, les données étant scopées par officer_id
                // côté serveur) pour ne pas recharger en reswitchant entre onglets déjà vus.
                tabs: { active: null, loading: false, cache: {} },
                // Onglet "Fonds de crédit" (7e, cf. TABS) : état séparé de `tabs` ci-dessus car
                // il porte des filtres (fonds/type/période) qui composent la clé de cache, en
                // plus de l'offset de pagination - les 6 autres onglets n'en ont pas.
                fundsTab: {
                    loading: false,
                    offset: 0,
                    filters: { fundId: false, flow: "all", dateFrom: false, dateTo: false },
                    cache: {},
                },
                // Chantier décaissement provisoire : crédits activés pas encore libérés pour
                // décaissement au guichet (get_agent_upcoming_disbursements), section
                // "Décaissements à venir" - distincte de la table principale ci-dessus qui ne
                // porte que sur le portefeuille déjà décaissé.
                upcomingDisbursements: [],
            },
        });
        this.charts = [];
        this.shouldRenderCharts = false;
        this.stateChartRef = useRef("stateChart");
        this.disbursementChartRef = useRef("disbursementChart");
        this.repaymentChartRef = useRef("repaymentChart");
        this.overdueTrendChartRef = useRef("overdueTrendChart");
        this.parChartRef = useRef("parChart");
        this.fondMultiChartRef = useRef("fondMultiChart");
        this.fondSingleChartRef = useRef("fondSingleChart");
        this.agentDonutRef = useRef("agentDonut");
        this.agentCumulParRef = useRef("agentCumulPar");
        this.agentHistoryRef = useRef("agentHistory");
        this._agentSearchTimer = null;

        onMounted(async () => {
            // portfolio_id (menu "Portefeuille" -> microfinance.portfolio.action_open_dashboard,
            // bouton d'une ligne de liste) : transmis tel quel à get_dashboard_data, qui le
            // résout et le vérifie côté serveur par ORM (record rules de microfinance.portfolio)
            // avant de renvoyer portfolio_officer_id/portfolio_is_own - jamais d'agent_id envoyé
            // par ce composant, uniquement cet id de portefeuille.
            this._portfolioId = this.props.action?.context?.portfolio_id || null;
            await this.loadDashboard();
            // Ouverture directe sur un onglet donné (action "Mon portefeuille"/"Portefeuille" :
            // contexte {'dashboard_topic': 'portefeuille'}). Sans contexte -> "apercu" par défaut.
            const initialTopic = this.props.action?.context?.dashboard_topic;
            if (initialTopic && this.topics.some((t) => t.id === initialTopic)) {
                if (this.state.data?.portfolio_officer_id) {
                    // Pré-sélectionne l'agent résolu par le serveur AVANT setActiveTopic : son
                    // chargement (loadAgentPortfolio) ne l'écrase pas s'il est déjà renseigné
                    // (cf. ce fichier plus bas), et appelle get_available_agents comme d'habitude
                    // pour peupler le sélecteur d'en-tête avec le bon agent déjà actif.
                    this.state.agent.selectedOfficerId = this.state.data.portfolio_officer_id;
                }
                this.state.agent.readOnly = !(this.state.data?.portfolio_is_own ?? true);
                this.setActiveTopic(initialTopic);
            }
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
            // Méthode de modèle (et non plus une route HTTP maison appelée via this.rpc) :
            // orm.call transmet allowed_company_ids, donc self.env.company côté serveur suit
            // le sélecteur multi-société. Le rechargement de page déclenché nativement par le
            // sélecteur (browser.location.reload) suffit à rejouer onMounted -> loadDashboard.
            this.state.data = await this.orm.call(
                "microfinance.loan", "get_dashboard_data", [this._portfolioId || null]);
            this.shouldRenderCharts = true;
            this.state.loading = false;
        } catch (error) {
            this.state.loading = false;
            this.state.error = true;
            // Remplace le message générique par celui de l'exception serveur (UserError/
            // AccessError...) : diagnosticable sans log pour le prochain défaut de ce genre
            // (ex. TypeError de signature, AccessError portefeuille hors périmètre).
            this.notification.add(error.data?.message || error.message || "Impossible de charger le tableau de bord.", {
                type: "danger",
            });
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
        if (topic === "portefeuille" && !this.state.agent.loaded) {
            this.loadAgentPortfolio();
        }
    }

    // ================================================================
    // Onglet "Mon portefeuille"
    // ================================================================

    async loadAgentPortfolio() {
        const agent = this.state.agent;
        agent.loading = true;
        try {
            if (!agent.agents.length) {
                agent.agents = await this.orm.call("microfinance.loan", "get_available_agents", []);
            }
            if (agent.selectedOfficerId === null && agent.agents.length) {
                agent.selectedOfficerId = agent.agents[0].officer_id;
            }
            const officerId = agent.selectedOfficerId;
            if (officerId === null) {
                // Aucun agent dans le périmètre : rien à charger.
                agent.loaded = true;
                return;
            }
            // get_par_buckets_by_agent + get_cumulative_par_by_agent fusionnés en un seul appel
            // (perf portefeuille agent, sous-lot B, docs_dev/perf_portefeuille_agent/) : les deux
            // recalculaient indépendamment le même _par_by_agent_raw() côté serveur.
            // loadAgentTable(0) inclus dans ce même Promise.all (sous-lot D) : attendait
            // auparavant la résolution des 6 autres appels avant de partir, un aller-retour
            // réseau de plus que nécessaire à chaque chargement/changement d'agent.
            const [kpis, monthly, parData, dueDates, history, upcoming] = await Promise.all([
                this.orm.call("microfinance.loan", "get_agent_portfolio_kpis", [officerId]),
                this.orm.call("microfinance.loan", "get_agent_monthly_kpis", [officerId]),
                this.orm.call("microfinance.loan", "get_par_data_by_agent", [officerId]),
                this.orm.call("microfinance.loan", "get_agent_due_dates_panel", [officerId]),
                this.orm.call("microfinance.loan", "get_par_history_by_agent", [officerId]),
                this.orm.call("microfinance.loan", "get_agent_upcoming_disbursements", [officerId]),
                this.loadAgentTable(0),
            ]);
            agent.kpis = kpis;
            agent.monthly = monthly;
            agent.par = parData.buckets[0] || null;
            agent.cumulPar = parData.cumulative[0] || null;
            agent.dueDates = dueDates;
            agent.history = history;
            agent.upcomingDisbursements = upcoming;
            agent.loaded = true;
            // Re-rendu des graphiques de cet onglet avec les nouvelles séries.
            if (this.state.activeTopic === "portefeuille") {
                this.shouldRenderCharts = true;
            }
        } catch (error) {
            // Ne jamais laisser l'onglet "Mon portefeuille" vide en silence (seul l'en-tête
            // restait visible, cf. incident ccl1/Andoharanofotsy) : notifier comme loadDashboard()
            // ci-dessus, ET marquer loaded pour que le template retombe sur les valeurs par
            // défaut sûres (kpis: {}, table: {rows: []}, ...) plutôt que de ne rien afficher.
            agent.loaded = true;
            this.notification.add(error.data?.message || error.message || "Impossible de charger le portefeuille de l'agent.", {
                type: "danger",
            });
            console.error("Microfinance dashboard: agent portfolio loading failed", error);
        } finally {
            agent.loading = false;
        }
    }

    async loadAgentTable(offset) {
        const agent = this.state.agent;
        if (agent.selectedOfficerId === null) {
            return;
        }
        agent.tableLoading = true;
        try {
            const result = await this.orm.call("microfinance.loan", "get_agent_portfolio_table", [
                agent.selectedOfficerId,
                agent.search || null,
                offset || 0,
                MicrofinanceLoanDashboard.PAGE_SIZE,
            ]);
            agent.table = { rows: result.rows, total: result.total, offset: result.offset };
        } finally {
            agent.tableLoading = false;
        }
    }

    onSelectAgent(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.agent.selectedOfficerId = Number.isNaN(value) ? null : value;
        this.state.agent.search = "";
        this.state.agent.tabs = { active: null, loading: false, cache: {} };
        this.state.agent.fundsTab = {
            loading: false, offset: 0,
            filters: { fundId: false, flow: "all", dateFrom: false, dateTo: false },
            cache: {},
        };
        this.loadAgentPortfolio();
    }

    onAgentSearchInput(ev) {
        this.state.agent.search = ev.target.value;
        if (this._agentSearchTimer) {
            clearTimeout(this._agentSearchTimer);
        }
        this._agentSearchTimer = setTimeout(() => this.loadAgentTable(0), 300);
    }

    get agentTablePages() {
        const total = this.state.agent.table.total;
        const size = MicrofinanceLoanDashboard.PAGE_SIZE;
        const pageCount = Math.max(1, Math.ceil(total / size));
        const current = Math.floor((this.state.agent.table.offset || 0) / size) + 1;
        const pages = [];
        for (let p = 1; p <= pageCount; p++) {
            if (p === 1 || p === pageCount || Math.abs(p - current) <= 2) {
                pages.push(p);
            } else if (pages[pages.length - 1] !== "…") {
                pages.push("…");
            }
        }
        return { pages, current, pageCount };
    }

    goToAgentPage(page) {
        if (typeof page !== "number") {
            return;
        }
        this.loadAgentTable((page - 1) * MicrofinanceLoanDashboard.PAGE_SIZE);
    }

    get agentSelectorVisible() {
        return this.state.agent.agents.length > 1;
    }

    get selectedAgentLabel() {
        const found = this.state.agent.agents.find(
            (a) => a.officer_id === this.state.agent.selectedOfficerId
        );
        return found ? found.officer_name : "";
    }

    /** "Nouveau client" : seul chemin de création d'un client. L'action (agent, flag de
     *  création) est construite côté serveur ; aucun id d'agent n'est envoyé d'ici. */
    async openAgentShortcut(kind) {
        if (kind === "new_client") {
            const action = await this.orm.call("microfinance.loan", "get_portfolio_new_client_action", []);
            await this.actionService.doAction(action);
        }
    }

    // ----------------------------------------------------------------
    // Onglets "Mes clients/crédits/remboursements/impayés/échéances/visites"
    // ----------------------------------------------------------------

    /** Clic sur un onglet de la barre "Mon portefeuille" : re-cliquer l'onglet actif le ferme
     *  (choix le plus simple, cf. consigne), sinon l'active et charge ses données si pas déjà
     *  en cache pour cet agent (cache vidé par onSelectAgent au changement d'agent). */
    onPortfolioTabClick(tabId) {
        const tabs = this.state.agent.tabs;
        if (tabs.active === tabId) {
            tabs.active = null;
            return;
        }
        tabs.active = tabId;
        if (tabId === "my_funds") {
            if (!Object.keys(this.state.agent.fundsTab.cache).length) {
                this.loadFundsTab(0);
            }
            return;
        }
        if (!tabs.cache[tabId]) {
            this.loadPortfolioTab(tabId, 0);
        }
    }

    async loadPortfolioTab(tabId, offset) {
        const tabs = this.state.agent.tabs;
        tabs.loading = true;
        try {
            const result = await this.orm.call("microfinance.loan", "get_portfolio_tab", [
                tabId,
                this.state.agent.selectedOfficerId,
                offset || 0,
                MicrofinanceLoanDashboard.PAGE_SIZE,
            ]);
            tabs.cache[tabId] = {
                columns: result.columns, rows: result.rows, total: result.total, offset: result.offset,
            };
        } finally {
            tabs.loading = false;
        }
    }

    // ----------------------------------------------------------------
    // Onglet "Fonds de crédit" (7e onglet)
    // ----------------------------------------------------------------

    /** Clé de cache : combinaison filtres + offset (consigne "cache par combinaison de
     *  filtres") - rejouer les mêmes filtres après être reparti sur un autre onglet ne
     *  recharge pas le serveur. */
    _fundsTabCacheKey(offset) {
        const f = this.state.agent.fundsTab.filters;
        return JSON.stringify({ ...f, offset: offset || 0 });
    }

    get fundsTabData() {
        const f = this.state.agent.fundsTab;
        return f.cache[this._fundsTabCacheKey(f.offset)] || null;
    }

    async loadFundsTab(offset) {
        const f = this.state.agent.fundsTab;
        const key = this._fundsTabCacheKey(offset || 0);
        f.offset = offset || 0;
        if (f.cache[key]) {
            return;
        }
        f.loading = true;
        try {
            const result = await this.orm.call("microfinance.loan", "get_portfolio_tab", [
                "fonds",
                this.state.agent.selectedOfficerId,
                offset || 0,
                MicrofinanceLoanDashboard.PAGE_SIZE,
                f.filters.fundId || false,
                f.filters.flow,
                f.filters.dateFrom || false,
                f.filters.dateTo || false,
            ]);
            f.cache[key] = result;
        } catch (error) {
            this.notification.add(error.data?.message || error.message || "Impossible de charger les fonds de crédit.", {
                type: "danger",
            });
            console.error("Microfinance dashboard: funds tab loading failed", error);
        } finally {
            f.loading = false;
        }
    }

    onFundsSelectFund(fundId) {
        this.state.agent.fundsTab.filters.fundId = fundId || false;
        this.loadFundsTab(0);
    }

    onFundsSelectFlow(flow) {
        this.state.agent.fundsTab.filters.flow = flow;
        this.loadFundsTab(0);
    }

    onFundsDateChange(which, ev) {
        this.state.agent.fundsTab.filters[which] = ev.target.value || false;
        this.loadFundsTab(0);
    }

    onFundsResetFilters() {
        this.state.agent.fundsTab.filters = { fundId: false, flow: "all", dateFrom: false, dateTo: false };
        this.loadFundsTab(0);
    }

    get fundsTabPages() {
        const data = this.fundsTabData;
        const total = data ? data.total_rows : 0;
        const size = MicrofinanceLoanDashboard.PAGE_SIZE;
        const pageCount = Math.max(1, Math.ceil(total / size));
        const current = Math.floor(((data && data.offset) || 0) / size) + 1;
        return { pageCount, current };
    }

    goToFundsPage(page) {
        if (typeof page !== "number") {
            return;
        }
        this.loadFundsTab((page - 1) * MicrofinanceLoanDashboard.PAGE_SIZE);
    }

    /** Lecture seule partout : seules les lignes crédit/allocation (res_model/res_id renvoyés
     *  par le serveur) ouvrent une fiche. */
    openFundsRow(row) {
        if (!row.res_model || !row.res_id) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: row.res_model,
            res_id: row.res_id,
            views: [[this._dashboardFormViewId(row.res_model), "form"]],
            target: "current",
        });
    }

    get fundsModeLabel() {
        const data = this.fundsTabData;
        const fundId = this.state.agent.fundsTab.filters.fundId;
        if (!data) {
            return "";
        }
        if (!fundId) {
            return `Vue agrégée · ${data.funds.length} fonds`;
        }
        const fund = data.funds.find((fd) => fd.id === fundId);
        return fund ? `Fonds ${fund.name}` : "";
    }

    get activePortfolioTab() {
        return this.portfolioTabs.find((t) => t.id === this.state.agent.tabs.active) || null;
    }

    get activePortfolioTabData() {
        const active = this.state.agent.tabs.active;
        return active ? this.state.agent.tabs.cache[active] : null;
    }

    get portfolioTabPages() {
        const data = this.activePortfolioTabData;
        const total = data ? data.total : 0;
        const size = MicrofinanceLoanDashboard.PAGE_SIZE;
        const pageCount = Math.max(1, Math.ceil(total / size));
        const current = Math.floor(((data && data.offset) || 0) / size) + 1;
        return { pageCount, current };
    }

    goToPortfolioTabPage(page) {
        const active = this.state.agent.tabs.active;
        if (!active || typeof page !== "number") {
            return;
        }
        this.loadPortfolioTab(active, (page - 1) * MicrofinanceLoanDashboard.PAGE_SIZE);
    }

    /** Libelle du bouton d'un onglet de la barre "Mon portefeuille" - par defaut le label
     *  statique (TABS), mais surchargeable (cf. patch() d'un module tiers) pour y ajouter par
     *  exemple un compteur une fois l'onglet charge. Indirection generique et triviale : ne
     *  change rien pour les 7 onglets existants. */
    formatPortfolioTabLabel(tab) {
        return tab.label;
    }

    /** Ligne cliquable uniquement pour les onglets marqués `clickable` (clients/crédits/visites,
     *  cf. TABS) : remboursements/impayés/échéances restent en lecture seule. */
    async openPortfolioTabRow(row) {
        const tab = this.activePortfolioTab;
        if (!tab || !tab.clickable) {
            return;
        }
        if (tab.model === "res.partner") {
            const action = await this.orm.call(
                "res.partner", "action_open_microfinance_client_form", [[row.id]]
            );
            await this.actionService.doAction(action);
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: tab.model,
            res_id: row.id,
            views: [[this._dashboardFormViewId(tab.model), "form"]],
            target: "current",
        });
    }

    /** Formate une cellule de tableau d'onglet selon le type déclaré par la colonne
     *  (microfinance.loan.get_portfolio_tab) : many2one -> display_name, money/date -> mêmes
     *  helpers que le reste du dashboard (formatMoney/formatDate), sinon valeur brute. */
    formatTabCell(column, row) {
        const value = row[column.name];
        if (column.type === "many2one") {
            return value ? value[1] : "";
        }
        if (column.type === "money") {
            return this.formatMoney(value);
        }
        if (column.type === "date") {
            return this.formatDate(value);
        }
        return value === false || value === undefined || value === null ? "" : value;
    }

    /** Formulaire sans création/duplication pour `model` (dashboard_form_views, cf.
     *  get_dashboard_data) si connu, sinon vue par défaut (false) en dernier recours. */
    _dashboardFormViewId(model) {
        return this.state.data?.dashboard_form_views?.[model] || false;
    }

    openLoanRecord(loanId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "microfinance.loan",
            res_id: loanId,
            views: [[this._dashboardFormViewId("microfinance.loan"), "form"]],
            target: "current",
        });
    }

    get tiles() {
        return this.state.data?.tiles || [];
    }

    formatTileValue(tile) {
        if (tile.type === "money") {
            return this.formatMoney(tile.value);
        }
        if (tile.type === "percent") {
            return this.formatPercent(tile.value);
        }
        return this.formatNumber(tile.value);
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

    /** Liste ouverte avec EXACTEMENT le domaine qui a servi au calcul de la tuile (renvoyé par
     *  le serveur), sans filtre par défaut : compteur affiché == lignes de la liste. */
    openKpiTile(tile) {
        this._openDomainList(tile.model, tile.domain, tile.label, tile.views);
    }

    openTodayInstallments() {
        const link = this.state.data?.today_installments_link;
        if (link) {
            this._openDomainList(link.model, link.domain, link.label, link.views);
        }
    }

    _openDomainList(model, domain, name, views) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            name,
            views: views || [[false, "list"], [false, "form"]],
            domain,
            context: {},
            target: "current",
        });
    }

    openNewLoan() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "microfinance.loan",
            name: "Nouveau prêt",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllLoans() {
        this.actionService.doAction("microfinance_loan_management.action_microfinance_loan");
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
                    { name: "Allocations", data: data.fond_multi_chart.allocations || [] },
                ],
                xaxis: { categories: data.fond_multi_chart.labels },
                colors: ["#0891b2", "#2563eb", "#7c3aed"],
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

        this.renderAgentCharts(baseChart);
    }

    renderAgentCharts(baseChart) {
        const agent = this.state.agent;
        if (!agent.loaded) {
            return;
        }
        // Donut : répartition de l'encours à risque par tranche d'ancienneté (mesure
        // EXCLUSIVE - un crédit tombe dans une seule tranche).
        const par = agent.par || { labels: [], values: [] };
        this.mountChart(this.agentDonutRef, {
            chart: { ...baseChart, type: "donut", height: 300 },
            series: (par.values || []).map((v) => Number((v || 0).toFixed(1))),
            labels: par.labels || [],
            colors: ["#22c55e", "#eab308", "#f97316", "#ef4444"],
            legend: { position: "bottom" },
            dataLabels: { enabled: true, formatter: (v) => `${Number(v).toFixed(1)}%` },
            plotOptions: { pie: { donut: { size: "68%" } } },
        });
        // Barres : PAR cumulatif (mesure CUMULATIVE - % de l'encours en retard de >= t jours,
        // distincte du donut, monotone décroissante).
        const cumul = agent.cumulPar || { thresholds: [30, 60, 90, 120], values: [] };
        this.mountChart(this.agentCumulParRef, {
            chart: { ...baseChart, type: "bar", height: 280 },
            series: [{ name: "PAR cumulatif", data: (cumul.values || []).map((v) => Number((v || 0).toFixed(1))) }],
            xaxis: { categories: (cumul.thresholds || []).map((t) => `PAR ${t}`) },
            colors: ["#ef4444"],
            plotOptions: { bar: { borderRadius: 5, columnWidth: "45%", dataLabels: { position: "top" } } },
            dataLabels: {
                enabled: true,
                formatter: (v) => `${v}%`,
                offsetY: -20,
                style: { colors: ["#475569"] },
            },
            legend: { show: false },
            yaxis: { labels: { formatter: (v) => `${v}%` } },
            grid: { borderColor: "#e2e8f0" },
        });
        // Ligne : évolution du PAR cumulatif dans le temps (instantanés mensuels).
        if (agent.history?.has_data) {
            this.mountChart(this.agentHistoryRef, {
                chart: { ...baseChart, type: "line", height: 300 },
                series: [
                    { name: "PAR 30", data: agent.history.par30 || [] },
                    { name: "PAR 60", data: agent.history.par60 || [] },
                    { name: "PAR 90", data: agent.history.par90 || [] },
                    { name: "PAR 120", data: agent.history.par120 || [] },
                ],
                xaxis: { categories: agent.history.labels || [] },
                colors: ["#f59e0b", "#f97316", "#ef4444", "#7c3aed"],
                stroke: { width: 2, curve: "smooth" },
                dataLabels: { enabled: false },
                markers: { size: 3 },
                yaxis: { labels: { formatter: (v) => `${Number(v).toFixed(1)}%` } },
                grid: { borderColor: "#e2e8f0" },
            });
        }
    }
}

MicrofinanceLoanDashboard.template = "microfinance_loan_management.MicrofinanceLoanDashboard";
registry.category("actions").add("microfinance_loan_dashboard", MicrofinanceLoanDashboard);
