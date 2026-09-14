# -*- coding: utf-8 -*-
from odoo import api, models


class MicrofinanceLoan(models.Model):
    """Ajout des KPI épargne au tableau de bord Microfinance.

    Historique : surcharge portée jusqu'ici par le contrôleur HTTP
    MicrofinanceSavingsDashboardController (sous-classe du contrôleur du module crédit).
    Depuis la migration de l'endpoint vers microfinance.loan.get_dashboard_data
    (méthode de modèle appelée via orm.call, réactive au sélecteur multi-société), la
    surcharge redevient un simple super() Python — et reste dans le module épargne,
    conformément à la dépendance à sens unique (le module crédit n'importe jamais le
    module épargne).
    """
    _inherit = 'microfinance.loan'

    @api.model
    def get_dashboard_data(self):
        data = super().get_dashboard_data()
        company = self.env.company
        Account = self.env['microfinance.savings.account']
        active_accounts = Account.search([
            ('company_id', '=', company.id), ('state', '=', 'active'),
        ])
        data['kpis']['savings_outstanding_total'] = sum(active_accounts.mapped('balance'))
        data['kpis']['active_savings_account_count'] = len(active_accounts)
        return data
