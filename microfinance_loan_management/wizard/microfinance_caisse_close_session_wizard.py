# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceCaisseCloseSessionWizard(models.TransientModel):
    """Assistant de clôture de session avec comptage de billetage (sous-lot B).

    Seul chemin de clôture depuis la fiche session désormais : le bouton direct
    action_close_session est remplacé par celui qui ouvre ce wizard. À la confirmation :
    (1) on rafraîchit la fiche journalière pour ne pas comparer à un solde périmé, (2) on
    crée le microfinance.caisse.comptage (dont la contrainte serveur exige un motif si écart),
    (3) on appelle session.action_close_session() — méthode existante, logique de contrôle
    comptable inchangée. Tout tient dans la transaction du bouton : si (2) ou (3) lève, le
    comptage n'est pas persisté."""
    _name = 'microfinance.caisse.close.session.wizard'
    _description = 'Assistant de clôture de session de caisse (billetage)'

    session_id = fields.Many2one(
        'microfinance.caisse.session', string='Session de caisse', required=True, readonly=True,
    )
    currency_id = fields.Many2one(
        related='session_id.currency_id', string='Devise', readonly=True,
    )
    line_ids = fields.One2many(
        'microfinance.caisse.close.session.wizard.line', 'wizard_id', string='Comptage',
    )
    counted_total = fields.Monetary(
        string='Total compté', compute='_compute_totals',
    )
    # Figé à l'ouverture du wizard (default_get) après un _refresh_amounts() de la fiche :
    # valeur d'affichage. Le snapshot faisant foi est re-calculé dans action_confirm juste
    # avant la création du comptage.
    theoretical_total = fields.Monetary(string='Solde théorique', readonly=True)
    variance = fields.Monetary(
        string='Écart (compté − théorique)', compute='_compute_totals',
    )
    variance_comment = fields.Text(string="Motif de l'écart")

    @api.depends('line_ids.subtotal', 'theoretical_total')
    def _compute_totals(self):
        for wizard in self:
            wizard.counted_total = sum(wizard.line_ids.mapped('subtotal'))
            wizard.variance = wizard.counted_total - wizard.theoretical_total

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        session_id = values.get('session_id') or self.env.context.get('default_session_id') \
            or self.env.context.get('active_id')
        if not session_id:
            return values
        session = self.env['microfinance.caisse.session'].browse(session_id)
        values['session_id'] = session.id
        # Rafraîchissement du solde figé de la fiche avant lecture (cf. AUDIT §2.1 : le nombre
        # affiché au guichet peut être périmé). La fiche est encore 'open' à ce stade.
        if session.fiche_journee_id and session.fiche_journee_id.state == 'open':
            session.fiche_journee_id._refresh_amounts()
        values['theoretical_total'] = session.closing_balance
        denominations = self.env['microfinance.caisse.denomination'].search([
            ('currency_id', '=', session.currency_id.id),
        ])
        values['line_ids'] = [
            (0, 0, {'denomination_id': denomination.id, 'quantity': 0})
            for denomination in denominations
        ]
        return values

    def action_confirm(self):
        self.ensure_one()
        session = self.session_id
        if session.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        # Snapshot faisant foi : re-rafraîchit la fiche (des écritures ont pu être postées
        # depuis l'ouverture du wizard) et relit le solde de clôture.
        if session.fiche_journee_id and session.fiche_journee_id.state == 'open':
            session.fiche_journee_id._refresh_amounts()
        theoretical_total = session.closing_balance
        comptage = self.env['microfinance.caisse.comptage'].create({
            'session_id': session.id,
            'theoretical_total': theoretical_total,
            'variance_comment': self.variance_comment,
            'line_ids': [
                (0, 0, {'denomination_id': line.denomination_id.id, 'quantity': line.quantity})
                for line in self.line_ids
            ],
        })
        # Déclenche comptage._check_variance_comment (motif obligatoire si écart). Puis la
        # clôture proprement dite : si action_close_session lève (écart comptable figé vs
        # réel, séquentialité chronologique), toute la transaction du bouton est annulée et
        # le comptage n'est jamais persisté.
        comptage.flush_recordset()
        session.action_close_session()
        return {'type': 'ir.actions.act_window_close'}


class MicrofinanceCaisseCloseSessionWizardLine(models.TransientModel):
    _name = 'microfinance.caisse.close.session.wizard.line'
    _description = 'Ligne de comptage (assistant de clôture de session)'
    _order = 'denomination_value desc'

    wizard_id = fields.Many2one(
        'microfinance.caisse.close.session.wizard', string='Assistant', required=True,
        ondelete='cascade',
    )
    denomination_id = fields.Many2one(
        'microfinance.caisse.denomination', string='Coupure / pièce', required=True, readonly=True,
    )
    denomination_value = fields.Monetary(
        related='denomination_id.value', string='Valeur faciale', readonly=True,
    )
    quantity = fields.Integer(string='Quantité', default=0)
    subtotal = fields.Monetary(string='Sous-total', compute='_compute_subtotal')
    currency_id = fields.Many2one(
        related='wizard_id.currency_id', string='Devise', readonly=True,
    )

    @api.depends('denomination_id.value', 'quantity')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.denomination_id.value or 0.0) * line.quantity
