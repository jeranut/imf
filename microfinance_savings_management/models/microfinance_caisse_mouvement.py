# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MicrofinanceCaisseMouvement(models.Model):
    _name = 'microfinance.caisse.mouvement'
    _description = 'Mouvement de caisse (ligne de ticket guichet)'
    _order = 'id desc'

    # Vit dans microfinance_savings_management (et non microfinance_loan_management, où vit
    # pourtant microfinance.caisse.session) : ce modèle référence à la fois microfinance.loan
    # (crédit) et microfinance.savings.account/transaction (épargne). microfinance_loan_management
    # ne dépend pas de microfinance_savings_management (c'est l'inverse), donc seul ce module peut
    # voir les deux mondes sans dépendance circulaire. mouvement_ids est ajouté sur
    # microfinance.caisse.session par _inherit ci-dessous, dans ce même fichier.
    session_id = fields.Many2one(
        'microfinance.caisse.session', string='Session de caisse', required=True,
        ondelete='restrict', index=True,
    )
    company_id = fields.Many2one(related='session_id.company_id', store=True, readonly=True)
    currency_id = fields.Many2one(related='session_id.currency_id', readonly=True)
    cashier_id = fields.Many2one(
        'res.users', string='Caissier', required=True, default=lambda self: self.env.user,
    )
    type = fields.Selection([
        ('depot_epargne', 'Dépôt épargne'),
        ('retrait_epargne', 'Retrait épargne'),
        ('remboursement_credit', 'Remboursement crédit'),
        ('decaissement_credit', 'Décaissement crédit'),
    ], string='Type', required=True)
    partner_id = fields.Many2one('res.partner', string='Client', required=True)
    amount = fields.Monetary(string='Montant', required=True)

    # Renseignés selon `type` uniquement (l'un ou l'autre, jamais les deux) — pas de contrainte
    # de cohérence ici : les méthodes du Lot 3, seules créatrices de ces enregistrements, savent
    # déjà quel champ remplir pour quel type et ne mélangent pas les deux.
    savings_account_id = fields.Many2one('microfinance.savings.account', string='Compte épargne')
    loan_id = fields.Many2one('microfinance.loan', string='Crédit')

    # Ventilation, pertinente uniquement pour type == 'remboursement_credit' : simple reflet du
    # résultat déjà calculé et posé par microfinance.loan.payment._allocate_to_installments()
    # (Lot 0), pas un second calcul.
    interest_amount = fields.Monetary(string='Dont intérêt')
    principal_amount = fields.Monetary(string='Dont principal')
    penalty_amount = fields.Monetary(string='Dont pénalité')

    # Traçabilité vers l'enregistrement métier réellement créé et comptabilisé (Lot 3) — un seul
    # des deux est renseigné selon `type`, jamais les deux.
    payment_id = fields.Many2one('microfinance.loan.payment', string='Remboursement', readonly=True, copy=False)
    savings_transaction_id = fields.Many2one('microfinance.savings.transaction', string='Transaction épargne', readonly=True, copy=False)

    @api.model
    def register_operation(self, session_id, type, partner_id, amount, savings_account_id=False, loan_id=False):
        """Point d'entrée unique du guichet (Lot 3.3) : exécute l'opération via les mécanismes
        déjà existants (transaction épargne, remboursement crédit, décaissement crédit) sans
        aucune comptabilisation propre à ce modèle, puis trace le résultat dans un
        microfinance.caisse.mouvement rattaché à la session. Refuse toute opération hors session
        ouverte."""
        session = self.env['microfinance.caisse.session'].browse(session_id)
        if not session.exists() or session.state != 'open':
            raise UserError(_("Aucune session de caisse ouverte : impossible d'enregistrer une opération."))
        partner = self.env['res.partner'].browse(partner_id)
        vals = {
            'session_id': session.id,
            'type': type,
            'partner_id': partner.id,
            'amount': amount,
        }
        if type in ('depot_epargne', 'retrait_epargne'):
            account = self.env['microfinance.savings.account'].browse(savings_account_id)
            if account.company_id != session.company_id:
                raise UserError(_("Ce compte épargne n'appartient pas à l'agence de la session en cours."))
            transaction_type = 'deposit' if type == 'depot_epargne' else 'withdrawal'
            transaction = account._create_transaction(transaction_type, amount, payment_method='cash')
            vals.update({'savings_account_id': account.id, 'savings_transaction_id': transaction.id})
        elif type == 'remboursement_credit':
            loan = self.env['microfinance.loan'].browse(loan_id)
            if loan.company_id != session.company_id:
                raise UserError(_("Ce crédit n'appartient pas à l'agence de la session en cours."))
            payment = self.env['microfinance.loan.payment'].create({
                'loan_id': loan.id,
                'amount': amount,
                'journal_id': session.journal_id.id,
            })
            payment.action_post()
            vals.update({
                'loan_id': loan.id,
                'payment_id': payment.id,
                'interest_amount': payment.allocated_interest,
                'principal_amount': payment.allocated_principal,
                'penalty_amount': payment.allocated_penalty,
            })
        elif type == 'decaissement_credit':
            loan = self.env['microfinance.loan'].browse(loan_id)
            if loan.company_id != session.company_id:
                raise UserError(_("Ce crédit n'appartient pas à l'agence de la session en cours."))
            loan.action_disburse()
            # Le montant réellement sorti de caisse (net des frais nettés éventuels), pas la
            # saisie brute côté UI : action_disburse() ne prend aucun montant en paramètre, il
            # décaisse toujours l'intégralité configurée sur le crédit.
            vals['amount'] = loan.net_disbursed_amount
            vals['loan_id'] = loan.id
        else:
            raise UserError(_('Type d\'opération de caisse inconnu : %s') % type)
        return self.create(vals)


class MicrofinanceCaisseSession(models.Model):
    _inherit = 'microfinance.caisse.session'

    mouvement_ids = fields.One2many('microfinance.caisse.mouvement', 'session_id', string='Mouvements')
