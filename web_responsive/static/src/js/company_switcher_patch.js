/** @odoo-module **/
/* Copyright 2026
 * License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl). */

import {
    SwitchCompanyItem,
    SwitchCompanyMenu,
} from "@web/webclient/switch_company_menu/switch_company_menu";
import {onWillStart, useChildSubEnv, useState} from "@odoo/owl";
import {patch} from "@web/core/utils/patch";
import {useService} from "@web/core/utils/hooks";

function normalize(value) {
    return (value || "").toString().toLocaleLowerCase();
}

function companyText(company) {
    return [company.name, company.display_name, company.code, company.company_code]
        .filter(Boolean)
        .join(" ");
}

function companyLabel(company) {
    return company.display_name || company.name || "";
}

function companyCode(company) {
    return company.code || company.company_code || "";
}

function sortCompanies(companyService, companyIds) {
    return companyIds
        .map((companyId) => companyService.getCompany(companyId))
        .filter(Boolean)
        .sort((company1, company2) =>
            companyLabel(company1).localeCompare(companyLabel(company2), undefined, {
                sensitivity: "base",
            })
        );
}

async function enrichCompanies(orm, companyService) {
    const companies = Object.values(companyService.allowedCompaniesWithAncestors);
    const companyIds = companies.map((company) => company.id);
    if (!companyIds.length) {
        return;
    }

    let fields = ["display_name"];
    try {
        const fieldsInfo = await orm.call("res.company", "fields_get", [
            ["display_name", "code", "company_code"],
            ["string"],
        ]);
        fields = fields.concat(["code", "company_code"].filter((fieldName) => fieldsInfo[fieldName]));
    } catch {
        // Keep the switcher usable even if metadata cannot be fetched.
    }

    let companyData = [];
    try {
        companyData = await orm.searchRead("res.company", [["id", "in", companyIds]], fields);
    } catch {
        try {
            companyData = await orm.searchRead("res.company", [["id", "in", companyIds]], [
                "display_name",
            ]);
        } catch {
            return;
        }
    }

    for (const data of companyData) {
        const company = companyService.allowedCompaniesWithAncestors[data.id];
        if (company) {
            Object.assign(company, data);
        }
    }
}

function patchSwitchCompanyMenu(MenuClass) {
    patch(MenuClass.prototype, {
        setup() {
            super.setup();
            this.orm = useService("orm");
            this.webResponsiveCompanySwitcher = useState({
                search: "",
                enriched: false,
            });
            useChildSubEnv({
                webResponsiveCompanySwitcher: this.webResponsiveCompanySwitcher,
            });
            onWillStart(async () => {
                await enrichCompanies(this.orm, this.companyService);
                this.webResponsiveCompanySwitcher.enriched = true;
            });
        },

        get companySearchValue() {
            return this.webResponsiveCompanySwitcher.search;
        },

        get sortedRootCompanies() {
            const rootCompanyIds = Object.values(this.companyService.allowedCompaniesWithAncestors)
                .filter((company) => !company.parent_id)
                .map((company) => company.id);
            return sortCompanies(this.companyService, rootCompanyIds);
        },

        get sortedFilteredRootCompanies() {
            return this.sortedRootCompanies.filter((company) => this.companyMatchesSearch(company));
        },

        onCompanySearchInput(ev) {
            this.webResponsiveCompanySwitcher.search = ev.target.value;
        },

        clearCompanySearch() {
            this.webResponsiveCompanySwitcher.search = "";
        },

        getCompanyLabel(company) {
            return companyLabel(company);
        },

        getCompanyCode(company) {
            return companyCode(company);
        },

        companyMatchesSearch(company) {
            if (!company) {
                return false;
            }
            const query = normalize(this.companySearchValue);
            if (!query) {
                return true;
            }
            if (normalize(companyText(company)).includes(query)) {
                return true;
            }
            return company.child_ids.some((childId) =>
                this.companyMatchesSearch(this.companyService.getCompany(childId))
            );
        },
    });
}

function patchSwitchCompanyItem(ItemClass) {
    patch(ItemClass.prototype, {
        get companySearchValue() {
            return this.env.webResponsiveCompanySwitcher?.search || "";
        },

        get companyLabel() {
            return companyLabel(this.props.company);
        },

        get companyCode() {
            return companyCode(this.props.company);
        },

        get companyLogoUrl() {
            return `/web/image/res.company/${this.props.company.id}/logo`;
        },

        get visibleChildCompanies() {
            return sortCompanies(this.companyService, this.props.company.child_ids).filter((company) =>
                this.companyMatchesSearch(company)
            );
        },

        companyMatchesSearch(company) {
            if (!company) {
                return false;
            }
            const query = normalize(this.companySearchValue);
            if (!query) {
                return true;
            }
            if (normalize(companyText(company)).includes(query)) {
                return true;
            }
            return company.child_ids.some((childId) =>
                this.companyMatchesSearch(this.companyService.getCompany(childId))
            );
        },
    });
}

patchSwitchCompanyMenu(SwitchCompanyMenu);
patchSwitchCompanyItem(SwitchCompanyItem);
