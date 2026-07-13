/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillUnmount } from "@odoo/owl";

const HEARTBEAT_INTERVAL_MS = 3000;
const STALL_THRESHOLD_MS = 5000;

// Rejoue "action_process_next_step" en boucle côté client (au lieu d'une
// boucle serveur dans une seule requête HTTP) : chaque lot reste une requête
// courte et indépendante, ce qui évite qu'une requête ne dépasse jamais
// limit_time_real, quel que soit le volume total à traiter.
//
// Un heartbeat détecte si la boucle s'est arrêtée silencieusement (onglet mis
// en arrière-plan par le navigateur qui throttle les timers, erreur avalée,
// etc.) alors que le serveur indique toujours state == 'running', et la
// relance automatiquement.
class MicrofinanceDataResetAutoRunner extends Component {
    static template = "microfinance_data_reset_wizard.AutoRunner";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ running: false });
        this.stopRequested = false;
        this.everStarted = false;
        this.loopActive = false;
        this.lastActivity = Date.now();
        this.heartbeat = setInterval(() => this._heartbeatCheck(), HEARTBEAT_INTERVAL_MS);
        onWillUnmount(() => {
            this.stopRequested = true;
            clearInterval(this.heartbeat);
        });
    }

    get wizardState() {
        return this.props.record.data.state;
    }

    async onClickStart() {
        if (this.state.running) {
            return;
        }
        this.everStarted = true;
        this.stopRequested = false;
        this.state.running = true;
        await this._runLoop();
    }

    onClickStop() {
        this.stopRequested = true;
    }

    // Ne relance que si CE navigateur a déjà démarré la boucle au moins une
    // fois (évite que plusieurs onglets ouverts sur le même wizard se
    // mettent tous à appeler action_process_next_step en même temps).
    _heartbeatCheck() {
        if (!this.everStarted || this.stopRequested || this.loopActive) {
            return;
        }
        const stalled = Date.now() - this.lastActivity > STALL_THRESHOLD_MS;
        if (this.wizardState === "running" && stalled) {
            this.state.running = true;
            this._runLoop();
        }
    }

    async _runLoop() {
        if (this.loopActive) {
            return;
        }
        this.loopActive = true;
        const resId = this.props.record.resId;
        try {
            while (!this.stopRequested) {
                this.lastActivity = Date.now();
                try {
                    await this.orm.call("microfinance.data.reset.wizard", "action_process_next_step", [[resId]]);
                } catch (error) {
                    this.state.running = false;
                    await this.props.record.load();
                    throw error;
                }
                this.lastActivity = Date.now();
                await this.props.record.load();
                if (this.wizardState !== "running" || this.stopRequested) {
                    break;
                }
                // Courte pause entre deux lots pour laisser respirer le serveur.
                await new Promise((resolve) => setTimeout(resolve, 400));
            }
        } finally {
            this.loopActive = false;
        }
        this.state.running = false;
    }
}

export const microfinanceDataResetAutoRunner = {
    component: MicrofinanceDataResetAutoRunner,
    supportedTypes: ["integer", "boolean", "char"],
};

registry.category("fields").add("microfinance_data_reset_auto_runner", microfinanceDataResetAutoRunner);
