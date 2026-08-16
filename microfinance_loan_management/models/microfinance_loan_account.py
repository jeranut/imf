# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanAccount(models.Model):
    """Conteneur léger regroupant l'historique des crédits (microfinance.loan) d'un client, par
    société. Symétrique à microfinance.savings.account dans son rôle (conteneur stable
    au-dessus des instances), sans en reproduire la complexité : pas de solde, pas de
    transactions, pas de statut, pas de plafond — volontairement absent tant qu'aucune logique
    métier n'a été demandée dessus (décision validée par Micka, cf. correctif numérotation)."""
    _name = 'microfinance.loan.account'
    _description = 'Compte crédit microfinance (conteneur historique)'
    _order = 'id desc'

    name = fields.Char(string='Référence', default='Nouveau', copy=False, readonly=True, required=True)
    partner_id = fields.Many2one('res.partner', string='Titulaire', required=True)
    company_id = fields.Many2one('res.company', string='Société', default=lambda self: self.env.company, required=True)
    loan_ids = fields.One2many('microfinance.loan', 'loan_account_id', string='Crédits')
    loan_count = fields.Integer(compute='_compute_loan_count')

    _sql_constraints = [
        ('partner_company_unique', 'unique(partner_id, company_id)',
         "Un client ne peut avoir qu'un seul compte crédit par société."),
    ]

    @api.depends('loan_ids')
    def _compute_loan_count(self):
        for account in self:
            account.loan_count = len(account.loan_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                vals['name'] = self._get_loan_account_name(company, partner)
        return super().create(vals_list)

    def _get_loan_account_name(self, company, partner):
        """Calquée sur microfinance.savings.account._get_savings_account_name(), mais sans
        segment TYPE (décision Micka : pas de notion de type de compte crédit à représenter dans
        la référence, contrairement à l'épargne I/G/T). Reprend directement le numéro de compte
        permanent du client (partner.microfinance_account_number, format AGENCE/NNNNNN, attribué
        une seule fois à la création du client) tant qu'aucun compte crédit n'existe déjà sous ce
        nom (garde-fou défensif : ne devrait jamais se produire vu l'unicité du numéro de compte
        permanent, mais les deux mécanismes - dérivation directe et séquence indépendante
        ci-dessous - partagent le même espace de noms sans se coordonner entre eux, même
        raisonnement que côté épargne). Contrairement à l'épargne, jamais de "compte
        supplémentaire du même type" ici (contrainte partner_company_unique) : le repli sur la
        séquence indépendante ne sert donc que pour un client sans numéro de compte permanent
        encore attribué (ex. pas encore microfinance_partner_type == 'client' au moment de
        l'appel)."""
        if partner.microfinance_account_number:
            candidate = partner.microfinance_account_number
            if not self.search_count([('name', '=', candidate)]):
                return candidate
        return self._get_next_available_loan_account_name(company)

    def _get_next_available_loan_account_name(self, company):
        while True:
            number = company._get_or_create_numbering_sequence('microfinance.loan.account')
            candidate = '%s/%s' % (company.agency_code, number)
            if not self.search_count([('name', '=', candidate)]):
                return candidate
