# -*- coding: utf-8 -*-
from .test_fond_origine import TestFondOrigine
from .test_fond_liaison import TestFondLiaison


class TestFondSiegeN1N2(TestFondLiaison):
    """La société mère est à la fois le siège (N1 : bailleur → banque du siège) et une agence (N2 : partages).
    N1 « Fonds reçus à répartir (siège) » : contribué, en transit, reçu en banque, reste à répartir (faits bancaires
    bruts, non nets du partagé). N2 « Part allouée » : inchangé, part gardée du siège comprise (transit réel)."""

    _auto_fond = TestFondOrigine._auto_fond
    _deposit = TestFondOrigine._deposit

    DEPOSIT = 150000.0
    SHARE_AGENCY = 40000.0
    SHARE_HQ = 20000.0

    def _n1(self, fond, company=None):
        fond = fond.with_company(company or self.hq)
        fond.invalidate_recordset()
        return (fond.siege_contribue, fond.siege_en_transit, fond.siege_recu_banque)

    def _n2(self, fond, company):
        allocation = self.env['microfinance.fond.allocation'].sudo().search(
            [('fond_id', '=', fond.id), ('company_id', '=', company.id)])
        allocation.invalidate_recordset()
        return (allocation.amount_allocated, allocation.amount_in_transit, allocation.amount_received)

    def _bank_in(self, contribution):
        """Relevé du journal de fonds du siège qui lettre la 139100 de la contribution."""
        account = self.env['microfinance.fond.partage']._payment_account(self.fdbm, 'inbound')
        self._reconcile(contribution.move_id, account, self._statement(self.fdbm, contribution.amount, account))

    def _share(self, fond):
        partage = self.env['microfinance.fond.partage'].create({
            'fond_id': fond.id, 'base_amount': self.SHARE_AGENCY + self.SHARE_HQ})
        partage.line_ids.filtered(lambda l: l.company_id == self.hq).write({'amount': self.SHARE_HQ})
        partage.line_ids.filtered(lambda l: l.company_id == self.agency).write({'amount': self.SHARE_AGENCY})
        partage.action_validate()
        return partage

    def test_n1_contribution_in_transit_then_received(self):
        fond = self._auto_fond()
        contribution = self._deposit(fond, self.DEPOSIT)
        # fonds contribué, jamais partagé : visible au siège, en transit (aucune allocation, N2 vide)
        self.assertEqual(self._n1(fond), (self.DEPOSIT, self.DEPOSIT, 0.0))
        self.assertFalse(fond.allocation_ids)
        # le relevé du siège lettre la 139100 : reçu en banque
        self._bank_in(contribution)
        self.assertEqual(self._n1(fond), (self.DEPOSIT, 0.0, self.DEPOSIT))

    def test_n1_is_gross_and_n2_is_independent_after_sharing(self):
        fond = self._auto_fond()
        contribution = self._deposit(fond, self.DEPOSIT)
        self._bank_in(contribution)
        partage = self._share(fond)
        # N1 : faits bancaires bruts, inchangés par le partage
        self.assertEqual(self._n1(fond), (self.DEPOSIT, 0.0, self.DEPOSIT))
        # N2 agence X : en transit tant que son relevé n'a pas lettré sa 139100
        self.assertEqual(self._n2(fond, self.agency), (self.SHARE_AGENCY, self.SHARE_AGENCY, 0.0))
        # N2 siège (part gardée) : transit réel, aucune exception pour le siège
        self.assertEqual(self._n2(fond, self.hq), (self.SHARE_HQ, self.SHARE_HQ, 0.0))
        # N1 contribué = reçu + transit ; N1 reste à répartir + Σ allocations = contribué
        contribue, transit, recu = self._n1(fond)
        self.assertEqual(contribue, recu + transit)
        fond.invalidate_recordset()
        allocated = sum(fond.sudo().allocation_ids.mapped('amount_allocated'))
        self.assertEqual(fond.reste_partageable, self.DEPOSIT - self.SHARE_AGENCY - self.SHARE_HQ)
        self.assertEqual(fond.reste_partageable + allocated, contribue)
        # le relevé de l'agence X lettre sa 139100 : reçu pour X seulement
        mirror = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self._reconcile(mirror, self.ag_in, self._statement(self.ag_journal, self.SHARE_AGENCY, self.ag_in))
        self.assertEqual(self._n2(fond, self.agency), (self.SHARE_AGENCY, 0.0, self.SHARE_AGENCY))
        self.assertEqual(self._n2(fond, self.hq), (self.SHARE_HQ, self.SHARE_HQ, 0.0))
        self.assertEqual(self._n1(fond), (self.DEPOSIT, 0.0, self.DEPOSIT))

    def test_kept_share_in_transit_until_credit_statement_then_received(self):
        fond = self._auto_fond()
        self._bank_in(self._deposit(fond, self.DEPOSIT))
        partage = self._share(fond)
        own = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'hq_own')
        credit_journal = partage._credit_journal_for(self.fdbm, self.hq)
        inbound = partage._payment_account(credit_journal, 'inbound')
        self.assertEqual(self._n2(fond, self.hq), (self.SHARE_HQ, self.SHARE_HQ, 0.0))
        # le relevé du journal de fonds ne solde que le 139500, pas la 139100 : toujours en transit
        outbound = partage._payment_account(self.fdbm, 'outbound')
        self._reconcile(own, outbound, self._statement(self.fdbm, -self.SHARE_HQ, outbound))
        self.assertEqual(self._n2(fond, self.hq), (self.SHARE_HQ, self.SHARE_HQ, 0.0))
        # le relevé du journal crédit lettre la 139100 : reçue
        self._reconcile(own, inbound, self._statement(credit_journal, self.SHARE_HQ, inbound))
        self.assertEqual(self._n2(fond, self.hq), (self.SHARE_HQ, 0.0, self.SHARE_HQ))
        self.assertEqual(self._n1(fond), (self.DEPOSIT, 0.0, self.DEPOSIT))

    def test_agency_never_sees_n1(self):
        fond = self._auto_fond()
        self._deposit(fond, self.DEPOSIT)
        self._share(fond)
        agency_fond = fond.with_company(self.agency)
        self.assertFalse(agency_fond.siege_view)
        self.assertEqual(self._n1(fond, self.agency), (0.0, 0.0, 0.0))
        self.assertTrue(fond.with_company(self.hq).siege_view)

    def test_withdrawal_is_net_of_contributions(self):
        fond = self._auto_fond()
        self._bank_in(self._deposit(fond, self.DEPOSIT))
        withdrawal = self._create_contribution(fond, amount=10000.0, type_mouvement='retrait')
        withdrawal.action_post()
        self.assertEqual(self._n1(fond), (self.DEPOSIT - 10000.0, -10000.0, self.DEPOSIT))
        outbound = self.env['microfinance.fond.partage']._payment_account(self.fdbm, 'outbound')
        self._reconcile(withdrawal.move_id, outbound, self._statement(self.fdbm, -10000.0, outbound))
        self.assertEqual(self._n1(fond), (self.DEPOSIT - 10000.0, 0.0, self.DEPOSIT - 10000.0))

    def test_parent_sees_fund_without_allocation_in_accessible_funds(self):
        fond = self._auto_fond()
        self._deposit(fond, self.DEPOSIT)
        Fond = self.env['microfinance.fond.credit']
        self.assertIn(fond, Fond._get_agency_accessible_funds(self.hq.id)[0])
        self.assertNotIn(fond, Fond._get_agency_accessible_funds(self.agency.id)[0])
        # la tuile N1 lit les mêmes champs que la liste
        amounts = Fond._get_siege_fund_amounts(self.hq.id, fond)
        self.assertEqual((amounts['contribue'], amounts['en_transit'], amounts['recu_banque'], amounts['reste']),
                         (self.DEPOSIT, self.DEPOSIT, 0.0, self.DEPOSIT))

    # ------------------------------------------------------------------ banque du relevé à saisir
    def test_transit_note_single_and_multiple_banks(self):
        Fond = self.env['microfinance.fond.credit']
        other = self.env['res.bank'].create({'name': 'Zeta banque (test)'})
        self.ag_journal.microfinance_bank_id = other
        self.assertEqual(Fond._transit_note([(self.fdbm, 100000.0)]), 'BMOI liaison (test)')
        self.assertEqual(Fond._transit_note([(self.fdbm, 100000.0)], with_journal=True),
                         'BMOI liaison (test) (relevé %s)' % self.fdbm.name)
        self.assertEqual(Fond._transit_note([(self.fdbm, 100000000.0), (self.ag_journal, 50500000.0)]),
                         'BMOI liaison (test) 100 M · Zeta banque (test) 50,5 M')
        # rien en transit (nul, négatif) : aucune mention
        self.assertEqual(Fond._transit_note([(self.fdbm, 0.0)]), '')
        self.assertEqual(Fond._transit_note([(self.fdbm, -5.0)]), '')
        self.assertEqual(Fond._transit_note([]), '')

    def test_transit_bank_note_follows_the_unreconciled_line(self):
        fond = self._auto_fond()
        contribution = self._deposit(fond, self.DEPOSIT)
        # N1 : journal de fonds du siège
        fond.invalidate_recordset()
        self.assertEqual(fond.with_company(self.hq).transit_banque_siege, 'BMOI liaison (test) (relevé %s)' % self.fdbm.name)
        self.assertEqual(fond._transit_note_for(fond.with_company(self.hq), 'siege'), 'BMOI liaison (test)')
        self._bank_in(contribution)
        fond.invalidate_recordset()
        self.assertEqual(fond.with_company(self.hq).transit_banque_siege, '')
        self.assertEqual(fond._transit_note_for(fond.with_company(self.hq), 'siege'), '')
        # N2 : journal crédit de l'agence destinataire ; part gardée = journal crédit du siège
        partage = self._share(fond)
        credit_name = partage._credit_journal_for(self.fdbm, self.hq).name
        fond.invalidate_recordset()
        self.assertEqual(fond.with_company(self.agency).transit_banque_agence,
                         'BMOI liaison (test) (relevé %s)' % self.ag_journal.name)
        self.assertEqual(fond.with_company(self.hq).transit_banque_agence, 'BMOI liaison (test) (relevé %s)' % credit_name)
        own_line = partage.line_ids.filtered(lambda l: l.company_id == self.hq)
        self.assertEqual(own_line._bank_state()[3], partage._credit_journal_for(self.fdbm, self.hq))
        # les relevés lettrent les 139100 : plus rien à saisir
        mirror = self._moves(partage).filtered(lambda m: m.microfinance_partage_side == 'agency')
        self._reconcile(mirror, self.ag_in, self._statement(self.ag_journal, self.SHARE_AGENCY, self.ag_in))
        fond.invalidate_recordset()
        self.assertEqual(fond.with_company(self.agency).transit_banque_agence, '')
        self.assertEqual(fond.with_company(self.hq).transit_banque_agence, 'BMOI liaison (test) (relevé %s)' % credit_name)

    def test_agency_does_not_get_siege_bank_note(self):
        fond = self._auto_fond()
        self._deposit(fond, self.DEPOSIT)
        self.assertEqual(fond.with_company(self.agency).transit_banque_siege, '')

    def test_dashboard_tile_main_value_is_allocated_amount_with_bank_note(self):
        fond = self._auto_fond()
        self._bank_in(self._deposit(fond, self.DEPOSIT))
        self._share(fond)
        tiles = {t['key']: t for t in self.env['microfinance.loan'].get_dashboard_data()['tiles']}
        tile = tiles['fund_count']
        Fond = self.env['microfinance.fond.credit']
        funds, _solde = Fond._get_agency_accessible_funds(self.hq.id)
        self.assertIn(fond, funds)
        # tuile = liste : chiffre principal = Σ « Alloué (ma part) » des fonds listés, en Ar
        self.assertEqual(tile['type'], 'money')
        self.assertEqual(tile['value'], sum(Fond.search(tile['domain']).with_company(self.hq).mapped('agency_allocated')))
        self.assertGreaterEqual(tile['value'], self.SHARE_HQ)
        self.assertFalse(tile.get('secondary_label'))
        items = {i['label']: i for i in tile['secondary_items']}
        self.assertTrue(items['%d fonds' % len(funds)]['text'])
        amounts = Fond._get_agency_fund_amounts(self.hq.id, funds)
        self.assertEqual(items['En transit']['value'], amounts['in_transit'])
        self.assertIn('BMOI liaison (test)', items['En transit']['note'])
        self.assertFalse(items['Reçu en banque'].get('note'))
        self.assertEqual(tiles['siege_funds']['secondary_items'][0]['label'], 'En transit')
        self.assertNotIn('BMOI liaison (test)', tiles['siege_funds']['secondary_items'][0]['note'])  # N1 reçu
