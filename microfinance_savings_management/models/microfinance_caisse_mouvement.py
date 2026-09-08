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
        ('frais_dossier', 'Frais de dossier'),
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
    # des trois est renseigné selon `type`, jamais plusieurs.
    payment_id = fields.Many2one('microfinance.loan.payment', string='Remboursement', readonly=True, copy=False)
    savings_transaction_id = fields.Many2one('microfinance.savings.transaction', string='Transaction épargne', readonly=True, copy=False)
    # type == 'frais_dossier' : écriture de règlement des frais de dossier posée par
    # microfinance.loan.action_charge_fee() (= loan.fee_move_id).
    fee_move_id = fields.Many2one('account.move', string='Écriture frais', readonly=True, copy=False)

    def _run_posting_sudo(self, record, session, method_name, *args, **kwargs):
        """Exécute EN SUDO l'unique étape comptabilisante d'une opération de guichet
        (_create_transaction / microfinance.loan.payment.action_post / microfinance.loan.
        action_disburse). Ces méthodes créent/postent un account.move et, pour le crédit,
        écrivent ou créent des microfinance.loan.installment — droits absents du profil
        caissier (group_microfinance_cashier + group_savings_agent) et volontairement NON
        élargis dans ir.model.access (décision Micka Lot 1.1bis, option 2 : sudo ciblé plutôt
        qu'un groupe comptable).

        Le sudo est strictement circonscrit à ce point d'entrée : les méthodes cibles restent
        partagées et non sudo-ées pour tous leurs autres appelants (boutons de formulaire
        finance / épargne, assistant remboursement, crons auto-débit / capitalisation), qui
        portent déjà les droits comptables.

        Défense en profondeur : re-vérifie ICI, au plus près du bypass, que l'enregistrement
        comptabilisé appartient bien à l'agence de la session — sans se reposer uniquement sur
        la garde d'amont de register_operation. `record.company_id` est lu en identité réelle
        (record passé non sudo par l'appelant) ; seule l'exécution de `method_name` passe en
        sudo."""
        record.ensure_one()
        if record.company_id != session.company_id:
            raise UserError(_(
                "Opération de caisse refusée : « %(record)s » n'appartient pas à l'agence "
                "de la session en cours (%(company)s)."
            ) % {'record': record.display_name, 'company': session.company_id.display_name})
        return getattr(record.sudo(), method_name)(*args, **kwargs)

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
            transaction = self._run_posting_sudo(
                account, session, '_create_transaction', transaction_type, amount, payment_method='cash')
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
            # payment.company_id est un related stocké de loan_id.company_id : la
            # re-vérification d'agence dans _run_posting_sudo porte donc bien sur l'agence du
            # crédit remboursé.
            self._run_posting_sudo(payment, session, 'action_post')
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
            # Découplage activation / décaissement (docs_dev/guichet_caisse/AUDIT_decaissement.md) :
            # le guichet ne fait plus que le décaissement effectif (écriture de sortie de caisse
            # + disbursement_date + recalage de l'échéancier). Les contrôles d'éligibilité et le
            # passage à 'active' ont eu lieu au clic « Activer » (action_activate) sur la fiche.
            self._run_posting_sudo(loan, session, 'action_process_disbursement')
            # Le montant réellement sorti de caisse (net des frais nettés éventuels), pas la
            # saisie brute côté UI : action_process_disbursement() ne prend aucun montant en
            # paramètre, il décaisse toujours l'intégralité configurée sur le crédit.
            vals['amount'] = loan.net_disbursed_amount
            vals['loan_id'] = loan.id
        elif type == 'frais_dossier':
            loan = self.env['microfinance.loan'].browse(loan_id)
            if loan.company_id != session.company_id:
                raise UserError(_("Ce crédit n'appartient pas à l'agence de la session en cours."))
            # Gardes métier remontées ici pour un message clair côté guichet (redondantes avec
            # les gardes internes de action_charge_fee : state == 'approved', fee_sent_to_cashier,
            # not fee_paid, fee_amount_due > 0).
            if not loan.fee_sent_to_cashier:
                raise UserError(_("Les frais de ce dossier n'ont pas été envoyés en caisse."))
            if loan.fee_paid:
                raise UserError(_('Les frais de dossier de ce dossier ont déjà été encaissés.'))
            # action_charge_fee() conserve son verrou pessimiste (SELECT ... FOR UPDATE) et
            # toute sa logique (rattrapage engagement, règlement product.fee_journal_id,
            # lettrage). _run_posting_sudo ne fait qu'exécuter cette méthode en sudo (le
            # caissier n'a pas create sur account.move) après re-vérification d'agence.
            self._run_posting_sudo(loan, session, 'action_charge_fee')
            # Relu après l'appel : fee_amount_due est figé (inchangé), fee_move_id vient d'être
            # renseigné par action_charge_fee.
            vals['amount'] = loan.fee_amount_due
            vals['loan_id'] = loan.id
            mouvement = self.create(vals)
            # Lien vers l'account.move de règlement posé en sudo : le caissier n'a aucun droit
            # sur account.move, et ce champ n'est de toute façon lu que dans les vues manager.
            mouvement.sudo().write({'fee_move_id': loan.fee_move_id.id})
            return mouvement
        else:
            raise UserError(_('Type d\'opération de caisse inconnu : %s') % type)
        return self.create(vals)


class MicrofinanceCaisseSession(models.Model):
    _inherit = 'microfinance.caisse.session'

    mouvement_ids = fields.One2many('microfinance.caisse.mouvement', 'session_id', string='Mouvements')
