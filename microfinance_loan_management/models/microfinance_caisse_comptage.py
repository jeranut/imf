# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
