# -*- coding: utf-8 -*-
"""Traçabilité comptable du partage de fonds entre le siège et les agences.

Validation d'un partage (une part par agence, société mère incluse) :
  - agence : DEUX écritures liées, chacune dans sa société, soldées ensuite par le rapprochement du
    relevé de chaque société :
      siège  : journal du fonds (FDBM/FDBN)   Dr 301xxx (liaison agence) / Cr 139500
      agence : journal crédit de la même banque (BMCR si FDBM, BNCR si FDBN)   Dr 139100 / Cr 301010
  - part gardée par la société mère : UNE écriture, Dr journal crédit (BMCR/BNCR) / Cr journal du fonds,
    même banque, sans compte de liaison.
Si le côté agence ne peut pas être créé (agence non configurée), le côté siège reste en suspens et la
ligne passe en « envoyé, non reçu » ; le bouton « Générer le côté agence » le crée ensuite. Rien n'est
généré si le fonds ne passe pas au grand livre (passer_gl faux) ou n'a pas de journal bancaire.
"""
from odoo import api, fields, models, _, tools
from odoo.exceptions import UserError

# journal du fonds -> journal crédit de la même banque
FUND_TO_CREDIT_JOURNAL = {'FDBM': 'BMCR', 'FDBN': 'BNCR'}


class ResCompany(models.Model):
    _inherit = 'res.company'

    microfinance_liaison_hq_account_id = fields.Many2one(
        'account.account', string='Compte de liaison (côté siège)', check_company=False,
        help="À renseigner sur l'AGENCE : compte du plan de la société mère qui représente cette "
             "agence (ex. 301101), débité au siège quand un fonds lui est partagé.",
    )
    microfinance_liaison_agency_account_id = fields.Many2one(
        'account.account', string='Compte de liaison (côté agence)',
        help="À renseigner sur l'AGENCE : son propre compte de liaison avec le siège (ex. 301010), "
             "crédité à l'agence quand elle reçoit un fonds.",
    )


class MicrofinanceFondCredit(models.Model):
    _inherit = 'microfinance.fond.credit'

    bank_journal_id = fields.Many2one(
        'account.journal', string='Journal bancaire du fonds', tracking=True, check_company=False,
        domain="[('type', '=', 'bank'), ('code', 'in', ('FDBM', 'FDBN'))]",
        help="Banque du fonds (FDBM = BMOI, FDBN = BNI) : un fonds est sur UNE SEULE banque. Sert de "
             "journal aux écritures de partage. Sans ce journal, un partage ne génère aucune écriture.",
    )


class AccountMove(models.Model):
    _inherit = 'account.move'

    microfinance_fond_partage_id = fields.Many2one(
        'microfinance.fond.partage', string='Partage de fonds', copy=False, index='btree_not_null',
        readonly=True, ondelete='restrict')
    microfinance_fond_partage_line_id = fields.Many2one(
        'microfinance.fond.partage.line', string='Part de partage', copy=False, index='btree_not_null',
        readonly=True, ondelete='restrict')
    microfinance_partage_side = fields.Selection([
        ('hq', 'Côté siège'), ('agency', 'Côté agence'), ('hq_own', 'Part du siège'),
    ], string='Côté du partage', copy=False, readonly=True)


class MicrofinanceFondPartageLine(models.Model):
    _inherit = 'microfinance.fond.partage.line'

    hq_move_id = fields.Many2one('account.move', string='Écriture siège', readonly=True, copy=False, ondelete='restrict')
    agency_move_id = fields.Many2one('account.move', string='Écriture agence', readonly=True, copy=False, ondelete='restrict')
    liaison_note = fields.Char(string='Remarque de liaison', readonly=True, copy=False)
    liaison_state = fields.Selection([
        ('none', 'Aucune écriture'),
        ('both', 'Siège et agence'),
        ('hq_only', 'Envoyé, non reçu'),
        ('agency_only', 'Agence seule'),
        ('own', 'Part du siège'),
        ('cancelled', 'Annulé'),
    ], string='Liaison', compute='_compute_liaison_state')

    @api.depends('hq_move_id', 'agency_move_id', 'partage_id.state', 'company_id', 'partage_id.company_id')
    def _compute_liaison_state(self):
        for line in self:
            if line.partage_id.state == 'cancelled':
                line.liaison_state = 'cancelled'
            elif line.hq_move_id and line.hq_move_id.microfinance_partage_side == 'hq_own':
                line.liaison_state = 'own'
            elif line.hq_move_id and line.agency_move_id:
                line.liaison_state = 'both'
            elif line.hq_move_id:
                line.liaison_state = 'hq_only'
            elif line.agency_move_id:
                line.liaison_state = 'agency_only'
            else:
                line.liaison_state = 'none'

    def action_generate_agency_move(self):
        """Crée le côté agence des parts envoyées mais non reçues (agence maintenant configurée)."""
        self.env['res.company']._check_microfinance_parent_only()
        for line in self:
            if line.partage_id.state != 'validated' or not line.hq_move_id or line.agency_move_id \
                    or line.hq_move_id.microfinance_partage_side != 'hq':
                continue
            line.partage_id._create_agency_move(line)
            line.liaison_note = False
        return True


class MicrofinanceFondPartage(models.Model):
    _inherit = 'microfinance.fond.partage'

    # ------------------------------------------------------------------ helpers
    @api.model
    def _payment_account(self, journal, direction):
        """Compte en suspens du journal (139100 entrant / 139500 sortant), repli sur la société."""
        lines = journal.inbound_payment_method_line_ids if direction == 'inbound' else journal.outbound_payment_method_line_ids
        account = lines.filtered('payment_account_id')[:1].payment_account_id
        if not account:
            company = journal.company_id
            account = (company.account_journal_payment_debit_account_id if direction == 'inbound'
                       else company.account_journal_payment_credit_account_id)
        return account

    def _liaison_env(self, company):
        return self.env['account.move'].sudo().with_company(company).with_context(allowed_company_ids=[company.id])

    def _create_move(self, company, vals):
        move = self._liaison_env(company).create(vals)
        move.action_post()
        return move

    def _move_vals(self, line, journal, label, debit_account, credit_account, side):
        return {
            'move_type': 'entry', 'date': self.date, 'journal_id': journal.id,
            'ref': '%s - %s' % (self.name, label),
            'microfinance_fond_partage_id': self.id, 'microfinance_fond_partage_line_id': line.id,
            'microfinance_partage_side': side,
            'line_ids': [
                (0, 0, {'name': label, 'account_id': debit_account.id, 'debit': line.amount, 'credit': 0.0}),
                (0, 0, {'name': label, 'account_id': credit_account.id, 'debit': 0.0, 'credit': line.amount}),
            ],
        }

    def _credit_journal_for(self, fund_journal, company):
        code = FUND_TO_CREDIT_JOURNAL.get(fund_journal.code)
        journal = self.env['account.journal'].sudo().search(
            [('code', '=', code), ('company_id', '=', company.id), ('type', '=', 'bank')], limit=1) if code else self.env['account.journal']
        return journal

    # ------------------------------------------------------------------ génération
    def _create_agency_move(self, line):
        """Côté agence : Dr 139100 / Cr compte de liaison de l'agence (journal crédit de la banque du fonds)."""
        self.ensure_one()
        agency = line.company_id
        fund_journal = self.fond_id.bank_journal_id
        journal = self._credit_journal_for(fund_journal, agency)
        if not journal:
            raise UserError(_("L'agence « %(agence)s » n'a pas de journal crédit pour la banque du fonds (%(code)s).")
                            % {'agence': agency.name, 'code': fund_journal.code})
        inbound = self._payment_account(journal, 'inbound')
        liaison = agency.microfinance_liaison_agency_account_id
        if not inbound or not liaison:
            raise UserError(_("L'agence « %s » n'a pas de compte de paiement en suspens (139100) ou de compte de liaison configuré.") % agency.name)
        move = self._create_move(agency, self._move_vals(
            line, journal, _('Fonds reçu %s') % self.fond_id.code, inbound, liaison, 'agency'))
        line.agency_move_id = move
        return move

    def _generate_liaison_moves(self):
        for partage in self:
            fond = partage.fond_id
            if not fond.passer_gl:
                partage.message_post(body=_("Aucune écriture comptable : le fonds ne passe pas au grand livre."))
                continue
            fund_journal = fond.bank_journal_id
            if not fund_journal:
                partage.message_post(body=_(
                    "Aucune écriture comptable générée : renseignez le journal bancaire du fonds (FDBM/FDBN)."))
                continue
            hq = partage.company_id
            for line in partage.line_ids.filtered(lambda l: l.amount > 0 and not l.hq_move_id):
                if line.company_id == hq:
                    credit_journal = partage._credit_journal_for(fund_journal, hq)
                    if not credit_journal:
                        raise UserError(_("Journal crédit de la banque du fonds introuvable pour %s.") % hq.name)
                    move = partage._create_move(hq, partage._move_vals(
                        line, fund_journal, _('Part gardée %s') % fond.code,
                        credit_journal.default_account_id, fund_journal.default_account_id, 'hq_own'))
                    line.hq_move_id = move
                    continue
                liaison_hq = line.company_id.microfinance_liaison_hq_account_id
                outbound = partage._payment_account(fund_journal, 'outbound')
                if not liaison_hq or not outbound:
                    raise UserError(_(
                        "Configurez le compte de liaison côté siège de l'agence « %s » (et le compte "
                        "en suspens sortant du journal du fonds) avant de valider le partage.") % line.company_id.name)
                move = partage._create_move(hq, partage._move_vals(
                    line, fund_journal, _('Fonds envoyé à %s') % line.company_id.name, liaison_hq, outbound, 'hq'))
                line.hq_move_id = move
                try:
                    with self.env.cr.savepoint():
                        partage._create_agency_move(line)
                except UserError as e:
                    line.liaison_note = e.args[0]

    def action_validate(self):
        res = super().action_validate()
        self._generate_liaison_moves()
        return res

    # ------------------------------------------------------------------ annulation
    def _liaison_moves(self):
        return self.mapped('line_ids.hq_move_id') | self.mapped('line_ids.agency_move_id')

    def _check_liaison_not_reconciled(self):
        for partage in self:
            moves = partage._liaison_moves().sudo()
            if moves.line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids):
                raise UserError(_(
                    "Annulation impossible : une écriture de ce partage est déjà lettrée/rapprochée avec un "
                    "relevé. Défaites d'abord le rapprochement."))

    def action_cancel(self):
        validated = self.filtered(lambda p: p.state == 'validated')
        validated._check_liaison_not_reconciled()
        res = super().action_cancel()
        for partage in validated.filtered(lambda p: p.state == 'cancelled'):
            for move in partage._liaison_moves().sudo():
                if self.env['account.move'].sudo().search_count([('reversed_entry_id', '=', move.id)]):
                    continue
                move.with_company(move.company_id).with_context(allowed_company_ids=[move.company_id.id])._reverse_moves([{
                    'date': fields.Date.context_today(self),
                    'ref': _('Extourne %s') % (move.ref or move.name),
                    'microfinance_fond_partage_id': partage.id,
                    'microfinance_fond_partage_line_id': move.microfinance_fond_partage_line_id.id,
                    'microfinance_partage_side': move.microfinance_partage_side,
                }], cancel=True)
        return res


class MicrofinanceFondLiaisonReport(models.Model):
    """Écarts de liaison par partage et par agence : montant débité au siège (301xxx) contre montant
    crédité à l'agence (301010), extournes incluses."""
    _name = 'microfinance.fond.liaison.report'
    _description = 'Écarts de liaison des partages de fonds'
    _auto = False
    _order = 'date desc, line_id'

    line_id = fields.Many2one('microfinance.fond.partage.line', string='Part', readonly=True)
    partage_id = fields.Many2one('microfinance.fond.partage', string='Partage', readonly=True)
    fond_id = fields.Many2one('microfinance.fond.credit', string='Fonds', readonly=True)
    company_id = fields.Many2one('res.company', string='Agence', readonly=True)
    date = fields.Date(readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    partage_state = fields.Selection([('draft', 'Brouillon'), ('validated', 'Validé'), ('cancelled', 'Annulé')], string='État du partage', readonly=True)
    amount_partage = fields.Monetary(string='Montant partagé', readonly=True)
    hq_amount = fields.Monetary(string='Siège (301xxx)', readonly=True)
    agency_amount = fields.Monetary(string='Agence (301010)', readonly=True)
    difference = fields.Monetary(string='Écart', readonly=True)
    state = fields.Selection([
        ('ok', 'Soldé'), ('ecart', 'Écart'), ('hq_only', 'Envoyé, non reçu'),
        ('agency_only', 'Agence seule'), ('none', 'Aucune écriture'),
    ], string='Situation', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT l.id AS id, l.id AS line_id, p.id AS partage_id, p.fond_id AS fond_id,
                       l.company_id AS company_id, p.date AS date, p.currency_id AS currency_id,
                       p.state AS partage_state, l.amount AS amount_partage,
                       x.hq AS hq_amount, x.ag AS agency_amount, (x.hq - x.ag) AS difference,
                       CASE WHEN x.hq = 0 AND x.ag = 0 THEN 'none'
                            WHEN x.hq <> 0 AND x.ag = 0 THEN 'hq_only'
                            WHEN x.hq = 0 AND x.ag <> 0 THEN 'agency_only'
                            WHEN x.hq = x.ag THEN 'ok' ELSE 'ecart' END AS state
                FROM microfinance_fond_partage_line l
                JOIN microfinance_fond_partage p ON p.id = l.partage_id
                JOIN res_company c ON c.id = l.company_id
                CROSS JOIN LATERAL (
                    SELECT COALESCE(SUM(CASE WHEN m.microfinance_partage_side = 'hq' AND aml.account_id = c.microfinance_liaison_hq_account_id
                                             THEN aml.debit - aml.credit END), 0) AS hq,
                           COALESCE(SUM(CASE WHEN m.microfinance_partage_side = 'agency' AND aml.account_id = c.microfinance_liaison_agency_account_id
                                             THEN aml.credit - aml.debit END), 0) AS ag
                    FROM account_move m
                    JOIN account_move_line aml ON aml.move_id = m.id
                    WHERE m.microfinance_fond_partage_line_id = l.id AND m.state = 'posted'
                ) x
                WHERE l.company_id <> p.company_id AND p.state <> 'draft'
            )""" % self._table)


class MicrofinanceFondLiaisonSolde(models.Model):
    """Solde du compte de liaison de chaque agence côté siège (301xxx) contre son compte 301010, toutes
    écritures confondues (partage ou non)."""
    _name = 'microfinance.fond.liaison.solde'
    _description = 'Soldes de liaison siège / agences'
    _auto = False
    _order = 'company_id'

    company_id = fields.Many2one('res.company', string='Agence', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    hq_balance = fields.Monetary(string='Solde siège (301xxx)', readonly=True)
    agency_balance = fields.Monetary(string='Solde agence (301010)', readonly=True)
    difference = fields.Monetary(string='Écart', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT c.id AS id, c.id AS company_id, c.currency_id AS currency_id,
                       COALESCE((SELECT SUM(aml.debit - aml.credit) FROM account_move_line aml
                                 WHERE aml.account_id = c.microfinance_liaison_hq_account_id AND aml.parent_state = 'posted'), 0) AS hq_balance,
                       COALESCE((SELECT SUM(aml.credit - aml.debit) FROM account_move_line aml
                                 WHERE aml.account_id = c.microfinance_liaison_agency_account_id AND aml.parent_state = 'posted'), 0) AS agency_balance,
                       COALESCE((SELECT SUM(aml.debit - aml.credit) FROM account_move_line aml
                                 WHERE aml.account_id = c.microfinance_liaison_hq_account_id AND aml.parent_state = 'posted'), 0)
                       - COALESCE((SELECT SUM(aml.credit - aml.debit) FROM account_move_line aml
                                 WHERE aml.account_id = c.microfinance_liaison_agency_account_id AND aml.parent_state = 'posted'), 0) AS difference
                FROM res_company c
                WHERE c.microfinance_liaison_hq_account_id IS NOT NULL
            )""" % self._table)
