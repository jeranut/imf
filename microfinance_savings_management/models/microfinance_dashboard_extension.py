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
    def get_dashboard_data(self, portfolio_id=None):
        data = super().get_dashboard_data(portfolio_id)
        company = self.env.company
        # sudo() limité à cet agrégat : total/compte des comptes épargne actifs de la société,
        # une statistique globale au même titre que le KPI "Fonds bailleurs" (déjà visible de tous
        # les rôles du dashboard) - pas une liste de comptes. Le contrôle d'accès réel (portefeuille
        # demandé visible pour l'appelant) a déjà eu lieu dans super().get_dashboard_data(). Sans ce
        # sudo(), un agent crédit (groupe "Agent crédit", sans accès à microfinance.savings.account,
        # cf. security/ir.model.access.csv) obtient un AccessError ici, qui interrompt tout le
        # calcul et laisse un tableau de bord vide (l'erreur est notifiée côté JS mais plus aucune
        # donnée n'est jamais rendue).
        Account = self.env['microfinance.savings.account'].sudo()
        active_accounts = Account.search([
            ('company_id', '=', company.id), ('state', '=', 'active'),
        ])
        data['kpis']['savings_outstanding_total'] = sum(active_accounts.mapped('balance'))
        data['kpis']['active_savings_account_count'] = len(active_accounts)
        return data
