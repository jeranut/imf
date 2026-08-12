/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

// Rafraîchit uniquement le fil de communication (chatter) après le bouton "Imprimer le
// calendrier de remboursement" : ce bouton poste bien le PDF en pièce jointe côté serveur
// (message_post confirmé fonctionnel), mais son action de retour (display_notification) ne
// déclenche aucun rechargement du formulaire - le chatter reste donc figé sur l'état chargé
// à l'ouverture de la fiche jusqu'à un F5 manuel. On réutilise l'événement MAIL:RELOAD-THREAD
// déjà consommé par le composant Thread du module mail (cf. mail/static/src/core/common/
// thread.js) pour ne recharger que les nouveaux messages, sans toucher au reste du
// formulaire (donc aucun risque sur une saisie en cours ailleurs sur la fiche).
export class MicrofinanceLoanFormController extends FormController {
    async afterExecuteActionButton(clickParams) {
        await super.afterExecuteActionButton(...arguments);
        if (clickParams.name === "action_print_repayment_schedule") {
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
