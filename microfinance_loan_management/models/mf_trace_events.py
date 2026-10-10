# -*- coding: utf-8 -*-
"""Événements comptables d'Ampaly tracés dans le chatter (voir mf_trace.py).

Ce fichier est chargé EN DERNIER : chaque surcharge appelle d'abord le code existant (super), inchangé, puis ajoute une
trace. Rien n'est modifié dans l'opération : mêmes écritures, mêmes montants, mêmes états, mêmes valeurs de retour. Toute
méthode `_mf_trace_*` est protégée (mf_safe) : une trace qui échoue est journalisée puis ignorée.

Confidentialité : un message ne cite jamais de donnée d'une autre société que celle de la fiche où il est posé. Un fonds
multi-agences est lisible de toutes les agences : son fil ne reçoit donc aucun montant (voir `_fund_details`).
"""
from markupsafe import Markup

from odoo import api, models, _

from .mf_trace import mf_amount, mf_link, mf_safe, mf_selection_label

SKIP_RECONCILE = 'mf_trace_skip_reconcile'   # posé par les opérations qui tracent déjà leurs lettrages
MAX_LISTED = 300                            # lignes citées dans une synthèse ; le reste est résumé en un compteur
FOND_WATCHED = {'bank_id', 'origine', 'nature', 'destination', 'account_id', 'passer_gl'}


def _dash(value):
    return value or '—'


def _fund_details(fond, full, neutral):
    """Un fonds multi-agences (sans société) est lisible de toutes les agences : aucun montant dans son fil."""
    return neutral if fond.scope == 'multi_company' else full


def _side_lines(move):
    """(ligne débitrice, ligne créditrice) d'une pièce à deux lignes."""
    return move.line_ids.filtered(lambda l: l.debit > 0)[:1], move.line_ids.filtered(lambda l: l.credit > 0)[:1]


def _reversals(moves):
    return moves.env['account.move'].sudo().search([('reversed_entry_id', 'in', moves.ids)])


def _listed(items):
    if len(items) > MAX_LISTED:
        return items[:MAX_LISTED] + [_('… et %s autres lignes') % (len(items) - MAX_LISTED)]
    return items


# ====================================================================== fonds
class MfTraceFondCredit(models.Model):
    _inherit = 'microfinance.fond.credit'

    @api.model_create_multi
    def create(self, vals_list):
        fonds = super().create(vals_list)
        fonds._mf_trace_created()
        return fonds

    def write(self, vals):
        before = self._mf_snapshot() if FOND_WATCHED & set(vals) else None
        res = super().write(vals)
        if before:
            self._mf_trace_changed(before)
        return res

    @mf_safe
    def _mf_snapshot(self):
        return {fond.id: {
            'bank': fond.bank_id.name, 'origine': mf_selection_label(fond, 'origine'),
            'nature': mf_selection_label(fond, 'nature'), 'destination': mf_selection_label(fond, 'destination'),
            'account': fond.account_id.display_name, 'auto': fond.account_auto,
        } for fond in self.sudo()}

    @mf_safe
    def _mf_trace_created(self):
        entries = []
        for fond in self.sudo():
            details = [
                (_('Nom'), fond.name), (_('Code'), fond.code), (_('Bailleur'), fond.bailleur_id.display_name),
                (_('Portée'), mf_selection_label(fond, 'scope')), (_('Destination'), mf_selection_label(fond, 'destination')),
                (_('Nature'), mf_selection_label(fond, 'nature')), (_('Origine'), mf_selection_label(fond, 'origine')),
                (_('Banque'), fond.bank_id.name), (_('Journal de fonds'), fond.fund_journal_id.display_name),
                (_("Compte d'origine"), (fond.account_id.display_name + (_(' (créé automatiquement)') if fond.account_auto else ''))
                 if fond.account_id else False),
                (_('Créé par'), self.env.user.name)]
            entries.append((fond, _('Fonds créé'), details, None))
        self.env['mf.trace'].mf_trace_batch(entries)

    @mf_safe
    def _mf_trace_changed(self, before):
        labels = (('bank', _('Banque')), ('origine', _('Origine')), ('nature', _('Nature')),
                  ('destination', _('Destination')), ('account', _("Compte d'origine")))
        entries = []
        for fond in self.sudo():
            old, new = before.get(fond.id), self._mf_snapshot_of(fond)
            if not old:
                continue
            changes = [(label, Markup('%s → %s') % (_dash(old[key]), _dash(new[key])))
                       for key, label in labels if old[key] != new[key]]
            if not changes:
                continue
            titre = _('Fonds modifié')
            if not old['account'] and new['account'] and new['auto']:
                titre = _("Fonds modifié : compte d'origine créé")
            entries.append((fond, titre, changes + [(_('Modifié par'), self.env.user.name)], None))
        self.env['mf.trace'].mf_trace_batch(entries)

    def _mf_snapshot_of(self, fond):
        return {'bank': fond.bank_id.name, 'origine': mf_selection_label(fond, 'origine'),
                'nature': mf_selection_label(fond, 'nature'), 'destination': mf_selection_label(fond, 'destination'),
                'account': fond.account_id.display_name, 'auto': fond.account_auto}


# ====================================================================== contribution
class MfTraceFondContribution(models.Model):
    _inherit = 'microfinance.fond.contribution'

    def action_post(self):
        res = super().action_post()
        self._mf_trace_posted()
        return res

    def action_cancel(self):
        res = super(MfTraceFondContribution, self.with_context(**{SKIP_RECONCILE: True})).action_cancel()
        self._mf_trace_cancelled()
        return res

    def _mf_accounts(self, move):
        """(compte de contrepartie, compte en suspens) lus sur la pièce : un dépôt crédite la contrepartie."""
        debit, credit = _side_lines(move)
        return (credit, debit) if self.type_mouvement == 'depot' else (debit, credit)

    @mf_safe
    def _mf_trace_posted(self):
        entries = []
        for contrib in self.sudo():
            fond, move = contrib.fond_id, contrib.move_id
            counterpart, suspense = contrib._mf_accounts(move) if move else (False, False)
            common = [
                (_('Fonds'), mf_link(fond, fond.display_name)), (_('Date'), contrib.date),
                (_('Type de mouvement'), mf_selection_label(contrib, 'type_mouvement')),
                (_('Montant'), mf_amount(contrib.amount)),
                (_("Mode d'encaissement"), mf_selection_label(contrib, 'mode_paiement')),
                (_('Référence'), contrib.reference_paiement)]
            comptable = [
                (_('Journal'), (move.journal_id or contrib.journal_id).display_name),
                (_('Compte de contrepartie'), counterpart.account_id.display_name if counterpart else False),
                (_('Compte en suspens'), suspense.account_id.display_name if suspense else False),
                (_('Pièce comptable'), mf_link(move, move.name) if move else _('aucune (le fonds ne passe pas au grand livre)'))]
            by = [(_('Validée par'), self.env.user.name)]
            entries.append((contrib, _('Contribution validée'), common + comptable + by, None))
            entries.append((fond, _('Contribution validée'), _fund_details(
                fond, [(_('Contribution'), mf_link(contrib, contrib._mf_ref())), (_('Type de mouvement'), mf_selection_label(contrib, 'type_mouvement')),
                       (_('Montant'), mf_amount(contrib.amount)), (_('Journal'), (move.journal_id or contrib.journal_id).display_name),
                       (_('Pièce comptable'), mf_link(move, move.name) if move else False)] + by,
                [(_('Type de mouvement'), mf_selection_label(contrib, 'type_mouvement'))] + by), None))
            if move:
                entries.append((move, _('Créée par la contribution %s') % contrib._mf_ref(), [
                    (_('Source'), mf_link(contrib, contrib._mf_ref())), (_('Fonds'), mf_link(fond, fond.display_name)),
                    (_('Montant'), mf_amount(contrib.amount)), (_('Journal'), move.journal_id.display_name),
                    (_('Compte débité'), _side_lines(move)[0].account_id.display_name),
                    (_('Compte crédité'), _side_lines(move)[1].account_id.display_name),
                    (_('Référence'), contrib.reference_paiement)] + by, None))
        self.env['mf.trace'].mf_trace_batch(entries)

    @mf_safe
    def _mf_trace_cancelled(self):
        entries = []
        by = [(_('Annulée par'), self.env.user.name)]
        for contrib in self.sudo():
            fond, move = contrib.fond_id, contrib.move_id
            reversal = _reversals(move)[:1] if move else move
            entries.append((contrib, _('Contribution annulée'), [
                (_('Fonds'), mf_link(fond, fond.display_name)), (_('Montant'), mf_amount(contrib.amount)),
                (_('Pièce extournée'), mf_link(move, move.name) if move else False),
                (_("Pièce d'extourne"), mf_link(reversal, reversal.name) if reversal else False)] + by, None))
            entries.append((fond, _('Contribution annulée'), _fund_details(
                fond, [(_('Contribution'), mf_link(contrib, contrib._mf_ref())), (_('Montant'), mf_amount(contrib.amount))] + by,
                by), None))
            if move:
                entries.append((move, _('Extournée : annulation de la contribution %s') % contrib._mf_ref(), [
                    (_('Source'), mf_link(contrib, contrib._mf_ref())),
                    (_("Pièce d'extourne"), mf_link(reversal, reversal.name) if reversal else False)] + by, None))
            if reversal:
                entries.append((reversal, _('Créée par l\'annulation de la contribution %s') % contrib._mf_ref(), [
                    (_('Source'), mf_link(contrib, contrib._mf_ref())), (_('Extourne de'), mf_link(move, move.name)),
                    (_('Montant'), mf_amount(contrib.amount))] + by, None))
        self.env['mf.trace'].mf_trace_batch(entries)

    def _mf_ref(self):
        self.ensure_one()
        return _('%(fonds)s du %(date)s (%(type)s)') % {
            'fonds': self.fond_id.code, 'date': self.date, 'type': mf_selection_label(self, 'type_mouvement')}


# ====================================================================== partage
class MfTraceFondPartage(models.Model):
    _inherit = 'microfinance.fond.partage'

    def action_validate(self):
        drafts = self.filtered(lambda p: p.state == 'draft')
        res = super().action_validate()
        drafts._mf_trace_validated()
        return res

    def action_cancel(self):
        todo = self.filtered(lambda p: p.state != 'cancelled')
        validated = todo.filtered(lambda p: p.state == 'validated')
        res = super(MfTraceFondPartage, self.with_context(**{SKIP_RECONCILE: True})).action_cancel()
        todo._mf_trace_cancelled(validated)
        return res

    # -- pièces d'une part : une note sur la pièce du siège, une sur la pièce miroir (qui ne cite QUE sa part)
    def _mf_line_piece_entries(self, line):
        self.ensure_one()
        fond, entries = self.fond_id, []
        by = [(_('Validée par'), self.env.user.name)]
        hq, ag = line.hq_move_id, line.agency_move_id
        if hq:
            own = hq.microfinance_partage_side == 'hq_own'
            titre = _('Créée par le partage %s (part gardée)') if own else _('Créée par le partage %s')
            entries.append((hq, titre % self.name, [
                (_('Source'), mf_link(self, self.name)), (_('Fonds'), mf_link(fond, fond.display_name)),
                (_('Agence'), line.company_id.name), (_('Montant'), mf_amount(line.amount)),
                (_('Journal'), hq.journal_id.display_name),
                (_('Compte débité'), _side_lines(hq)[0].account_id.display_name),
                (_('Compte crédité'), _side_lines(hq)[1].account_id.display_name),
                (_('Pièce côté agence'), mf_link(ag, ag.name) if ag else _('non générée : %s') % _dash(line.liaison_note))] + by, None))
        if ag:
            entries.append((ag, _('Créée par le partage %s') % self.name, [
                (_('Fonds'), fond.code), (_('Référence du partage'), self.name),
                (_('Montant reçu'), mf_amount(line.amount)), (_('Journal'), ag.journal_id.display_name),
                (_('Compte débité'), _side_lines(ag)[0].account_id.display_name),
                (_('Compte crédité'), _side_lines(ag)[1].account_id.display_name)] + by, None))
        return entries

    @mf_safe
    def _mf_trace_validated(self):
        entries = []
        by = [(_('Validé par'), self.env.user.name)]
        for partage in self.sudo():
            fond = partage.fond_id
            lines = partage.line_ids.filtered(lambda l: l.amount > 0)
            listing = []
            for line in lines:
                hq, ag = line.hq_move_id, line.agency_move_id
                parts = [Markup('%s : %s') % (line.company_id.name, mf_amount(line.amount))]
                if hq:
                    parts.append(Markup(_('pièce du siège %s')) % mf_link(hq, hq.name))
                if ag:
                    parts.append(Markup(_('pièce miroir %s')) % mf_link(ag, ag.name))
                elif hq and hq.microfinance_partage_side == 'hq':
                    parts.append(_('côté agence non généré'))
                listing.append(Markup(' — ').join(parts))
            entries.append((partage, _('Partage validé'), [
                (_('Fonds'), mf_link(fond, fond.display_name)), (_('Date'), partage.date),
                (_('Montant partagé'), mf_amount(partage.base_amount)),
                (_('Journal du fonds'), fond.fund_journal_id.display_name),
                (_('Parts par agence'), _listed(listing))] + by, None))
            entries.append((fond, _('Partage validé'), _fund_details(
                fond, [(_('Partage'), mf_link(partage, partage.name)), (_('Montant partagé'), mf_amount(partage.base_amount)),
                       (_('Parts par agence'), _listed(listing))] + by,
                [(_('Partage'), partage.name)] + by), None))
            for line in lines:
                entries.extend(partage._mf_line_piece_entries(line))
        self.env['mf.trace'].mf_trace_batch(entries)

    @mf_safe
    def _mf_trace_cancelled(self, validated):
        entries = []
        by = [(_('Annulé par'), self.env.user.name)]
        for partage in self.sudo():
            fond = partage.fond_id
            originals = partage._liaison_moves() if partage in validated else partage.env['account.move']
            reversals = _reversals(originals)
            pairs = [(move, reversals.filtered(lambda r: r.reversed_entry_id == move)[:1]) for move in originals]
            listing = [Markup(_('%s extournée par %s')) % (mf_link(move, move.name), mf_link(rev, rev.name))
                       for move, rev in pairs if rev]
            entries.append((partage, _('Partage annulé'), [
                (_('Fonds'), mf_link(fond, fond.display_name)), (_('Montant partagé'), mf_amount(partage.base_amount)),
                (_('Pièces extournées'), listing)] + by, None))
            entries.append((fond, _('Partage annulé'), _fund_details(
                fond, [(_('Partage'), mf_link(partage, partage.name)), (_('Montant partagé'), mf_amount(partage.base_amount))] + by,
                [(_('Partage'), partage.name)] + by), None))
            for move, rev in pairs:
                line = move.microfinance_fond_partage_line_id
                side_hq = move.company_id == partage.company_id
                shared = [(_('Montant'), mf_amount(line.amount))] + by
                entries.append((move, _('Extournée : annulation du partage %s') % partage.name,
                                ([(_('Source'), mf_link(partage, partage.name)), (_('Agence'), line.company_id.name)] if side_hq
                                 else [(_('Référence du partage'), partage.name)])
                                + [(_("Pièce d'extourne"), mf_link(rev, rev.name) if rev else False)] + shared, None))
                if rev:
                    entries.append((rev, _("Créée par l'annulation du partage %s") % partage.name,
                                    ([(_('Source'), mf_link(partage, partage.name)), (_('Agence'), line.company_id.name)] if side_hq
                                     else [(_('Référence du partage'), partage.name)])
                                    + [(_('Extourne de'), mf_link(move, move.name))] + shared, None))
        self.env['mf.trace'].mf_trace_batch(entries)


class MfTraceFondPartageLine(models.Model):
    _inherit = 'microfinance.fond.partage.line'

    def action_generate_agency_move(self):
        pending = self.filtered(lambda l: l.partage_id.state == 'validated' and l.hq_move_id and not l.agency_move_id)
        res = super().action_generate_agency_move()
        pending.filtered('agency_move_id')._mf_trace_agency_generated()
        return res

    @mf_safe
    def _mf_trace_agency_generated(self):
        entries = []
        for partage in self.sudo().partage_id:
            lines = self.sudo().filtered(lambda l: l.partage_id == partage)
            entries.append((partage, _('Côté agence généré'), [
                (_('Parts'), [Markup('%s : %s — %s') % (l.company_id.name, mf_amount(l.amount), mf_link(l.agency_move_id, l.agency_move_id.name))
                              for l in lines]), (_('Généré par'), self.env.user.name)], None))
            for line in lines:
                entries.extend(e for e in partage._mf_line_piece_entries(line))
        self.env['mf.trace'].mf_trace_batch(entries)


# ====================================================================== relevé bancaire
class MfTraceBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    @api.model_create_multi
    def create(self, vals_list):
        statements = super().create(vals_list)
        statements.filtered('mf_state')._mf_trace_created()
        return statements

    def action_mf_validate(self):
        drafts = self.filtered(lambda s: s.mf_state == 'draft')
        res = super().action_mf_validate()
        drafts._mf_trace_validated()
        return res

    def _mf_reopen(self, reason):
        validated = self.filtered(lambda s: s.mf_state == 'validated')
        res = super()._mf_reopen(reason)
        validated._mf_trace_reopened(reason)
        return res

    def _mf_period(self):
        self.ensure_one()
        return _('du %(debut)s au %(fin)s') % {'debut': _dash(self.mf_date_from), 'fin': _dash(self.mf_date_to)}

    @mf_safe
    def _mf_trace_created(self):
        self.env['mf.trace'].mf_trace_batch([(stmt, _('Relevé créé'), [
            (_('Journal'), stmt.journal_id.display_name), (_('Période'), stmt._mf_period()),
            (_('Solde initial'), mf_amount(stmt.balance_start)), (_('Solde final imprimé'), mf_amount(stmt.balance_end_real)),
            (_('Créé par'), self.env.user.name)], None) for stmt in self.sudo()])

    @mf_safe
    def _mf_trace_validated(self):
        entries = []
        for stmt in self.sudo():
            lines = stmt.mf_entry_ids
            entries.append((stmt, _('Relevé validé'), [
                (_('Journal'), stmt.journal_id.display_name), (_('Période'), stmt._mf_period()),
                (_('Solde initial'), mf_amount(stmt.balance_start)), (_('Solde final'), mf_amount(stmt.balance_end_real)),
                (_('Lignes'), len(lines)), (_('Total des entrées'), mf_amount(sum(lines.mapped('amount_in')))),
                (_('Total des sorties'), mf_amount(sum(lines.mapped('amount_out')))),
                (_('Lignes à traiter'), len(lines.filtered(lambda l: l.state == 'todo'))),
                (_('Pièce jointe'), _('oui') if stmt.attachment_ids else _('aucune')),
                (_('Validé par'), self.env.user.name)], None))
        self.env['mf.trace'].mf_trace_batch(entries)

    @mf_safe
    def _mf_trace_reopened(self, reason):
        self.env['mf.trace'].mf_trace_batch([(stmt, _('Relevé rouvert'), [
            (_('Motif'), reason), (_('Période'), stmt._mf_period()), (_('Rouvert par'), self.env.user.name)], None)
            for stmt in self.sudo()])


class MfTraceBankStatementEntry(models.Model):
    _inherit = 'microfinance.bank.statement.entry'

    def action_treat(self):
        todo = self.filtered(lambda e: e.state == 'todo')
        res = super(MfTraceBankStatementEntry, self.with_context(**{SKIP_RECONCILE: True})).action_treat()
        todo.filtered(lambda e: e.state == 'done')._mf_trace_treated()
        return res

    def _cancel_treatment(self, reason):
        before = self._mf_snapshot_pieces()
        res = super(MfTraceBankStatementEntry, self.with_context(**{SKIP_RECONCILE: True}))._cancel_treatment(reason)
        self._mf_trace_cancelled(before or {}, reason)
        return res

    def _mf_entry_text(self):
        self.ensure_one()
        return Markup('%s (%s) : %s') % (self.name, _dash(self.date), mf_amount(self.amount))

    @mf_safe
    def _mf_snapshot_pieces(self):
        return {e.id: {'target': e.target_line_id.move_id.id, 'statement': e.statement_line_id.move_id.id,
                       'pointed': e.pointed_line_id.move_id.id} for e in self.sudo()}

    @mf_safe
    def _mf_trace_treated(self):
        entries, who = [], self.env.user.name
        for stmt in self.sudo().statement_id:
            lines, listing = self.sudo().filtered(lambda e: e.statement_id == stmt), []
            for entry in lines:
                target, made = entry.target_line_id.move_id, entry.statement_line_id.move_id
                ref = {'reconcile': lambda: Markup(_('rapprochée avec %s')) % mf_link(target, target.name),
                       'point': lambda: Markup(_('pointée sur %s')) % mf_link(entry.pointed_line_id.move_id),
                       'new': lambda: Markup(_('nouvelle opération %s')) % mf_link(made, made.name)}[entry.treatment]()
                listing.append(Markup('%s — %s') % (entry._mf_entry_text(), ref))
                details = [(_('Ligne du relevé'), entry.name), (_('Date'), entry.date), (_('Référence'), entry.reference),
                           (_('Montant'), mf_amount(entry.amount)), (_('Relevé'), mf_link(stmt, stmt.display_name))]
                if entry.treatment == 'reconcile':
                    entries.append((target, _('Rapprochée avec la ligne « %(l)s » du relevé %(r)s par %(u)s') % {
                        'l': entry.name, 'r': stmt.display_name, 'u': who},
                        details + [(_('Compte'), entry.target_line_id.account_id.display_name),
                                   (_('Pièce du relevé'), mf_link(made, made.name))], None))
                elif entry.treatment == 'point':
                    entries.append((entry.pointed_line_id.move_id, _('Pointée avec la ligne « %(l)s » du relevé %(r)s par %(u)s') % {
                        'l': entry.name, 'r': stmt.display_name, 'u': who}, details, None))
                if made:
                    entries.append((made, _('Créée par la ligne « %(l)s » du relevé %(r)s') % {'l': entry.name, 'r': stmt.display_name},
                                    details + [(_('Traitement'), mf_selection_label(entry, 'treatment')),
                                               (_('Traitée par'), who)], None))
            entries.append((stmt, _('%s ligne(s) du relevé traitée(s)') % len(lines), [
                (_('Lignes'), _listed(listing)), (_('Traité par'), who)], None))
        # la synthèse du relevé est posée même si les messages par pièce dépassent le plafond
        self.env['mf.trace'].mf_trace_batch([e for e in entries if e[0]._name == 'account.bank.statement'])
        self.env['mf.trace'].mf_trace_batch([e for e in entries if e[0]._name != 'account.bank.statement'])

    @mf_safe
    def _mf_trace_cancelled(self, before, reason):
        Move = self.env['account.move'].sudo()
        entries, who = [], self.env.user.name
        for stmt in self.sudo().statement_id:
            listing = []
            for entry in self.sudo().filtered(lambda e: e.statement_id == stmt):
                info = before.get(entry.id, {})
                made, target = Move.browse(info.get('statement')), Move.browse(info.get('target') or info.get('pointed'))
                reversal = _reversals(made)[:1]
                log = self.env['microfinance.bank.statement.log'].sudo().search(
                    [('entry_id', '=', entry.id), ('action', '=', 'cancel')], order='id desc', limit=1)
                listing.append(Markup('%s — %s') % (entry._mf_entry_text(), _dash(log.detail)))
                details = [(_('Ligne du relevé'), entry.name), (_('Montant'), mf_amount(entry.amount)),
                           (_('Relevé'), mf_link(stmt, stmt.display_name)), (_('Motif'), reason), (_('Annulé par'), who)]
                if target:
                    entries.append((target, _('Rapprochement annulé : ligne « %(l)s » du relevé %(r)s') % {
                        'l': entry.name, 'r': stmt.display_name}, details, None))
                if made:
                    entries.append((made, _('Extournée : annulation du traitement de la ligne « %s »') % entry.name,
                                    details + [(_("Pièce d'extourne"), mf_link(reversal, reversal.name) if reversal else False)], None))
                if reversal:
                    entries.append((reversal, _('Créée par l\'annulation du traitement de la ligne « %s »') % entry.name,
                                    details + [(_('Extourne de'), mf_link(made, made.name))], None))
            entries.append((stmt, _('Traitement annulé sur %s ligne(s)') % len(self.sudo().filtered(lambda e: e.statement_id == stmt)), [
                (_('Lignes'), _listed(listing)), (_('Motif'), reason), (_('Annulé par'), who)], None))
        self.env['mf.trace'].mf_trace_batch([e for e in entries if e[0]._name == 'account.bank.statement'])
        self.env['mf.trace'].mf_trace_batch([e for e in entries if e[0]._name != 'account.bank.statement'])


# ====================================================================== lettrage / délettrage
class MfTraceMoveLine(models.Model):
    _inherit = 'account.move.line'

    def reconcile(self):
        wants = self._mf_wants_trace()
        known = self.sudo().matched_debit_ids | self.sudo().matched_credit_ids if wants else None
        res = super().reconcile()
        if wants:
            self._mf_trace_reconciled(known)
        return res

    def remove_move_reconcile(self):
        before = self._mf_snapshot_partials() if self._mf_wants_trace() else None
        res = super().remove_move_reconcile()
        if before:
            self._mf_trace_unreconciled(before)
        return res

    def _mf_wants_trace(self):
        """Test bon marché, avant toute trace : le lettrage des crédits (très fréquent) ne coûte rien de plus."""
        if self.env.context.get(SKIP_RECONCILE):
            return False
        return any(self._mf_is_ampaly_move(move) for move in self.sudo().move_id)

    @api.model
    def _mf_is_ampaly_move(self, move):
        """Pièces concernées : celles des fonds (contribution, partage) et des relevés bancaires."""
        return bool(move.microfinance_fond_contribution_id or move.microfinance_fond_partage_id or move.statement_line_id)

    @api.model
    def _mf_move_origin(self, move):
        if move.microfinance_fond_contribution_id:
            return _('Contribution %s') % move.microfinance_fond_contribution_id._mf_ref()
        if move.microfinance_fond_partage_id:
            return _('Partage %s') % move.microfinance_fond_partage_id.name
        if move.statement_line_id:
            return _('Ligne de relevé « %s »') % move.statement_line_id.payment_ref
        return False

    def _mf_partial_rows(self, partials):
        """[(pièce débit, pièce crédit, compte, montant)] lus avant ou après l'opération."""
        return [(p.debit_move_id.move_id.id, p.credit_move_id.move_id.id, p.debit_move_id.account_id.display_name,
                 p.amount) for p in partials.sudo()]

    @api.model
    def _mf_full_names(self, moves):
        return {m.id: ', '.join(sorted(set(m.line_ids.full_reconcile_id.mapped('display_name')))) for m in moves.sudo()}

    @mf_safe
    def _mf_snapshot_partials(self):
        lines = self.sudo()
        return {'rows': self._mf_partial_rows(lines.matched_debit_ids | lines.matched_credit_ids)}

    @mf_safe
    def _mf_trace_reconciled(self, known):
        """`known` : lettrages déjà présents avant l'opération ; seuls les nouveaux sont décrits."""
        lines = self.sudo()
        new = (lines.matched_debit_ids | lines.matched_credit_ids) - known
        self._mf_trace_pieces(self._mf_partial_rows(new), _('Pièce lettrée'), self._mf_full_names(lines.move_id))

    @mf_safe
    def _mf_trace_unreconciled(self, before):
        self._mf_trace_pieces(before['rows'], _('Pièce délettrée'), None)

    def _mf_trace_pieces(self, rows, titre, full_names):
        """Une note par pièce d'Ampaly concernée (jamais une par ligne) : compte, montant, pièce en face, origine."""
        Move = self.env['account.move'].sudo()
        by_move = {}
        for debit_id, credit_id, account, amount in rows:
            by_move.setdefault(debit_id, []).append((credit_id, account, amount))
            by_move.setdefault(credit_id, []).append((debit_id, account, amount))
        entries = []
        for move in Move.browse(list(by_move)):
            if not self._mf_is_ampaly_move(move):
                continue
            listing = [Markup('%s : %s avec %s') % (account, mf_amount(amount), mf_link(Move.browse(other), Move.browse(other).name))
                       for other, account, amount in by_move[move.id]]
            entries.append((move, titre, [
                (_('Origine'), self._mf_move_origin(move)), (_('Lettrages'), listing),
                (_('Lettrage complet'), (full_names or {}).get(move.id)), (_('Par'), self.env.user.name)], None))
        self.env['mf.trace'].mf_trace_batch(entries)
