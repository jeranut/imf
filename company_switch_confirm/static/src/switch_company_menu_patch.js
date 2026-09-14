/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";

patch(CompanySelector.prototype, {
    /**
     * Le buffer natif `selectedCompaniesIds` sert déjà de sélection en
     * attente (c'est lui qui pilote l'affichage des cases à cocher). On se
     * contente ici de ne plus déclencher d'application automatique sur le
     * mode "toggle" : plus de _debouncedApply(), l'application ne se fait
     * plus que via confirmSelection().
     */
    switchCompany(mode, companyId) {
        if (mode === "toggle") {
            if (this.selectedCompaniesIds.includes(companyId)) {
                this._deselectCompany(companyId);
            } else {
                this._selectCompany(companyId);
            }
            return;
        }
        return super.switchCompany(mode, companyId);
    },

    /** Applique la sélection bufferisée via la méthode native inchangée. */
    confirmSelection() {
        this._apply();
    },

    /** Réinitialise le buffer sur la sélection réellement active. */
    resetSelection() {
        this.selectedCompaniesIds.splice(
            0,
            this.selectedCompaniesIds.length,
            ...this.companyService.activeCompanyIds
        );
    },
});
