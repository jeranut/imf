/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { useEffect, useRef } from "@odoo/owl";

// Regroupe les chiffres par blocs de 3 (ex: "123456789012" -> "123 456 789 012"). Les caractères
// non numériques sont ignorés (l'utilisateur peut coller un texte déjà espacé sans souci).
function groupDigits(value) {
    const digits = (value || "").replace(/\D/g, "");
    return digits.replace(/(\d{3})(?=\d)/g, "$1 ");
}

// CharField (et le hook useInputField qu'il utilise) ne committe la valeur au modèle qu'au blur
// ("change"), donc le compute microfinance_id_number_display ne se réévalue naturellement qu'à
// ce moment-là : c'est le mécanisme standard d'Odoo pour tous les champs Char, pas un bug propre
// à ce champ. Pour un espacement visible pendant la frappe, il faut reformater le DOM de
// l'input directement sur l'évènement "input" (à chaque frappe), en plus — pas à la place — du
// mécanisme existant qui reste responsable de committer la valeur au blur.
export class MicrofinanceGroupedDigitsField extends CharField {
    setup() {
        super.setup();
        const inputRef = useRef("input");
        useEffect(
            (inputEl) => {
                if (!inputEl) {
                    return;
                }
                const onInput = () => {
                    const cursor = inputEl.selectionStart;
                    const digitsBeforeCursor = inputEl.value
                        .slice(0, cursor)
                        .replace(/\D/g, "").length;
                    const formatted = groupDigits(inputEl.value);
                    if (formatted === inputEl.value) {
                        return;
                    }
                    inputEl.value = formatted;
                    let pos = 0;
                    let seen = 0;
                    while (pos < formatted.length && seen < digitsBeforeCursor) {
                        if (/\d/.test(formatted[pos])) {
                            seen++;
                        }
                        pos++;
                    }
                    inputEl.setSelectionRange(pos, pos);
                };
                inputEl.addEventListener("input", onInput);
                return () => inputEl.removeEventListener("input", onInput);
            },
            () => [inputRef.el]
        );
    }
}

export const microfinanceGroupedDigitsField = {
    ...charField,
    component: MicrofinanceGroupedDigitsField,
};

registry.category("fields").add("microfinance_grouped_digits", microfinanceGroupedDigitsField);
