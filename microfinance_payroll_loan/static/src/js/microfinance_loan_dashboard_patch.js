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
});

patch(MicrofinanceLoanDashboard.prototype, {
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
