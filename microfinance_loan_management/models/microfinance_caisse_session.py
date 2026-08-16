# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceCaisseSession(models.Model):
    _name = 'microfinance.caisse.session'
    _description = 'Session de caisse (guichet)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, journal_id'

    journal_id = fields.Many2one(
        'account.journal', string='Journal de caisse', required=True, tracking=True,
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Agence', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    cashier_id = fields.Many2one(
        'res.users', string='Caissier', required=True, tracking=True,
        default=lambda self: self.env.user,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('open', 'Ouverte'),
        ('closed', 'Clôturée'),
    ], string='État', default='draft', required=True, tracking=True)

    # La session ne porte aucun solde propre : elle alimente microfinance.caisse.fiche.journee
    # (1 session = 1 fiche, cf. décisions actées) et se contente de relayer ses montants, plutôt
    # que de dupliquer la logique de calcul déjà en place sur la fiche (_refresh_amounts).
    fiche_journee_id = fields.Many2one(
        'microfinance.caisse.fiche.journee', string='Fiche journalière', readonly=True, copy=False,
    )
    opening_balance = fields.Monetary(related='fiche_journee_id.opening_balance', readonly=True, string="Solde d'ouverture")
    total_debit = fields.Monetary(related='fiche_journee_id.total_debit', readonly=True, string='Total débits du jour')
    total_credit = fields.Monetary(related='fiche_journee_id.total_credit', readonly=True, string='Total crédits du jour')
    closing_balance = fields.Monetary(related='fiche_journee_id.closing_balance', readonly=True, string='Solde de clôture calculé')

    _sql_constraints = [
        ('journal_date_unique', 'unique(journal_id, date)',
         'Une seule session de caisse par journal et par jour.'),
    ]

    def action_open_session(self):
        for session in self:
            if session.state == 'open':
                continue
            if session.state == 'closed':
                raise UserError(_('Cette session est déjà clôturée.'))
            fiche = self.env['microfinance.caisse.fiche.journee'].search([
                ('journal_id', '=', session.journal_id.id),
                ('date', '=', session.date),
            ], limit=1)
            if fiche and fiche.state == 'closed':
                raise UserError(_(
                    "La fiche journalière du %(date)s pour le journal « %(journal)s » est déjà "
                    "clôturée. Un manager doit la rouvrir (motif requis) avant d'ouvrir une "
                    "nouvelle session sur ce journal pour ce jour."
                ) % {'date': session.date, 'journal': session.journal_id.name})
            if not fiche:
                fiche = self.env['microfinance.caisse.fiche.journee'].create({
                    'journal_id': session.journal_id.id,
                    'date': session.date,
                    'company_id': session.company_id.id,
                })
            session.write({'fiche_journee_id': fiche.id, 'state': 'open'})
            session.message_post(body=_('Session ouverte par %s.') % session.cashier_id.name)

    def action_close_session(self):
        for session in self:
            if session.state != 'open':
                raise UserError(_('Seule une session ouverte peut être clôturée.'))
            # Ne redéclenche aucun contrôle ici : action_close_day() porte déjà la
            # séquentialité chronologique et la vérification d'écart de solde. Une erreur levée
            # ici doit remonter telle quelle à l'utilisateur, sans quoi state='closed' n'est
            # jamais écrit — la session reste 'open' tant que la fiche n'est pas réellement
            # clôturée.
            session.fiche_journee_id.action_close_day()
            session.write({'state': 'closed'})
            session.message_post(body=_('Session clôturée par %s.') % self.env.user.name)
