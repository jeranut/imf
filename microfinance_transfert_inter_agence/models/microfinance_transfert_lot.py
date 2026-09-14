# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Séquence dédiée (par société source), réutilise
# res.company._get_or_create_numbering_sequence — même patron que toute la
# numérotation du projet. padding par défaut (6).
LOT_SEQ_CODE = 'microfinance.transfert.lot'


class MicrofinanceTransfertLot(models.Model):
    """Lot de rapatriement : regroupe plusieurs transferts encaissés par une même
    agence source et destinés à une même agence destination, remis ensemble à un
    coursier. Chaque transfert du lot garde son propre code de transfert.

    Visible par les deux agences concernées — voir
    security/microfinance_transfert_rules.xml.
    """
    _name = 'microfinance.transfert.lot'
    _description = "Lot de rapatriement de transferts inter-agences"
    _order = 'id desc'
    _rec_name = 'reference'

    reference = fields.Char(
        string='Référence du lot', required=True, readonly=True, copy=False, index=True,
        default='Nouveau',
        help="Générée à la création à partir d'une séquence dédiée par agence source "
             "(format TL/<préfixe source>/<numéro>).",
    )
    source_company_id = fields.Many2one(
        'res.company', string='Agence source', required=True, index=True, readonly=True,
        default=lambda self: self.env.company,
    )
    destination_company_id = fields.Many2one(
        'res.company', string='Agence destination', required=True, index=True, readonly=True,
    )
    currency_id = fields.Many2one(related='source_company_id.currency_id', readonly=True)

    coursier_id = fields.Many2one(
        'res.partner', string='Coursier',
        help="Personne à qui les espèces sont remises pour acheminement vers l'agence "
             "destination — salarié CEFOR ou prestataire externe de transport de fonds.",
    )
    date_remise = fields.Datetime(string='Date de remise au coursier', copy=False)

    transfert_ids = fields.One2many(
        'microfinance.transfert.remboursement', 'lot_id', string='Transferts du lot',
    )
    montant_total = fields.Monetary(
        string='Montant total', compute='_compute_montant_total', store=True,
    )

    state = fields.Selection(
        [('brouillon', 'Brouillon'), ('valide', 'Validé')],
        string='État', required=True, default='brouillon', copy=False, index=True,
    )
    validated_by = fields.Many2one('res.users', string='Validé par', readonly=True, copy=False)
    remise_move_id = fields.Many2one(
        'account.move', string='Écriture de remise au coursier (étape 2)',
        readonly=True, copy=False,
    )

    _sql_constraints = [
        ('reference_unique', 'unique(reference)', "La référence de lot doit être unique."),
    ]

    @api.depends('transfert_ids.amount')
    def _compute_montant_total(self):
        for lot in self:
            lot.montant_total = sum(lot.transfert_ids.mapped('amount'))

    @api.constrains('transfert_ids', 'source_company_id', 'destination_company_id')
    def _check_transfert_agencies(self):
        """Un lot ne regroupe que des transferts d'une même paire (source, destination)."""
        for lot in self:
            for transfert in lot.transfert_ids:
                if (transfert.source_company_id != lot.source_company_id
                        or transfert.destination_company_id != lot.destination_company_id):
                    # sudo pour le libellé : l'agence destination est hors périmètre
                    # multi-société du caissier source (cf. _guichet_row).
                    t_su, l_su = transfert.sudo(), lot.sudo()
                    raise ValidationError(_(
                        "Le transfert %(code)s (%(tsrc)s → %(tdst)s) ne peut pas rejoindre le "
                        "lot %(ref)s (%(lsrc)s → %(ldst)s) : un lot ne regroupe que des "
                        "transferts d'une même paire d'agences source / destination.",
                        code=t_su.transfer_code,
                        tsrc=t_su.source_company_id.name,
                        tdst=t_su.destination_company_id.name,
                        ref=l_su.reference,
                        lsrc=l_su.source_company_id.name,
                        ldst=l_su.destination_company_id.name,
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (vals.get('reference', 'Nouveau') in ('Nouveau', False)
                    and vals.get('source_company_id')):
                source = self.env['res.company'].browse(vals['source_company_id'])
                number = source._get_or_create_numbering_sequence(LOT_SEQ_CODE)
                vals['reference'] = 'TL/%s/%s' % (source.agency_code, number)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Étape 2 du cycle — remise du lot au coursier (voir la docstring de
    # microfinance.transfert.remboursement pour les 4 étapes).
    # ------------------------------------------------------------------
    def action_valider(self):
        """Solde le compte de transit de l'agence source (l'argent physique
        quitte le coffre) et fait passer tous les transferts du lot en
        « En transit ». Une paire de lignes Dr transit / Cr caisse PAR transfert :
        le transit se solde exactement contre ce que l'encaissement (étape 1) a
        créé, même si deux transferts du lot ont utilisé des comptes de caisse
        différents.
        """
        self.ensure_one()
        if self.state != 'brouillon':
            raise UserError(_("Ce lot est déjà validé."))
        if not self.coursier_id:
            raise UserError(_("Renseignez le coursier avant de valider le lot."))
        if not self.transfert_ids:
            raise UserError(_("Ce lot ne contient aucun transfert."))
        not_ready = self.transfert_ids.filtered(
            lambda t: t.state != 'en_attente' or not t.encaissement_move_id or not t.caisse_account_id)
        if not_ready:
            raise UserError(_(
                "Certains transferts du lot ne sont pas encaissés ou ne sont plus "
                "« En attente » : %s"
            ) % ', '.join(not_ready.mapped('transfer_code')))

        transit_journal = self.env['microfinance.transfert.remboursement']._get_company_transit_journal(
            self.source_company_id)
        transit_account = transit_journal.default_account_id
        if not transit_account:
            raise UserError(_(
                "Le journal TRANSIT de l'agence source n'a pas de compte par défaut (302000)."))

        line_ids = []
        for transfert in self.transfert_ids:
            line_ids.append((0, 0, {
                'name': _("Solde transit %s") % transfert.transfer_code,
                'account_id': transit_account.id, 'partner_id': transfert.partner_id.id,
                'debit': transfert.amount, 'credit': 0.0,
            }))
            line_ids.append((0, 0, {
                'name': _("Sortie caisse %s") % transfert.transfer_code,
                'account_id': transfert.caisse_account_id.id, 'partner_id': transfert.partner_id.id,
                'debit': 0.0, 'credit': transfert.amount,
            }))
        move = self.env['account.move'].sudo().create({
            'journal_id': transit_journal.id,
            'date': fields.Date.context_today(self),
            'ref': self.reference,
            'line_ids': line_ids,
        })
        move.action_post()

        self.write({
            'state': 'valide',
            'date_remise': fields.Datetime.now(),
            'validated_by': self.env.user.id,
            'remise_move_id': move.id,
        })
        self.transfert_ids.write({'state': 'en_transit'})

        # LIMITE CONNUE (v1, décision Micka — cf. docs_dev/guichet_caisse/
        # DECISIONS_transfert_inter_agence.md §2) : entre cette remise au coursier
        # et la réception à l'agence destination (action_valider_destination,
        # étape 3), les fonds sont physiquement chez le coursier mais
        # n'apparaissent NI dans le 302000 source (soldé ci-dessus) NI dans le
        # 302000 destination (pas encore mouvementé). Le solde consolidé du réseau
        # CEFOR est donc transitoirement sous-évalué du montant en transit.
        # Acceptable tant que remise et réception se font le même jour ou le
        # lendemain (coursier physique à l'échelle d'Antananarivo). Si les délais
        # s'allongent : chantier séparé pour un sous-compte « en route » dédié.
        return True

    def action_print_ticket(self):
        """Ticket de remise récapitulatif du lot (un ticket par lot ; chaque ligne
        garde son code de transfert individuel — décision actée). Le rendu passe
        par le modèle de rapport ReportTransfertLot ci-dessous, qui sudo les
        données (le ticket, édité par l'agence source, récapitule des données de
        l'agence destination hors de son périmètre multi-société)."""
        self.ensure_one()
        return self.env.ref(
            'microfinance_transfert_inter_agence.action_report_transfert_lot'
        ).report_action(self)


class ReportTransfertLot(models.AbstractModel):
    """Fournit les données du ticket de remise EN SUDO.

    _render_qweb_html d'Odoo cherche un modèle nommé « report.<report_name> » ;
    s'il existe, il appelle son _get_report_values au lieu de brancher `docs` sur
    l'utilisateur courant. Le ticket est édité par l'agence SOURCE (remise au
    coursier) mais récapitule des données de l'agence DESTINATION hors de son
    périmètre multi-société : nom du client (res.partner), n° de dossier
    (microfinance.loan), nom de l'agence destination. Sans ce modèle, chaque
    `t-field` correspondant lèverait AccessError pour un caissier source
    mono-agence. Sudo circonscrit à ce rendu en lecture seule, sur un lot que
    l'agence source possède déjà — même principe que
    microfinance.transfert.remboursement._guichet_row.
    """
    _name = 'report.microfinance_transfert_inter_agence.report_transfert_lot_document'
    _description = "Données du ticket de remise (rendu sudo)"
    # _name dépasse la limite PostgreSQL de 63 caractères pour un nom de table
    # auto-dérivé ; un AbstractModel ne crée aucune table, on fixe donc un _table
    # court explicite (check_pg_name le contrôle même sans persistance).
    _table = 'mf_transfert_lot_report'

    @api.model
    def _get_report_values(self, docids, data=None):
        return {
            'doc_ids': docids,
            'doc_model': 'microfinance.transfert.lot',
            'docs': self.env['microfinance.transfert.lot'].sudo().browse(docids),
        }
