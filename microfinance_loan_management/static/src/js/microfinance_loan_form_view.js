/** @odoo-module **/

import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useEffect } from "@odoo/owl";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";

// Boutons qui postent un PDF dans le chatter côté serveur (message_post) mais dont
// l'action de retour (display_notification) ne recharge pas le formulaire : sans ça, le
// chatter reste figé sur l'état chargé à l'ouverture de la fiche jusqu'à un F5 manuel.
// On réutilise l'événement MAIL:RELOAD-THREAD consommé par le composant Thread du module
// mail (cf. mail/static/src/core/common/thread.js) pour ne recharger que les nouveaux
// messages, sans toucher au reste du formulaire (aucun risque sur une saisie en cours).
const CHATTER_REFRESH_BUTTONS = new Set([
    "action_print_repayment_schedule",
    "action_print_contrat_to_chatter",
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

// Barre d'état du dossier de crédit : le widget statusbar natif ne distingue que l'étape
// courante. Ici on ajoute la classe `o_passed` aux étapes situées AVANT l'étape courante
// dans l'ordre du champ selection, pour que la feuille de style du module
// (microfinance_loan_form.scss) puisse les colorer différemment des étapes futures.
// Strictement borné à microfinance.loan / champ state : no-op partout ailleurs.
patch(StatusBarField.prototype, {
    setup() {
        super.setup();
        useEffect(() => {
            if (
                this.props.record.resModel !== "microfinance.loan" ||
                this.props.name !== "state"
            ) {
                return;
            }
            const root = this.rootRef.el;
            if (!root) {
                return;
            }
            const items = this.getAllItems();
            const currentIndex = items.findIndex((item) => item.isSelected);
            root.querySelectorAll(".o_arrow_button:not(.dropdown-toggle)").forEach((btn) => {
                const idx = items.findIndex(
                    (item) => String(item.value) === String(btn.dataset.value)
                );
                btn.classList.toggle(
                    "o_passed",
                    currentIndex > -1 && idx > -1 && idx < currentIndex
                );
            });
        });
    },
});
