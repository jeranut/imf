# -*- coding: utf-8 -*-
"""Partage aux agences et allocation aux portefeuilles : on ne partage et on n'alloue que de l'argent reçu en banque
(ligne en suspens 139100 soldée par une ligne de relevé). Contrôle permanent, sans réglage. Ces classes testent le
contrôle lui-même : elles n'appliquent pas le raccourci « tout est reçu » des anciens tests (TREAT_FUNDS_AS_RECEIVED)."""
from odoo.exceptions import UserError, ValidationError

from . import test_fond_liaison as liaison
from . import test_fond_partage_exploitation as expl

MF = 'microfinance_loan_management.'
M40, M30, M100 = expl.M40, expl.M30, expl.M100
M250, M160, M90, M12, M10, M20 = 250000000.0, 160000000.0, 90000000.0, 12000000.0, 10000000.0, 20000000.0


def _only_own_tests(cls_body, parent):
    """Les tests hérités de la classe de fixtures ne sont pas rejoués ici (ils testent autre chose)."""
    for name in dir(parent):
        if name.startswith('test_'):
            cls_body[name] = None


class TestFondRecuBanqueCredit(liaison.TestFondLiaison):
    """Fonds de crédit : partage (siège → agences, part gardée comprise) puis allocation aux portefeuilles."""
    TREAT_FUNDS_AS_RECEIVED = False
    _only_own_tests(locals(), liaison.TestFondLiaison)

    # ------------------------------------------------------------------ fixtures
    def _fond_of(self, amount):
        fond = self._create_shared_fond(
            verification_disponibilite='at_disbursement', passer_gl=True, bank_id=self.bank.id,
            account_id=self.hq_fond_account.id)
        self._create_contribution(fond, amount=amount).action_post()
        return fond

    def _receive_contribution(self, fond):
        contrib = fond.contribution_ids
        suspense = contrib.move_id.line_ids.filtered(lambda l: l.debit > 0)[:1].account_id
        self._reconcile(contrib.move_id, suspense, self._statement(self.fdbm, contrib.amount, suspense))

    def _share(self, fond, base, shares):
        partage = self.env['microfinance.fond.partage'].create({'fond_id': fond.id, 'base_amount': base})
        for line in partage.line_ids:
            line.percent = shares.get(line.company_id, 0.0)
        return partage

    def _agency_line(self, partage):
        return partage.line_ids.filtered(lambda l: l.company_id == self.agency)

    def _receive_agency(self, partage, amount):
        line = self._agency_line(partage)
        self._reconcile(line.agency_move_id, self.ag_in, self._statement(self.ag_journal, amount, self.ag_in))

    def _portfolio(self, company=None):
        company = company or self.agency
        agent = self.env['res.users'].create({
            'name': 'agent rb %s' % company.id, 'login': 'agent_rb_%s_%s' % (company.id, self.env.cr.now().timestamp()),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref(MF + 'group_microfinance_user').id])]})
        return self.env['microfinance.portfolio'].create({'agent_id': agent.id, 'company_id': company.id})

    def _allocate(self, fond, portfolio, amount):
        return self.env['microfinance.portfolio.allocation'].create({
            'fond_id': fond.id, 'company_id': self.agency.id, 'base_amount': amount,
            'line_ids': [(0, 0, {'portfolio_id': portfolio.id, 'percent': 100.0, 'amount': amount})]})

    def _shared_to_agency(self, amount):
        """Fonds reçu à la banque du siège, partagé entièrement à l'agence ; la ligne 139100 de l'agence n'est pas
        rapprochée."""
        fond = self._fond_of(M250)
        self._receive_contribution(fond)
        partage = self._share(fond, amount, {self.agency: 100.0})
        partage.action_validate()
        return fond, partage

    # ------------------------------------------------------------------ partage
    def test_share_refused_until_the_contribution_is_reconciled_then_capped(self):
        fond = self._fond_of(M250)
        with self.assertRaises(UserError) as caught:
            self._share(fond, M90, {self.agency: 100.0}).action_validate()
        message = str(caught.exception)
        self.assertIn('Montant non disponible', message)
        self.assertIn('reçu en banque 0', message)
        self.assertIn('Saisissez le relevé de la banque pour confirmer l\'encaissement.', message)
        self._receive_contribution(fond)
        first = self._share(fond, M90, {self.agency: 100.0})
        first.action_validate()
        self.assertEqual(first.state, 'validated')
        second = self._share(fond, M160, {self.agency: 100.0})
        second.action_validate()
        self.assertEqual(second.state, 'validated')
        with self.assertRaises(UserError):   # tout le fonds est réparti : refus (reste partageable ou reçu en banque)
            self._share(fond, 1.0, {self.agency: 100.0}).action_validate()

    def test_kept_share_counts_in_the_shared_total(self):
        fond = self._fond_of(M250)
        self._receive_contribution(fond)
        self._share(fond, M250 - 1.0, {self.hq: 100.0}).action_validate()   # tout gardé par le siège
        with self.assertRaises(UserError):
            self._share(fond, 2.0, {self.agency: 100.0}).action_validate()
        self._share(fond, 1.0, {self.agency: 100.0}).action_validate()

    def test_partial_reception_of_the_contribution_caps_the_share(self):
        fond = self._fond_of(M250)
        contrib = fond.contribution_ids
        suspense = contrib.move_id.line_ids.filtered(lambda l: l.debit > 0)[:1].account_id
        self._reconcile(contrib.move_id, suspense, self._statement(self.fdbm, M12, suspense))
        self._share(fond, M12, {self.agency: 100.0}).action_validate()
        with self.assertRaises(UserError):
            self._share(fond, 1.0, {self.agency: 100.0}).action_validate()

    def test_decimal_share_is_refused(self):
        fond = self._fond_of(M250)
        self._receive_contribution(fond)
        with self.assertRaises(ValidationError):
            self._share(fond, 1000.5, {self.agency: 100.0}).action_validate()

    def test_display_fields_follow_the_bank_state(self):
        fond = self._fond_of(M250)
        draft = self._share(fond, M90, {self.agency: 100.0})
        self.assertEqual((draft.fond_recu_banque, draft.fond_deja_reparti, draft.fond_reste_banque), (0.0, 0.0, 0.0))
        self._receive_contribution(fond)
        draft.invalidate_recordset()
        self.assertEqual((draft.fond_recu_banque, draft.fond_deja_reparti, draft.fond_reste_banque),
                         (M250, 0.0, M250))
        draft.action_validate()
        other = self._share(fond, 1000.0, {self.agency: 100.0})
        self.assertEqual((other.fond_recu_banque, other.fond_deja_reparti, other.fond_reste_banque),
                         (M250, M90, M160))
        # le « reste partageable » des tuiles reste calculé sur le contribué : mêmes chiffres qu'avant
        self.assertEqual(fond.reste_partageable, M160)

    # ------------------------------------------------------------------ allocation aux portefeuilles
    def test_allocation_refused_until_the_agency_statement_then_capped(self):
        fond, partage = self._shared_to_agency(M30)
        portfolio = self._portfolio()
        with self.assertRaises(UserError) as caught:
            self._allocate(fond, portfolio, M10).action_validate()
        message = str(caught.exception)
        self.assertIn('Montant non disponible', message)
        self.assertIn('reçu en banque 0', message)
        self.assertIn("Le relevé de l'agence n'a pas encore confirmé cette somme.", message)
        self._receive_agency(partage, M30)
        first = self._allocate(fond, portfolio, M10)
        first.action_validate()
        second = self._allocate(fond, portfolio, M20)
        second.action_validate()
        self.assertEqual(portfolio.amount_allocated, M30)
        with self.assertRaises(UserError) as caught:
            self._allocate(fond, portfolio, 1.0).action_validate()
        self.assertIn('disponible 0', str(caught.exception))
        # une diminution est toujours permise : annuler une répartition libère son montant
        second.action_cancel()
        self.assertEqual(portfolio.amount_allocated, M10)
        self._allocate(fond, portfolio, M20).action_validate()

    def test_only_the_reconciled_part_of_the_share_counts(self):
        fond, partage = self._shared_to_agency(M30)
        self._receive_agency(partage, M12)
        portfolio = self._portfolio()
        self._allocate(fond, portfolio, M12).action_validate()
        with self.assertRaises(UserError):
            self._allocate(fond, portfolio, 1.0).action_validate()

    def test_one_more_than_the_reconciled_part_is_refused(self):
        fond, partage = self._shared_to_agency(M30)
        self._receive_agency(partage, M12)
        with self.assertRaises(UserError):
            self._allocate(fond, self._portfolio(), M12 + 1.0).action_validate()

    def test_decimal_allocation_is_refused(self):
        fond, partage = self._shared_to_agency(M30)
        self._receive_agency(partage, M30)
        with self.assertRaises(ValidationError):
            self._allocate(fond, self._portfolio(), 1000.5).action_validate()

    def test_refusals_leave_existing_amounts_untouched(self):
        fond, partage = self._shared_to_agency(M30)
        portfolio = self._portfolio()
        allocation = fond.allocation_ids.filtered(lambda a: a.company_id == self.agency)
        before = (allocation.amount_allocated, portfolio.amount_allocated, partage.state, partage.base_amount)
        with self.assertRaises(UserError):
            self._allocate(fond, portfolio, M10).action_validate()
        self.assertEqual(
            before, (allocation.amount_allocated, portfolio.amount_allocated, partage.state, partage.base_amount))

    def test_display_fields_of_the_allocation_form(self):
        fond, partage = self._shared_to_agency(M30)
        self._receive_agency(partage, M12)
        portfolio = self._portfolio()
        draft = self._allocate(fond, portfolio, M10)
        self.assertEqual((draft.agence_recu_banque, draft.agence_deja_alloue, draft.agence_allouable), (M12, 0.0, M12))
        draft.action_validate()
        other = self._allocate(fond, portfolio, 1000.0)
        self.assertEqual((other.agence_recu_banque, other.agence_deja_alloue, other.agence_allouable),
                         (M12, M10, M12 - M10))

    def test_disbursement_ceiling_and_its_setting_are_unchanged(self):
        fond, partage = self._shared_to_agency(M30)
        allocation = fond.allocation_ids.filtered(lambda a: a.company_id == self.agency)
        self.assertEqual(allocation._available_for_disbursement(), M30)   # réglage éteint : alloué - utilisé
        self.agency.microfinance_fond_require_received = True
        self.assertEqual(allocation._available_for_disbursement(), 0.0)   # réglage allumé : reçu - utilisé
        self._receive_agency(partage, M12)
        allocation.invalidate_recordset()
        self.assertEqual(allocation._available_for_disbursement(), M12)

    def test_agency_manager_never_reads_another_company(self):
        fond, partage = self._shared_to_agency(M30)
        self._receive_agency(partage, M30)
        repartition = self._allocate(fond, self._portfolio(), M10)
        chef = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'chef autre agence', 'login': 'chef_autre_agence_rb', 'company_id': self.agency2.id,
            'company_ids': [(6, 0, [self.agency2.id])],
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref(MF + 'group_microfinance_gestionnaire').id])]})
        as_chef = self.env['microfinance.portfolio.allocation'].with_user(chef)
        self.assertFalse(as_chef.search([('id', '=', repartition.id)]))
        self.assertFalse(self.env['microfinance.fond.allocation'].with_user(chef).search(
            [('company_id', '=', self.agency.id)]))
        self.assertFalse(self.env['microfinance.fond.partage'].with_user(chef).search([('id', '=', partage.id)]))


class TestFondRecuBanqueExploitation(expl.TestFondPartageExploitation):
    """Fonds d'exploitation : même refus, à la place de l'ancien avertissement non bloquant."""
    TREAT_FUNDS_AS_RECEIVED = False
    _only_own_tests(locals(), expl.TestFondPartageExploitation)

    def _receive(self, fond):
        contrib = fond.contribution_ids
        self._reconcile(contrib.move_id, self.hq_in, self._statement(self.bmop, contrib.amount, self.hq_in))

    def test_share_refused_until_the_contribution_is_reconciled_then_capped(self):
        fond = self._fond()
        with self.assertRaises(UserError) as caught:
            self._partage(fond, {self.ag1: M40}).action_validate()
        message = str(caught.exception)
        self.assertIn('Montant non disponible', message)
        self.assertIn('reçu en banque 0', message)
        self.assertIn('Saisissez le relevé de la banque pour confirmer l\'encaissement.', message)
        self._receive(fond)
        self._partage(fond, {self.ag1: M40}).action_validate()
        self._partage(fond, {self.ag2: M30, self.ag1: M30}).action_validate()
        with self.assertRaises(UserError):
            self._partage(fond, {self.ag1: 1.0}).action_validate()

    def test_old_warning_is_gone(self):
        self.assertNotIn('bank_warning', self.env['microfinance.fond.partage']._fields)

    def test_display_fields(self):
        fond = self._fond()
        draft = self._partage(fond, {self.ag1: M40})
        self.assertEqual((draft.fond_recu_banque, draft.fond_deja_reparti, draft.fond_reste_banque), (0.0, 0.0, 0.0))
        self._receive(fond)
        draft.invalidate_recordset()
        self.assertEqual((draft.fond_recu_banque, draft.fond_deja_reparti, draft.fond_reste_banque),
                         (M100, 0.0, M100))
