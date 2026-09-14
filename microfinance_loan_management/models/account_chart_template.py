# -*- coding: utf-8 -*-
from odoo import models

from odoo.addons.microfinance_loan_management.hooks import provision_company_pcec


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo):
        """Après le chargement du plan PCEC 2005 sur une société (onboarding d'une nouvelle
        agence CEFOR : l'utilisateur choisit le pack comptable dans Comptabilité >
        Configuration), crée automatiquement les sous-comptes microfinance dédiés
        (LOAN_NEW_SUBACCOUNTS) et les journaux standards (JOURNALS).

        Sans ce hook, une agence créée après l'installation du module n'aurait ni les comptes
        203001/707301/208xxx/325xxx… ni les journaux CAI/CRE/EPG/BQ*, et les valeurs par
        défaut des produits de crédit (et d'épargne) resteraient vides à la saisie.
        post_init_hook, lui, ne s'exécute qu'à l'installation neuve et n'itère que sur les
        sociétés existantes à cet instant.

        Idempotent (provision_company_pcec => _get_or_create_account / search_count) :
        recharger le plan PCEC sur une agence déjà provisionnée ne recrée rien."""
        res = super()._load(template_code, company, install_demo)
        if template_code == 'mg_pcec':
            provision_company_pcec(self.env, company)
        return res
