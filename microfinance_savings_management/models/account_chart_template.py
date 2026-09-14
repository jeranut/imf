# -*- coding: utf-8 -*-
from odoo import models

from odoo.addons.microfinance_savings_management.hooks import provision_company_savings_accounts


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo):
        """Après le chargement du plan PCEC 2005 sur une société, crée les sous-comptes
        épargne dédiés (213001/2/3, 607301/2/3, 325005/6/7, 218001/2/3, 749003/4, 717004,
        467000) pour que les valeurs par défaut de microfinance.savings.product se résolvent
        sans saisie manuelle (sinon les champs Épargne Individuel/Groupe/Entreprise et
        Intérêts s'affichent vides, en rouge, sur une agence nouvellement créée).

        S'exécute après le hook homonyme de microfinance_loan_management (super()._load, MRO :
        savings -> loan -> account) : les journaux EPG/CAI/BQEP existent donc déjà lorsque ce
        code tourne. Idempotent (_get_or_create_account : search par code + société avant
        création)."""
        res = super()._load(template_code, company, install_demo)
        if template_code == 'mg_pcec':
            provision_company_savings_accounts(self.env, company)
        return res
