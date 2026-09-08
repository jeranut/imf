/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

// Boutons qui postent un PDF dans le chatter côté serveur (message_post) mais dont
// l'action de retour (display_notification) ne recharge pas le formulaire : sans ça, le
// chatter reste figé sur l'état chargé à l'ouverture de la fiche jusqu'à un F5 manuel.
// On réutilise l'événement MAIL:RELOAD-THREAD consommé par le composant Thread du module
// mail (cf. mail/static/src/core/common/thread.js) pour ne recharger que les nouveaux
// messages, sans toucher au reste du formulaire (aucun risque sur une saisie en cours).
const CHATTER_REFRESH_BUTTONS = new Set([
    "action_print_repayment_schedule",
    "action_print_contrat_to_chatter",
    "action_print_carnet_remboursement",
]);

export class MicrofinanceLoanFormController extends FormController {
    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton(...arguments);
        if (CHATTER_REFRESH_BUTTONS.has(clickParams.name)) {
            const record = this.model.root;
            this.env.bus.trigger("MAIL:RELOAD-THREAD", {
                model: record.resModel,
                id: record.resId,
            });
        }
    }
}

export const MicrofinanceLoanFormView = {
    ...formView,
    Controller: MicrofinanceLoanFormController,
};

registry.category("views").add("microfinance_loan_form", MicrofinanceLoanFormView);

// (Barre d'état : la coloration par état se fait entièrement en SCSS via des
// sélecteurs [data-value] sur l'étape courante, cf. microfinance_loan_form.scss —
// plus besoin du patch JS qui ajoutait la classe .o_passed.)
