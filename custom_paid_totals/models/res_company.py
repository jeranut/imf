from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    advance_payment_account_id = fields.Many2one(
        "account.account",
        string="Compte d'attente avance sur payment",
        domain="[('deprecated', '=', False)]",
    )

    cash_journal_id = fields.Many2one(
        "account.journal",
        string="Journal de caisse",
        domain="[('type', '=', 'cash'), ('company_id', '=', id)]",
        check_company=True,
        help="Journal de caisse physique/comptable de la société, utilisé "
             "pour résoudre le compte de trésorerie réel lors de la clôture "
             "caisse. Volontairement explicite : une recherche implicite "
             "(journal de type cash) serait fragile (journal archivé, de "
             "test, ou future société multi-caisses).",
    )

    def _get_cash_treasury_account(self):
        """Compte de trésorerie réelle de la caisse, utilisé pour la clôture
        (account.daily.balance.action_cloturer)."""
        self.ensure_one()
        if not self.cash_journal_id:
            raise UserError(_(
                "Veuillez configurer le journal de caisse de la société "
                "(Trésorerie ⚙ Configuration) avant de clôturer la caisse."
            ))
        account = self.cash_journal_id.default_account_id
        if not account:
            raise UserError(_(
                "Le journal de caisse « %(journal)s » n'a pas de compte "
                "comptable par défaut configuré.",
                journal=self.cash_journal_id.display_name,
            ))
        return account

    def _get_cash_suspense_accounts(self):
        """Comptes d'attente (Encaissements/Décaissements) réellement utilisés
        par le moteur de paiement standard d'Odoo (res.company.
        account_journal_payment_debit_account_id / _credit_account_id),
        tant qu'aucune ligne de méthode de paiement ne les surcharge.

        Volontairement PAS un nouveau champ dédié : n'importe quel paiement
        caisse ou Mobile Money passe par ces comptes natifs, donc les
        réutiliser garantit qu'on réconcilie toujours le compte réellement
        débité/crédité, plutôt qu'un compte configuré séparément qui
        pourrait diverger silencieusement.
        """
        self.ensure_one()
        receipts_account = self.account_journal_payment_debit_account_id
        payments_account = self.account_journal_payment_credit_account_id
        if not receipts_account or not payments_account:
            raise UserError(_(
                "Veuillez configurer les comptes d'attente d'encaissement et "
                "de décaissement (Comptabilité ⚙ Configuration > Paiements "
                "clients / Paiements fournisseurs) avant de clôturer la "
                "caisse."
            ))
        return receipts_account, payments_account
