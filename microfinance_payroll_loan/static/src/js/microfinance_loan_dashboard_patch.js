/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MicrofinanceLoanDashboard } from "@microfinance_loan_management/js/microfinance_loan_dashboard";

// Onglet "Clients a traiter" (decision 2026-10-05, cas bosta) : ajoute depuis le module
// passerelle (microfinance_officer_id, le champ qui qualifie ces clients, est defini ici,
// pas dans microfinance_loan_management) via un patch OWL plutot qu'une copie du composant -
// le rendu (nav, tableau generique de colonnes/lignes) reste entierement dans
// microfinance_loan_dashboard.xml, inchange : get_portfolio_tab (cf. models/microfinance_loan.py
// de ce module) fournit deja columns/rows au bon format pour n'importe quel id d'onglet.
MicrofinanceLoanDashboard.TABS.push({
    id: "clients_a_traiter",
    label: "Clients à traiter",
    model: "res.partner",
    clickable: true,
    // Contexte transmis a l'ouverture de la fiche (cf. patch de openPortfolioTabRow
    // ci-dessous) : expose le bouton "Nouvelle demande de credit" (invisible sans
    // microfinance_context, cf. microfinance_loan_management/views/microfinance_partner_views.xml).
    context: { microfinance_context: true },
});

patch(MicrofinanceLoanDashboard.prototype, {
    // "Mes clients" ouvrait deja la fiche SANS microfinance_context (angle mort pre-existant,
    // signale au passage) : ce patch couvre les deux onglets partner (my_clients ET
    // clients_a_traiter) via tab.context, sans toucher aux onglets credits/visites.
    openPortfolioTabRow(row) {
        const tab = this.activePortfolioTab;
        if (!tab || !tab.clickable) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: tab.model,
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
            context: tab.context || {},
        });
    },

    // Compteur sur l'onglet (lazy, coherent avec le chargement paresseux des autres onglets) :
    // affiche le total une fois le cache rempli (1er clic), vide avant.
    formatPortfolioTabLabel(tab) {
        if (tab.id === "clients_a_traiter") {
            const cached = this.state.agent.tabs.cache[tab.id];
            if (cached) {
                return `${tab.label} (${cached.total})`;
            }
        }
        return tab.label;
    },
});
