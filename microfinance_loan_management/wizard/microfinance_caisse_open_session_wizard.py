# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceCaisseOpenSessionWizard(models.TransientModel):
    """Point d'entrée unique de l'ouverture de session depuis l'écran guichet : le bouton
    « Ouvrir une session » (écran bloquant « Aucune session de caisse ouverte ») appelle
    directement l'action qui instancie ce wizard, sans navigation vers un autre menu/modèle.
    À la confirmation, trouve ou crée la session du jour pour l'agence/le journal courant et
    appelle session.action_open_session() — aucun champ ni contrôle propre à ce wizard, il ne
    fait que fournir le point d'entrée direct manquant jusqu'ici (cf. AUDIT_session_zigzag)."""
    _name = 'microfinance.caisse.open.session.wizard'
    _description = "Assistant d'ouverture de session de caisse"

    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Journal de caisse', readonly=True,
        default=lambda self: self.env.company.cash_journal_id,
    )
    date = fields.Date(
        string='Date', required=True, readonly=True, default=fields.Date.context_today,
    )
    cashier_id = fields.Many2one(
        'res.users', string='Caissier', required=True, readonly=True,
        default=lambda self: self.env.user,
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.journal_id:
            raise UserError(_(
                "Aucun journal de caisse guichet n'est configuré pour l'agence %(company)s. "
                "Configurez-le dans Paramètres > Sociétés avant d'ouvrir une session."
            ) % {'company': self.company_id.name})
        session = self.env['microfinance.caisse.session'].search([
            ('journal_id', '=', self.journal_id.id),
            ('date', '=', self.date),
        ], limit=1)
        if not session:
            session = self.env['microfinance.caisse.session'].create({
                'journal_id': self.journal_id.id,
                'date': self.date,
                'company_id': self.company_id.id,
                'cashier_id': self.cashier_id.id,
            })
        session.action_open_session()
        return {'type': 'ir.actions.act_window_close'}
