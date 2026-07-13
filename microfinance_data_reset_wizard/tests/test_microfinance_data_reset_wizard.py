# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError

from .common import MicrofinanceDataResetCommon


class TestMicrofinanceDataResetWizard(MicrofinanceDataResetCommon):
    """Toutes les exécutions "réelles" (non dry-run) portent exclusivement sur une
    agence de test dédiée (self.company), jamais sur self.env.company : dans MOWGLI,
    self.env.company résout vers une agence CEFOR réelle (id=1, "CEFOR Isotry") qui
    porte de vraies données de production. Un test qui supprimerait par erreur des
    données réelles resterait annulé par le rollback de TransactionCase, mais autant
    ne jamais s'approcher de cette dépendance : chaque test construit sa propre
    société isolée via _setup_second_company()."""

    def setUp(self):
        super().setUp()
        self.company, self.product, self.savings_product, self.payment_journal, self.partner = \
            self._setup_second_company('T1')

    # 1. Dry-run sans données : journal à 0 partout, aucune erreur.
    def test_dry_run_empty_company(self):
        wizard = self._make_wizard(self.company)
        wizard.action_start_dry_run()
        wizard.action_process_all_remaining()
        self.assertEqual(wizard.state, 'done')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertIn('0 microfinance.loan supprimés', wizard.log)
        self.assertIn('0 microfinance.loan.payment supprimés', wizard.log)
        self.assertIn('0 microfinance.savings.account supprimés', wizard.log)

    # 2. Dry-run avec données : rollback effectif, rien n'est supprimé.
    def test_dry_run_with_data_rolls_back(self):
        loan, payment, visit, account = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )
        move_ids = (loan.move_ids | payment.move_id).ids

        wizard = self._make_wizard(self.company)
        wizard.action_start_dry_run()
        wizard.action_process_all_remaining()

        self.assertEqual(wizard.state, 'done')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertTrue(loan.exists())
        self.assertTrue(payment.exists())
        self.assertTrue(visit.exists())
        self.assertTrue(account.exists())
        self.assertEqual(len(self.env['account.move'].browse(move_ids).exists()), len(move_ids))
        self.assertIn('1 microfinance.loan supprimés', wizard.log)
        self.assertIn('1 microfinance.loan.payment supprimés', wizard.log)
        self.assertIn('1 microfinance.savings.account supprimés', wizard.log)

    # 3. Exécution réelle : aucun blocage FK/état, écritures comptables liées supprimées.
    def test_execute_real_respects_fk_order(self):
        loan, payment, visit, account = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )
        move_ids = (loan.move_ids | payment.move_id).ids
        self.assertTrue(move_ids)

        wizard = self._make_wizard(self.company, i_confirm=True, confirm_text='SUPPRIMER')
        wizard.action_start_execute()
        wizard.action_process_all_remaining()

        self.assertEqual(wizard.state, 'done')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(loan.exists())
        self.assertFalse(payment.exists())
        self.assertFalse(visit.exists())
        self.assertFalse(account.exists())
        self.assertFalse(self.env['account.move'].sudo().browse(move_ids).exists())

    # 4. Isolation multi-agence : RAZ scopé sur A n'affecte jamais B.
    def test_multi_company_isolation(self):
        company_b, product_b, savings_product_b, payment_journal_b, partner_b = \
            self._setup_second_company('T2')
        loan_a, payment_a, visit_a, account_a = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )
        loan_b, payment_b, visit_b, account_b = self._create_full_dataset(
            partner=partner_b, product=product_b, savings_product=savings_product_b,
            payment_journal=payment_journal_b,
        )

        wizard = self._make_wizard(self.company, i_confirm=True, confirm_text='SUPPRIMER')
        wizard.action_start_execute()
        wizard.action_process_all_remaining()

        self.assertEqual(wizard.state, 'done')
        self.assertNotIn('ERREUR', wizard.log)
        self.assertFalse(loan_a.exists())
        self.assertFalse(payment_a.exists())
        self.assertFalse(visit_a.exists())
        self.assertFalse(account_a.exists())
        # Agence B jamais sélectionnée : tout doit rester intact.
        self.assertTrue(loan_b.exists())
        self.assertTrue(payment_b.exists())
        self.assertTrue(visit_b.exists())
        self.assertTrue(account_b.exists())

    # 5. Isolation res.partner : le client survit à la RAZ complète de son agence.
    def test_partner_survives_full_reset(self):
        loan, payment, visit, account = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )
        partner = loan.partner_id

        wizard = self._make_wizard(self.company, i_confirm=True, confirm_text='SUPPRIMER')
        wizard.action_start_execute()
        wizard.action_process_all_remaining()

        self.assertEqual(wizard.state, 'done')
        self.assertFalse(loan.exists())
        self.assertTrue(partner.exists())

    # 6. Isolation EAT/MIIA : une société sans agency_code (contournement direct en
    # base, hors ORM/UI) ne peut jamais être traitée, même si elle est forcée dans
    # company_ids.
    def test_out_of_scope_company_guard(self):
        other_company = self.env['res.company'].create({'name': 'Agence Guard Test', 'agency_code': 'GD'})
        # Contournement direct (bypass de la validation ORM create()/write() sur
        # agency_code) : simule une société tamponnée hors du chemin normal, comme le
        # ferait un accès shell direct.
        self.env.cr.execute("UPDATE res_company SET agency_code = NULL WHERE id = %s", (other_company.id,))
        other_company.invalidate_recordset()
        self.assertFalse(other_company.agency_code)

        wizard = self.Wizard.create({
            'company_ids': [(4, other_company.id)],
            'i_confirm': True,
            'confirm_text': 'SUPPRIMER',
        })
        with self.assertRaises(UserError):
            wizard.action_start_execute()
        self.assertEqual(wizard.state, 'draft')

    # 7. Confirmation renforcée : sans le mot exact "SUPPRIMER", aucune suppression.
    def test_confirm_text_required(self):
        loan, payment, visit, account = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )
        wizard = self._make_wizard(self.company, i_confirm=True, confirm_text='pas le bon mot')
        with self.assertRaises(UserError):
            wizard.action_start_execute()
        self.assertEqual(wizard.state, 'draft')
        self.assertTrue(loan.exists())

    # 8. Verrou anti-concurrence : une deuxième transaction ne peut pas avancer tant
    # que la première tient le verrou.
    def test_concurrent_lock_blocks_second_transaction(self):
        wizard = self._make_wizard(self.company)
        wizard.action_start_dry_run()

        cr2 = self.registry.cursor()
        try:
            cr2.execute("SELECT pg_try_advisory_xact_lock(%s)", (self.Wizard._LOCK_KEY,))
            self.assertTrue(cr2.fetchone()[0], "Le deuxième curseur devrait pouvoir prendre le verrou en premier")
            with self.assertRaises(UserError):
                wizard.action_process_next_step()
        finally:
            cr2.rollback()
            cr2.close()

    # 9. Reprise après interruption : une panne au milieu du traitement d'une agence
    # n'empêche pas de reprendre au prochain "étape suivante", sans dupliquer les
    # suppressions déjà commitées.
    def test_resume_after_interruption(self):
        loan, payment, visit, account = self._create_full_dataset(
            partner=self.partner, product=self.product,
            savings_product=self.savings_product, payment_journal=self.payment_journal,
        )

        wizard = self._make_wizard(self.company, i_confirm=True, confirm_text='SUPPRIMER')
        wizard.action_start_execute()
        # Simule la fin de la requête HTTP qui a démarré l'exécution : dans une vraie
        # utilisation, action_start_execute() et action_process_next_step() sont deux
        # requêtes/transactions séparées.
        self.env.cr.commit()

        original_batch_unlink = type(wizard)._batch_unlink
        call_count = {'n': 0}

        def flaky_batch_unlink(self, *args, **kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise RuntimeError("Panne simulée pour tester la reprise")
            return original_batch_unlink(self, *args, **kwargs)

        with patch.object(type(wizard), '_batch_unlink', flaky_batch_unlink):
            wizard.action_process_next_step()

        self.assertIn('ERREUR', wizard.log)
        self.assertIn(self.company, wizard.pending_company_ids)
        self.assertTrue(loan.exists(), "Rien ne doit être committé si la panne survient sur le premier lot")

        # Reprise : relance de la même étape, sans la panne cette fois.
        wizard.action_process_next_step()

        self.assertNotIn(self.company, wizard.pending_company_ids)
        self.assertFalse(loan.exists())
        self.assertFalse(payment.exists())
        self.assertFalse(visit.exists())
        self.assertFalse(account.exists())
