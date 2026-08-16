# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    microfinance_savings_account_ids = fields.One2many(
        'microfinance.savings.account', 'partner_id', string='Comptes épargne')
    microfinance_savings_count = fields.Integer(compute='_compute_microfinance_savings_count')

    @api.depends('microfinance_savings_account_ids')
    def _compute_microfinance_savings_count(self):
        for partner in self:
            partner.microfinance_savings_count = len(partner.microfinance_savings_account_ids)

    @api.model_create_multi
    def create(self, vals_list):
        # Ouverture du compte épargne principal dès la création du contact client — seul
        # déclencheur désormais (cf. correctif numérotation, décision validée par Micka :
        # l'ancien déclencheur au 1er dossier de crédit, _get_or_create_loan_application, est
        # supprimé). Un client déjà en base avant ce correctif et qui n'a pas encore de compte
        # épargne n'en obtiendra plus automatiquement, même en visant un crédit plus tard —
        # nécessiterait un script de rattrapage séparé, non demandé à ce stade.
        # super().create() remonte jusqu'à res_partner.py (microfinance_loan_management), qui
        # attribue microfinance_account_number avant de revenir ici — condition nécessaire pour
        # que la dérivation du numéro de compte épargne (AGENCE/TYPE/NNNNNN) fonctionne.
        partners = super().create(vals_list)
        if self.env.context.get('microfinance_context'):
            for partner in partners:
                if partner.microfinance_partner_type == 'client':
                    partner._get_or_create_microfinance_savings_principal_account()
        return partners

    def _get_or_create_microfinance_savings_principal_account(self):
        """Ouvre (ou réutilise) le compte d'épargne principal du client sur le produit
        d'épargne par défaut de son agence (res.company.microfinance_savings_default_product_id),
        appelée depuis create() ci-dessus. Idempotent : sans effet si un compte sur ce produit
        existe déjà pour ce client.

        Sans effet non plus si l'agence n'a pas encore configuré de produit d'épargne par défaut
        — choix délibéré, pas une erreur : Micka n'a pas demandé de bloquer la création du client
        dans ce cas, le comportement reste best-effort, jamais bloquant. En revanche une
        notification alerte l'utilisateur dans ce cas précis (demande explicite de Micka,
        2026-08-15) : silencieux en base ne doit pas dire invisible côté agent, sinon l'absence
        de compte épargne passe inaperçue jusqu'à ce qu'un agent la découvre par hasard."""
        self.ensure_one()
        company = self.company_id or self.env.company
        product = company.microfinance_savings_default_product_id
        if not product:
            self._notify_microfinance_savings_default_product_missing(company)
            return False
        Account = self.env['microfinance.savings.account']
        existing = Account.search([
            ('partner_id', '=', self.id), ('product_id', '=', product.id),
        ], limit=1)
        if existing:
            return existing
        return Account.create({
            'partner_id': self.id,
            'product_id': product.id,
            'company_id': company.id,
        })

    def _notify_microfinance_savings_default_product_missing(self, company):
        self.ensure_one()
        message = _(
            "Aucun compte épargne n'a été ouvert pour %(partner)s : l'agence « %(company)s » "
            "n'a pas encore de produit d'épargne par défaut configuré.\n\n"
            "Pour corriger : Réglages → Utilisateurs & Sociétés → Sociétés → %(company)s, "
            "renseigner le champ « Produit d'épargne par défaut » (accès manager crédit "
            "requis). Les prochains clients de cette agence auront alors leur compte ouvert "
            "automatiquement — ce client-ci devra être traité manuellement si un compte est "
            "nécessaire dès maintenant."
        ) % {'partner': self.name, 'company': company.name}
        self.env['bus.bus']._sendone(self.env.user.partner_id, 'simple_notification', {
            'type': 'warning',
            'title': _('Compte épargne non ouvert'),
            'message': message,
            'sticky': True,
        })

    def action_view_microfinance_savings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Épargne',
            'res_model': 'microfinance.savings.account',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
