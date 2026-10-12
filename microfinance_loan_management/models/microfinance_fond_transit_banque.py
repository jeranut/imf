# -*- coding: utf-8 -*-
"""Banque (et relevé à saisir) des montants « En transit », pour les fonds de crédit ET d'exploitation.

Un seul calcul, partagé par les tuiles du tableau de bord et les listes de fonds :
  - une « entrée de transit » est un couple (journal, montant) : le journal qui porte la ligne en suspens non lettrée,
    donc celui dont il faut saisir le relevé bancaire ; la banque se lit sur le champ « Banque (microfinance) » de ce
    journal, jamais en dur ;
  - niveau « siège » (N1) : contributions du fonds, journal de la contribution (journal de fonds, ou d'exploitation
    pour un fonds d'exploitation) ;
  - niveau « agence » (N2) : parts des partages validés de la société courante, journal qui reçoit la part (journal
    crédit ou d'exploitation de l'agence ; pour la part gardée par la société mère, son journal crédit) ;
  - `_transit_note` met ces entrées en forme : « BNI » ou « BNI 100 M · BMOI 50 M » ; vide si rien n'est en transit.
"""
from odoo import api, fields, models, _
from odoo.tools import float_compare

LEVEL_SIEGE = 'siege'
LEVEL_AGENCE = 'agence'


def _millions(amount):
    text = ('%.2f' % (amount / 1000000.0)).rstrip('0').rstrip('.')
    return '%s M' % text.replace('.', ',')


class MicrofinanceFondPartageLine(models.Model):
    _inherit = 'microfinance.fond.partage.line'

    def _bank_state(self):
        """(reçu en banque, en transit, non reçu, journal à rapprocher) de la part. Lu sur le lettrage de la ligne en
        suspens (139100) avec une ligne de relevé, jamais saisi. La part gardée par la société mère n'a pas de miroir :
        son écriture porte le suspens, et le relevé à saisir est celui de son journal crédit."""
        self.ensure_one()
        line = self.sudo()
        partage = line.partage_id
        own = line.company_id == partage.company_id
        # part gardée : la pièce qui porte le 139100 est celle du journal crédit (agency_move_id) ; anciens partages :
        # une seule pièce (hq_move_id) portait le 139100 et le 139500
        move = (line.agency_move_id or line.hq_move_id) if own else line.agency_move_id
        if not move:
            return 0.0, 0.0, line.amount, self.env['account.journal']
        suspense = move.line_ids.filtered(lambda l: l.debit > 0)[:1]
        banked = sum(
            partial.amount for partial in suspense.matched_credit_ids
            if partial.credit_move_id.move_id.statement_line_id)
        banked = min(banked, line.amount)
        journal = move.journal_id
        if own and partage.destination != 'exploitation':
            journal = partage._credit_journal_for(partage.fond_id.fund_journal_id, line.company_id) or journal
        return banked, line.amount - banked, 0.0, journal


class MicrofinanceFondContribution(models.Model):
    _inherit = 'microfinance.fond.contribution'

    def _transit_entry(self):
        """(journal, montant en transit signé) de la contribution : dépôt non encore lettré avec un relevé en positif,
        retrait ou remboursement en négatif (même signe que « contribué » du siège)."""
        self.ensure_one()
        sign = 1.0 if self.type_mouvement == 'depot' else -1.0
        return self.move_id.sudo().journal_id, sign * (self.amount - self._bank_received_amount())


class MicrofinanceFondCredit(models.Model):
    _inherit = 'microfinance.fond.credit'

    transit_banque_siege = fields.Char(
        string='Banque (relevé du siège)', compute='_compute_transit_banque', compute_sudo=True,
        help="Banque et journal dont il faut saisir le relevé pour rapprocher les contributions encore en transit. "
             "Vide si rien n'est en transit ; réservé à la société mère.")
    transit_banque_agence = fields.Char(
        string="Banque (relevé de l'agence)", compute='_compute_transit_banque', compute_sudo=True,
        help="Banque et journal dont il faut saisir le relevé pour rapprocher la part de la société courante encore "
             "en transit (part gardée du siège comprise). Vide si rien n'est en transit.")

    def _transit_entries(self, level):
        """Entrées de transit [(journal, montant)] du fonds pour le niveau demandé, pour la société courante."""
        self.ensure_one()
        fond = self.sudo()
        if not fond.passer_gl:
            return []
        company = self.env.company
        if level == LEVEL_SIEGE:
            parent = self.env['res.company']._get_microfinance_parent()
            if not parent or company != parent or fond._fund_company() != parent:
                return []
            return [contrib._transit_entry()
                    for contrib in fond.contribution_ids.filtered(lambda c: c.state == 'posted' and c.move_id)]
        lines = self.env['microfinance.fond.partage.line'].sudo().search([
            ('partage_id.fond_id', '=', fond.id), ('partage_id.state', '=', 'validated'),
            ('company_id', '=', company.id), ('amount', '>', 0)])
        entries = []
        for line in lines:
            _banked, transit, _missing, journal = line._bank_state()
            if journal:
                entries.append((journal, transit))
        return entries

    @api.model
    def _transit_note(self, entries, with_journal=False):
        """« BNI » ou « BNI 100 M · BMOI 50 M » (avec `with_journal` : « BNI (relevé FDBN) ») ; vide si le total en
        transit n'est pas positif. Les montants nuls ou négatifs d'une banque ne sont pas mentionnés."""
        groups = {}
        for journal, amount in entries:
            bank = journal.microfinance_bank_id.name or journal.name
            key = (bank, journal.name) if with_journal else (bank,)
            groups[key] = groups.get(key, 0.0) + amount
        groups = {key: amount for key, amount in groups.items() if float_compare(amount, 0.0, precision_digits=2) > 0}
        if not groups:
            return ''

        def label(key):
            return _('%(banque)s (relevé %(journal)s)') % {'banque': key[0], 'journal': key[1]} if with_journal else key[0]

        if len(groups) == 1:
            return label(next(iter(groups)))
        return ' · '.join('%s %s' % (label(key), _millions(amount)) for key, amount in sorted(groups.items()))

    @api.model
    def _transit_note_for(self, funds, level, with_journal=False):
        """Même calcul pour une liste de fonds (tuiles) : entrées de tous les fonds regroupées par banque."""
        entries = []
        for fond in funds:
            entries.extend(fond._transit_entries(level))
        return self._transit_note(entries, with_journal)

    @api.depends_context('company')
    @api.depends('contribution_ids.amount', 'contribution_ids.state', 'contribution_ids.move_id', 'passer_gl')
    def _compute_transit_banque(self):
        for fond in self:
            fond.transit_banque_siege = fond._transit_note(fond._transit_entries(LEVEL_SIEGE), with_journal=True)
            fond.transit_banque_agence = fond._transit_note(fond._transit_entries(LEVEL_AGENCE), with_journal=True)
