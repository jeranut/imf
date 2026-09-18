# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class MicrofinanceCaisseComptage(models.Model):
    """Comptage physique du billetage réalisé à la clôture d'une session de caisse (sous-lot B :
    créé par le wizard de clôture, jamais à la main en pratique). Rattaché à la session en
    One2many : la décision actée est « comptage seulement via session ». L'historisation à
    plusieurs comptages par session est prévue dans le modèle de données, même si le code
    actuel n'en produira qu'un seul par session tant que le gap de réouverture de session
    (cf. docs_dev/guichet_caisse/AUDIT_session_billetage.md §7 Q11 et sous-lot 0) n'est pas
    traité dans un chantier séparé.

    Le contrôle d'écart ici (comptage physique vs solde théorique) **ne bloque pas** la
    clôture : il exige seulement un commentaire tracé si l'écart est non nul. Il est distinct
    du contrôle de cohérence `closing_balance` figé vs solde comptable réel de
    `microfinance.caisse.fiche.journee.action_close_day()`, qui, lui, reste bloquant et
    inchangé."""
    _name = 'microfinance.caisse.comptage'
    _description = 'Comptage de billetage (clôture de caisse)'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Référence', compute='_compute_name', store=True)
    session_id = fields.Many2one(
        'microfinance.caisse.session', string='Session de caisse', required=True,
        ondelete='cascade', index=True,
    )
    date = fields.Datetime(string='Date du comptage', default=fields.Datetime.now, readonly=True)
    counted_by = fields.Many2one(
        'res.users', string='Compté par', default=lambda self: self.env.user, readonly=True,
    )
    line_ids = fields.One2many(
        'microfinance.caisse.comptage.line', 'comptage_id', string='Détail du comptage',
    )
    counted_total = fields.Monetary(
        string='Total compté', compute='_compute_totals', store=True,
    )
    # Instantané du solde de clôture de la fiche au moment du comptage : figé par le wizard de
    # clôture (sous-lot B), après un _refresh_amounts() de la fiche pour ne pas comparer à une
    # valeur périmée. Non recalculé ensuite.
    theoretical_total = fields.Monetary(string='Solde théorique', readonly=True)
    variance = fields.Monetary(
        string='Écart (compté − théorique)', compute='_compute_totals', store=True,
    )
    variance_comment = fields.Text(
        string="Motif de l'écart",
        help="Obligatoire (contrainte serveur) dès que l'écart entre le comptage physique et "
             "le solde théorique n'est pas nul. Tracé et conservé avec le comptage.",
    )
    company_id = fields.Many2one(
        related='session_id.company_id', string='Agence', store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        related='session_id.currency_id', string='Devise', store=True, readonly=True,
    )

    # Écriture d'écart en attente (Lot fermeture 3-temps) : même principe que cheque_state /
    # account_cheques_attente_id / action_clear_cheque sur microfinance.savings.transaction
    # (microfinance_savings_management) - un compte d'attente dédié (company.
    # microfinance_account_ecart_caisse_deficit_id si l'écart est négatif, sinon
    # microfinance_account_ecart_caisse_excedent_id) reçoit la contrepartie de l'écriture posée
    # à la clôture, puis une seconde écriture, posée par action_reconcile_variance(), transfère
    # le montant vers le compte de régularisation choisi par le manager. 'none' tant qu'aucun
    # écart n'a été constaté (aucune écriture générée dans ce cas).
    variance_state = fields.Selection([
        ('none', 'Sans écart'),
        ('en_attente', 'En attente de réconciliation'),
        ('reconcilie', 'Réconcilié'),
    ], string="État de l'écart", default='none', readonly=True, copy=False, tracking=True)
    variance_move_id = fields.Many2one(
        'account.move', string="Écriture d'écart", readonly=True, copy=False,
        help="Écriture posée à la clôture, imputant l'écart constaté sur le compte de caisse du "
             "journal de la session contre le compte d'attente d'écart de l'agence. Vide si "
             "aucun écart n'a été constaté.",
    )
    reconciliation_account_id = fields.Many2one(
        'account.account', string='Compte de régularisation',
        help="Compte final vers lequel imputer l'écart (perte/gain de caisse, compte débiteur "
             "du caissier...) — à choisir avant de cliquer sur « Réconcilier l'écart ». Sans "
             "effet tant que variance_state n'est pas 'en_attente'.",
    )
    variance_clearing_move_id = fields.Many2one(
        'account.move', string='Écriture de réconciliation', readonly=True, copy=False,
        help="Écriture générée par action_reconcile_variance(), transférant le montant du "
             "compte d'attente vers le compte de régularisation choisi. Vide tant que l'écart "
             "n'est pas réconcilié.",
    )

    @api.depends('session_id.journal_id', 'session_id.date')
    def _compute_name(self):
        for comptage in self:
            comptage.name = _('Comptage caisse %(journal)s — %(date)s') % {
                'journal': comptage.session_id.journal_id.name or '',
                'date': comptage.session_id.date or '',
            }

    @api.depends('line_ids.subtotal', 'theoretical_total')
    def _compute_totals(self):
        for comptage in self:
            comptage.counted_total = sum(comptage.line_ids.mapped('subtotal'))
            comptage.variance = comptage.counted_total - comptage.theoretical_total

    @api.constrains('variance_comment', 'counted_total', 'theoretical_total')
    def _check_variance_comment(self):
        for comptage in self:
            if abs(comptage.variance) > 0.01 and not (comptage.variance_comment or '').strip():
                raise ValidationError(_(
                    "Le comptage présente un écart de %(variance).2f par rapport au solde "
                    "théorique : un motif est obligatoire pour enregistrer ce comptage."
                ) % {'variance': comptage.variance})

    def _post_variance_move(self):
        """Appelée une seule fois, juste après la création du comptage (wizard de clôture,
        temps 3) : pose l'écriture d'écart si variance != 0, sur le compte d'attente de
        l'agence, jamais directement sur un compte de régularisation final (cf. docstring de
        variance_state). No-op silencieux si l'écart est nul - aucune écriture n'est générée
        dans ce cas, cohérent avec variance_state='none'.

        sudo() ciblé sur la création/comptabilisation du move (le caissier n'a pas create sur
        account.move) : même principe que _run_posting_sudo dans
        microfinance_savings_management/models/microfinance_caisse_mouvement.py (décision Micka
        Lot 1.1bis, option 2) - pas de nouveau groupe comptable pour ce seul besoin."""
        self.ensure_one()
        if abs(self.variance) <= 0.01:
            return
        session = self.session_id
        company = session.company_id
        # Écart négatif (manquant en caisse) -> compte deficit ; écart positif (excédent) ->
        # compte excedent. Cf. docstring de la classe et help des deux champs sur res.company.
        if self.variance > 0:
            waiting_account = company.microfinance_account_ecart_caisse_excedent_id
        else:
            waiting_account = company.microfinance_account_ecart_caisse_deficit_id
        if not waiting_account:
            raise UserError(_(
                "Configurez le compte d'attente d'écart de caisse (déficit/excédent) sur "
                "l'agence %(company)s (Paramètres > Sociétés) avant de clôturer une session "
                "avec un écart."
            ) % {'company': company.name})
        cash_account = session.journal_id.default_account_id
        if not cash_account:
            raise UserError(_(
                "Le journal de caisse « %(journal)s » n'a pas de compte par défaut configuré."
            ) % {'journal': session.journal_id.name})
        amount = abs(self.variance)
        # Surplus (compté > théorique) : plus d'espèces en caisse que prévu -> on débite le
        # compte caisse (l'actif augmente) en contrepartie du compte d'attente. Manque (compté <
        # théorique) : l'inverse.
        if self.variance > 0:
            cash_side = {'debit': amount, 'credit': 0.0}
            waiting_side = {'debit': 0.0, 'credit': amount}
        else:
            cash_side = {'debit': 0.0, 'credit': amount}
            waiting_side = {'debit': amount, 'credit': 0.0}
        move = self.env['account.move'].sudo().create({
            'date': fields.Date.context_today(self),
            'journal_id': session.journal_id.id,
            'ref': _('Écart de caisse - %s') % self.name,
            'line_ids': [
                (0, 0, dict(cash_side, name=_('Écart de caisse'), account_id=cash_account.id)),
                (0, 0, dict(waiting_side, name=_('Écart de caisse - attente'), account_id=waiting_account.id)),
            ],
        })
        move.sudo().action_post()
        self.write({'variance_move_id': move.id, 'variance_state': 'en_attente'})

    def action_reconcile_variance(self):
        """Réconciliation manuelle de l'écart en attente (même rôle que action_clear_cheque) :
        transfère le montant du compte d'attente vers le compte de régularisation choisi par le
        manager (reconciliation_account_id, à renseigner avant l'appel)."""
        if not self.env.user.has_group('microfinance_loan_management.group_microfinance_manager'):
            raise AccessError(_("Seul un manager peut réconcilier un écart de caisse."))
        for comptage in self:
            if comptage.variance_state != 'en_attente':
                raise UserError(_(
                    "Cet écart n'est plus en attente de réconciliation (état actuel : %s)."
                ) % dict(comptage._fields['variance_state'].selection).get(comptage.variance_state))
            if not comptage.reconciliation_account_id:
                raise UserError(_(
                    "Choisissez un compte de régularisation avant de réconcilier cet écart."))
            session = comptage.session_id
            company = session.company_id
            if comptage.variance > 0:
                waiting_account = company.microfinance_account_ecart_caisse_excedent_id
            else:
                waiting_account = company.microfinance_account_ecart_caisse_deficit_id
            # Journal d'opérations diverses, PAS le journal de caisse de la session : celui-ci
            # a déjà sa fiche journalière clôturée à ce stade (la réconciliation intervient
            # après coup, potentiellement plusieurs jours plus tard) - AccountMove.action_post()
            # refuse toute nouvelle écriture sur un journal dont la fiche du jour est clôturée
            # (cf. microfinance_caisse_fiche_journee.py), donc réutiliser session.journal_id
            # ferait systématiquement échouer cette écriture.
            misc_journal = self.env['account.journal'].search([
                ('type', '=', 'general'), ('company_id', '=', company.id),
            ], limit=1)
            if not misc_journal:
                raise UserError(_(
                    "Aucun journal d'opérations diverses n'est configuré pour l'agence "
                    "%(company)s : requis pour réconcilier un écart de caisse."
                ) % {'company': company.name})
            amount = abs(comptage.variance)
            # Solde le compte d'attente (mouvement inverse de celui posé par _post_variance_move)
            # contre le compte de régularisation choisi.
            if comptage.variance > 0:
                waiting_side = {'debit': amount, 'credit': 0.0}
                dest_side = {'debit': 0.0, 'credit': amount}
            else:
                waiting_side = {'debit': 0.0, 'credit': amount}
                dest_side = {'debit': amount, 'credit': 0.0}
            move = self.env['account.move'].sudo().create({
                'date': fields.Date.context_today(comptage),
                'journal_id': misc_journal.id,
                'ref': _('Réconciliation écart de caisse - %s') % comptage.name,
                'line_ids': [
                    (0, 0, dict(waiting_side, name=_('Réconciliation écart de caisse'), account_id=waiting_account.id)),
                    (0, 0, dict(dest_side, name=_('Réconciliation écart de caisse'), account_id=comptage.reconciliation_account_id.id)),
                ],
            })
            move.sudo().action_post()
            comptage.write({'variance_clearing_move_id': move.id, 'variance_state': 'reconcilie'})
            comptage.message_post(body=_('Écart de caisse réconcilié par %(user)s. Écriture : %(move)s') % {
                'user': self.env.user.name, 'move': move.name,
            })


class MicrofinanceCaisseComptageLine(models.Model):
    _name = 'microfinance.caisse.comptage.line'
    _description = 'Ligne de comptage de billetage'
    _order = 'comptage_id, denomination_value desc'

    comptage_id = fields.Many2one(
        'microfinance.caisse.comptage', string='Comptage', required=True,
        ondelete='cascade', index=True,
    )
    denomination_id = fields.Many2one(
        'microfinance.caisse.denomination', string='Coupure / pièce', required=True,
    )
    denomination_value = fields.Monetary(
        related='denomination_id.value', string='Valeur faciale', store=True, readonly=True,
    )
    quantity = fields.Integer(string='Quantité', default=0)
    subtotal = fields.Monetary(
        string='Sous-total', compute='_compute_subtotal', store=True,
    )
    currency_id = fields.Many2one(
        related='comptage_id.currency_id', string='Devise', store=True, readonly=True,
    )

    _sql_constraints = [
        ('denom_uniq', 'unique(comptage_id, denomination_id)',
         'Cette coupure est déjà présente dans ce comptage.'),
    ]

    @api.depends('denomination_id.value', 'quantity')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.denomination_id.value or 0.0) * line.quantity

    @api.constrains('quantity')
    def _check_quantity_positive(self):
        for line in self:
            if line.quantity < 0:
                raise ValidationError(_('La quantité comptée ne peut pas être négative.'))
