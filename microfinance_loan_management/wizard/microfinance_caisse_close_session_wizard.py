# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceCaisseCloseSessionWizard(models.TransientModel):
    """Assistant de clôture de session — TEMPS 1 : comptage de billetage (sous-lot B, revu en
    3 temps). Seul point d'entrée de la clôture, appelé directement par le bouton « Fermer la
    caisse » de l'en-tête du guichet (session.action_open_close_wizard()).

    Le solde théorique n'existe PAS sur ce modèle : il ne doit être ni calculé ni transmis au
    client avant le temps 3 (cf. AUDIT_session_close_3temps), pour qu'un utilisateur inspectant
    le réseau ne puisse pas le voir pendant la saisie. Seul « Total compté » est visible ici.

    action_confirm_count() ouvre le temps 2 (récapitulatif, sans théorique ni écart) ; c'est
    seulement au temps 2 -> temps 3 (recap.wizard.action_confirm_recap()) que le théorique est
    calculé pour la première fois, côté serveur uniquement."""
    _name = 'microfinance.caisse.close.session.wizard'
    _description = 'Assistant de clôture de session de caisse — comptage'

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
        string='Total compté', compute='_compute_counted_total',
    )
    # Motif d'écart : n'est saisi qu'au temps 3 (variance.wizard.variance_comment), mais doit
    # survivre à un aller-retour temps3 -> temps1 (action_back) et à la reprise d'un brouillon
    # persistant (cf. microfinance_caisse_comptage_brouillon.py) - stocké ici pour que
    # recap.wizard puis variance.wizard le retransmettent à chaque recréation.
    variance_comment = fields.Text(string="Motif de l'écart")
    is_recovered_draft = fields.Boolean(
        string='Brouillon retrouvé', default=False,
        help="Un comptage en cours pour cette session a été retrouvé et pré-rempli ci-dessous.",
    )
    draft_date = fields.Datetime(string='Comptage sauvegardé le')

    @api.depends('line_ids.subtotal')
    def _compute_counted_total(self):
        for wizard in self:
            wizard.counted_total = sum(wizard.line_ids.mapped('subtotal'))

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        session_id = values.get('session_id') or self.env.context.get('default_session_id') \
            or self.env.context.get('active_id')
        if not session_id:
            return values
        session = self.env['microfinance.caisse.session'].browse(session_id)
        values['session_id'] = session.id
        denominations = self.env['microfinance.caisse.denomination'].search([
            ('currency_id', '=', session.currency_id.id),
        ])
        brouillon = self.env['microfinance.caisse.comptage.brouillon'].search([
            ('session_id', '=', session.id),
        ], limit=1)
        quantities_by_denomination = {
            line.denomination_id.id: line.quantity for line in brouillon.line_ids
        }
        values['line_ids'] = [
            (0, 0, {
                'denomination_id': denomination.id,
                'quantity': quantities_by_denomination.get(denomination.id, 0),
            })
            for denomination in denominations
        ]
        if brouillon:
            values['variance_comment'] = brouillon.variance_comment
            values['is_recovered_draft'] = True
            values['draft_date'] = brouillon.write_date
        return values

    @api.model_create_multi
    def create(self, vals_list):
        """Ne fait jamais confiance aux commandes line_ids telles qu'envoyées par le client au
        moment de la sauvegarde implicite du formulaire (bouton « Confirmer le comptage ») :
        un utilisateur a pu constater une ValidationError "denomination_id requis" à ce
        moment-là, alors que default_get() les renseigne pourtant correctement à l'ouverture
        (vérifié par rejeu du RPC onchange() réel) - la cause précise côté client n'a pas pu
        être établie avec certitude, donc plutôt que de dépendre du mécanisme de sauvegarde du
        widget de liste éditable, on reconstruit ici une ligne garantie par coupure active de
        la devise de la session, en ne retenant du payload client QUE les quantités saisies
        (par denomination_id si présent, sinon par position dans la liste - le tableau n'est
        jamais réordonné par l'utilisateur, aucun tri/drag&drop sur cette vue)."""
        for vals in vals_list:
            if 'line_ids' in vals:
                vals['line_ids'] = self._rebuild_line_commands(vals)
        return super().create(vals_list)

    def _rebuild_line_commands(self, vals):
        session_id = vals.get('session_id') or self.env.context.get('default_session_id') \
            or self.env.context.get('active_id')
        if not session_id:
            return vals.get('line_ids') or []
        session = self.env['microfinance.caisse.session'].browse(session_id)
        if not session.exists():
            return vals.get('line_ids') or []
        quantities_by_denomination = {}
        quantities_by_position = {}
        for index, command in enumerate(vals.get('line_ids') or []):
            if not isinstance(command, (list, tuple)) or len(command) < 3 or not isinstance(command[2], dict):
                continue
            command_vals = command[2]
            quantity = command_vals.get('quantity') or 0
            denomination_id = command_vals.get('denomination_id')
            if denomination_id:
                quantities_by_denomination[denomination_id] = quantity
            else:
                quantities_by_position[index] = quantity
        denominations = self.env['microfinance.caisse.denomination'].search([
            ('currency_id', '=', session.currency_id.id),
        ])
        return [
            (0, 0, {
                'denomination_id': denomination.id,
                'quantity': quantities_by_denomination.get(
                    denomination.id, quantities_by_position.get(index, 0)),
            })
            for index, denomination in enumerate(denominations)
        ]

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Comptage de billetage'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def action_confirm_count(self):
        """Ouvre le temps 2 (récapitulatif). Ne calcule rien côté théorique/écart — se contente
        de vérifier que la session est toujours ouverte avant de faire progresser le flux."""
        self.ensure_one()
        if self.session_id.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        self._save_draft()
        recap = self.env['microfinance.caisse.close.session.recap.wizard'].create({
            'source_wizard_id': self.id,
        })
        return recap._reopen_action()

    def _save_draft(self):
        """Persiste l'état courant (quantités + motif) dans le brouillon de la session, pour
        qu'il survive à une fermeture de la fenêtre avant la confirmation finale. Appelé aux
        transitions d'étape du wizard, pas à chaque saisie clavier."""
        self.ensure_one()
        self.env['microfinance.caisse.comptage.brouillon']._save_draft(
            self.session_id,
            [
                {'denomination_id': line.denomination_id.id, 'quantity': line.quantity}
                for line in self.line_ids
            ],
            self.variance_comment,
        )


class MicrofinanceCaisseCloseSessionRecapWizard(models.TransientModel):
    """TEMPS 2 : récapitulatif du billetage compté, SANS théorique ni écart (aucun des deux
    champs n'existe sur ce modèle : rien à transmettre au client tant que l'utilisateur n'a pas
    confirmé ce récapitulatif). line_ids/counted_total sont des `related` en lecture seule vers
    le wizard de comptage (temps 1) : aucune donnée dupliquée, la caissière peut encore revenir
    en arrière et modifier les quantités sur l'enregistrement d'origine (action_back)."""
    _name = 'microfinance.caisse.close.session.recap.wizard'
    _description = 'Assistant de clôture de session de caisse — récapitulatif'

    source_wizard_id = fields.Many2one(
        'microfinance.caisse.close.session.wizard', string='Comptage', required=True, readonly=True,
    )
    session_id = fields.Many2one(related='source_wizard_id.session_id', readonly=True)
    currency_id = fields.Many2one(related='source_wizard_id.currency_id', readonly=True)
    line_ids = fields.One2many(
        'microfinance.caisse.close.session.wizard.line', compute='_compute_line_ids',
        string='Comptage',
    )
    counted_total = fields.Monetary(related='source_wizard_id.counted_total', readonly=True)

    @api.depends('source_wizard_id.line_ids.subtotal')
    def _compute_line_ids(self):
        for wizard in self:
            wizard.line_ids = wizard.source_wizard_id.line_ids

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Récapitulatif du comptage'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def action_back(self):
        """Retour au temps 1 (comptage) : réouvre le MÊME enregistrement de comptage, quantités
        déjà saisies conservées — rien n'est recréé ni perdu."""
        self.ensure_one()
        return self.source_wizard_id._reopen_action()

    def action_confirm_recap(self):
        """Bascule vers le temps 3 : c'est ICI, et seulement ici, que le solde théorique de la
        session est calculé pour la première fois (session.theoretical_balance, non stocké,
        jamais périmé - cf. AUDIT_session_zigzag). Rien avant ce point n'a jamais transmis cette
        valeur au client."""
        self.ensure_one()
        session = self.session_id
        if session.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        session.invalidate_recordset(['theoretical_balance'])
        variance_wizard = self.env['microfinance.caisse.close.session.variance.wizard'].create({
            'source_wizard_id': self.source_wizard_id.id,
            'theoretical_total': session.theoretical_balance,
            'variance_comment': self.source_wizard_id.variance_comment,
        })
        return variance_wizard._reopen_action()


class MicrofinanceCaisseCloseSessionVarianceWizard(models.TransientModel):
    """TEMPS 3 : révélation du solde théorique et de l'écart, saisie du motif si nécessaire,
    confirmation finale (verrouille la session). theoretical_total est figé à la création de CE
    wizard (par recap.wizard.action_confirm_recap()) pour l'affichage ; action_confirm_close()
    le relit toujours frais au moment de conclure (même principe « snapshot faisant foi » que
    l'ancien wizard à un seul temps), pour ne jamais clôturer sur une valeur périmée."""
    _name = 'microfinance.caisse.close.session.variance.wizard'
    _description = "Assistant de clôture de session de caisse — écart"

    source_wizard_id = fields.Many2one(
        'microfinance.caisse.close.session.wizard', string='Comptage', required=True, readonly=True,
    )
    session_id = fields.Many2one(related='source_wizard_id.session_id', readonly=True)
    currency_id = fields.Many2one(related='source_wizard_id.currency_id', readonly=True)
    line_ids = fields.One2many(
        'microfinance.caisse.close.session.wizard.line', compute='_compute_line_ids',
        string='Comptage',
    )
    counted_total = fields.Monetary(related='source_wizard_id.counted_total', readonly=True)
    theoretical_total = fields.Monetary(string='Solde théorique', readonly=True)
    variance = fields.Monetary(
        string='Écart (compté − théorique)', compute='_compute_variance',
    )
    variance_comment = fields.Text(string="Motif de l'écart")

    @api.depends('source_wizard_id.line_ids.subtotal')
    def _compute_line_ids(self):
        for wizard in self:
            wizard.line_ids = wizard.source_wizard_id.line_ids

    @api.depends('counted_total', 'theoretical_total')
    def _compute_variance(self):
        for wizard in self:
            wizard.variance = wizard.counted_total - wizard.theoretical_total

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Écart de caisse'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
        }

    def action_back(self):
        """Retour au temps 1 (comptage), pas au récapitulatif intermédiaire : quantités déjà
        saisies conservées sur le même enregistrement source_wizard_id. Le motif éventuellement
        déjà tapé ici est reporté sur le comptage (temps 1) puis sur le brouillon persistant,
        pour ne pas le perdre si la fenêtre est fermée juste après ce retour."""
        self.ensure_one()
        self.source_wizard_id.variance_comment = self.variance_comment
        self.source_wizard_id._save_draft()
        return self.source_wizard_id._reopen_action()

    def action_confirm_close(self):
        self.ensure_one()
        session = self.session_id
        if session.state != 'open':
            raise UserError(_('Seule une session ouverte peut être clôturée.'))
        # Snapshot faisant foi, relu ici plutôt que réutilisé depuis la création de ce wizard
        # (temps 2->3) : des mouvements ont pu être enregistrés depuis.
        session.invalidate_recordset(['theoretical_balance'])
        theoretical_total = session.theoretical_balance
        counted_total = self.counted_total
        variance = counted_total - theoretical_total
        if abs(variance) > 0.01 and not (self.variance_comment or '').strip():
            raise UserError(_(
                "Le comptage présente un écart de %(variance).2f par rapport au solde "
                "théorique : un motif est obligatoire pour clôturer la session."
            ) % {'variance': variance})
        comptage = self.env['microfinance.caisse.comptage'].create({
            'session_id': session.id,
            'theoretical_total': theoretical_total,
            'variance_comment': self.variance_comment,
            'line_ids': [
                (0, 0, {'denomination_id': line.denomination_id.id, 'quantity': line.quantity})
                for line in self.line_ids
            ],
        })
        # Déclenche comptage._check_variance_comment (motif obligatoire si écart - filet de
        # sécurité redondant avec la garde ci-dessus, au cas où ce wizard ne serait pas le seul
        # créateur de comptage à l'avenir). Puis l'écriture d'écart en attente (no-op si
        # variance == 0), puis la clôture proprement dite : si l'un de ces appels lève, toute la
        # transaction du bouton est annulée et rien n'est persisté.
        comptage.flush_recordset()
        comptage._post_variance_move()
        session.action_close_session()
        # Clôture réussie : le comptage devient définitif, le brouillon n'a plus lieu d'être.
        # Si l'un des appels ci-dessus lève, la transaction du bouton est annulée en entier
        # (cf. docstring de la classe) et ce unlink() est annulé avec elle - le brouillon reste
        # donc disponible pour une reprise si la clôture échoue.
        self.env['microfinance.caisse.comptage.brouillon'].search([
            ('session_id', '=', session.id),
        ]).unlink()
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
