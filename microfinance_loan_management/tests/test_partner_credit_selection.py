# -*- coding: utf-8 -*-
import unittest

from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestPartnerCreditSelectionIndependent(MicrofinanceCommon):
    """Section CRÉDIT de la fiche client, mode 'Produit indépendant' : création/réutilisation
    automatique du dossier d'instruction à l'enregistrement (cf. prompt fiche client crédit)."""

    def test_selecting_independent_product_creates_draft_application(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Sélection Indépendante',
            'microfinance_partner_type': 'client',
            'microfinance_selected_product_id': self.product.id,
        })
        application = partner.microfinance_current_loan_application_id
        self.assertTrue(application)
        self.assertEqual(application.partner_id, partner)
        self.assertEqual(application.loan_product_id, self.product)
        self.assertEqual(application.state, 'draft')

    def test_reusing_existing_draft_application_no_duplicate(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Réutilisation',
            'microfinance_partner_type': 'client',
        })
        existing = self.env['microfinance.loan.application'].create({
            'partner_id': partner.id, 'loan_product_id': self.product.id, 'company_id': self.env.company.id,
        })
        partner.with_context(microfinance_context=True).write({'microfinance_selected_product_id': self.product.id})
        self.assertEqual(partner.microfinance_current_loan_application_id, existing)
        count = self.env['microfinance.loan.application'].search_count([
            ('partner_id', '=', partner.id), ('loan_product_id', '=', self.product.id),
        ])
        self.assertEqual(count, 1)

    def test_no_product_selected_no_application_created_no_error(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Sans Produit',
            'microfinance_partner_type': 'client',
        })
        self.assertFalse(partner.microfinance_current_loan_application_id)
        count = self.env['microfinance.loan.application'].search_count([('partner_id', '=', partner.id)])
        self.assertEqual(count, 0)

    def test_independent_product_rejected_under_progressive_policy(self):
        # self.product n'appartient à aucun programme progressif dans cette classe de test :
        # il ne peut donc pas être choisi si la politique globale est réglée sur 'progressive'.
        self._set_product_policy('progressive')
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Incohérence Politique',
            'microfinance_partner_type': 'client',
        })
        with self.assertRaises(ValidationError):
            partner.with_context(microfinance_context=True).write({
                'microfinance_selected_product_id': self.product.id,
            })


class TestPartnerCreditSelectionProgressiveEligibility(MicrofinanceCommon):
    """microfinance_progressive_eligible_product_ids : réutilise _evaluate_progressive_eligibility
    de microfinance.loan.application (jamais dupliqué), en ajoutant l'inclusion systématique de
    la 1ère étape (aucun prérequis, sinon aucun client ne pourrait jamais entrer dans un
    programme progressif via la politique 'Produit progressif')."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_step1 = cls.env['microfinance.loan.product'].create({
            'name': 'Prêt initial (test sélection crédit)', 'code': 'PSEL1',
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.disbursement_journal.id, 'payment_journal_id': cls.payment_journal.id,
            'account_principal_individuel_id': cls.loan_account.id,
            'account_principal_groupe_id': cls.loan_account_groupe.id,
            'account_interets_recus_individuel_id': cls.interest_account.id,
            'account_interets_recus_groupe_id': cls.interest_account_groupe.id,
        })
        cls.program = cls.env['microfinance.loan.progressive.program'].create({
            'name': 'Programme test sélection crédit',
            'step_ids': [
                (0, 0, {
                    'sequence_number': 1, 'product_id': cls.product_step1.id,
                    'late_tolerance_days': 7, 'late_tolerance_amount_percent': 5.0,
                }),
                (0, 0, {
                    'sequence_number': 2, 'product_id': cls.product.id,
                    'late_tolerance_days': 7, 'late_tolerance_amount_percent': 5.0,
                }),
            ],
        })

    def _new_client_partner(self, name, **kwargs):
        vals = {'name': name, 'microfinance_partner_type': 'client'}
        vals.update(kwargs)
        return self.env['res.partner'].with_context(microfinance_context=True).create(vals)

    def _close_step1_loan_without_arrears(self, partner):
        loan = self._create_loan(partner_id=partner.id, product_id=self.product_step1.id)
        loan.action_generate_schedule()
        for inst in loan.installment_ids:
            inst.write({
                'paid_principal': inst.principal_amount,
                'paid_interest': inst.interest_amount,
                'paid_penalty': inst.penalty_amount,
            })
        loan.action_close()
        return loan

    def test_zero_eligible_products_for_partner_in_another_company(self):
        # Aucun produit de programme progressif n'est rattaché à cette société : liste vide.
        company_b = self.env['res.company'].create({
            'name': 'Agence B (test sélection crédit)', 'agency_code': 'PSB',
        })
        partner = self._new_client_partner('Client Test 0 éligible', company_id=company_b.id)
        self.assertFalse(partner.microfinance_progressive_eligible_product_ids)

    def test_one_eligible_product_before_any_prior_loan(self):
        # Seule la 1ère étape (aucun prérequis) est accessible tant que le prêt initial n'a
        # pas été pris.
        partner = self._new_client_partner('Client Test 1 éligible')
        eligible = partner.microfinance_progressive_eligible_product_ids
        self.assertEqual(eligible, self.product_step1)

    def test_two_eligible_products_after_step1_closed_without_arrears(self):
        # Une fois le prêt d'étape 1 clôturé sans retard, l'étape 2 devient éligible en plus
        # de l'étape 1 (toujours accessible, cf. décision de conception validée).
        partner = self._new_client_partner('Client Test 2 éligibles')
        self._close_step1_loan_without_arrears(partner)
        partner.invalidate_recordset(['microfinance_progressive_eligible_product_ids'])
        eligible = partner.microfinance_progressive_eligible_product_ids
        self.assertEqual(set(eligible.ids), {self.product_step1.id, self.product.id})

    def test_progressive_product_selection_allowed_when_eligible(self):
        self._set_product_policy('progressive')
        partner = self._new_client_partner('Client Test Sélection Progressive')
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.product_step1.id,
        })
        self.assertEqual(partner.microfinance_selected_product_id, self.product_step1)
        application = partner.microfinance_current_loan_application_id
        self.assertEqual(application.loan_product_id, self.product_step1)

    def test_progressive_product_selection_rejected_when_not_yet_eligible(self):
        self._set_product_policy('progressive')
        partner = self._new_client_partner('Client Test Sélection Progressive Refusée')
        with self.assertRaises(ValidationError):
            partner.with_context(microfinance_context=True).write({
                'microfinance_selected_product_id': self.product.id,
            })


class TestPartnerCreditSelectionProductPolicy(MicrofinanceCommon):
    """Politique de produit globale (Microfinance > Configuration > Paramètres) : un seul
    réglage pour tout le système (pas par société), aucun traitement rétroactif sur les
    dossiers/crédits déjà créés lors d'un changement de politique."""

    def test_default_policy_is_independent(self):
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Politique Défaut', 'microfinance_partner_type': 'client',
        })
        self.assertEqual(partner.microfinance_product_policy, 'independent')

    def test_policy_reflects_global_config_parameter(self):
        self._set_product_policy('progressive')
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Politique Globale', 'microfinance_partner_type': 'client',
        })
        self.assertEqual(partner.microfinance_product_policy, 'progressive')

    def test_policy_is_not_per_company(self):
        # Un seul réglage pour tout le système : un client d'une autre société lit la même
        # valeur globale, pas un réglage dupliqué par agence.
        self._set_product_policy('progressive')
        company_b = self.env['res.company'].create({
            'name': 'Agence B (test politique produit)', 'agency_code': 'PPB',
        })
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Politique Autre Société',
            'microfinance_partner_type': 'client',
            'company_id': company_b.id,
        })
        self.assertEqual(partner.microfinance_product_policy, 'progressive')

    def test_policy_change_does_not_affect_existing_application(self):
        # Dossier créé sous la politique 'indépendant' (réglage par défaut).
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Changement Politique',
            'microfinance_partner_type': 'client',
            'microfinance_selected_product_id': self.product.id,
        })
        application = partner.microfinance_current_loan_application_id
        self.assertEqual(application.loan_product_id, self.product)
        self.assertEqual(application.state, 'draft')

        # Changement de politique en cours de route.
        self._set_product_policy('progressive')

        # Aucun traitement rétroactif : le dossier et la sélection déjà en place restent
        # inchangés.
        application.invalidate_recordset()
        self.assertEqual(application.loan_product_id, self.product)
        self.assertEqual(application.state, 'draft')
        self.assertEqual(partner.microfinance_selected_product_id, self.product)

        # Un nouveau client, créé après le changement, suit désormais la nouvelle politique :
        # self.product (produit indépendant, hors programme progressif) n'est plus sélectionnable.
        other_partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Nouvelle Politique', 'microfinance_partner_type': 'client',
        })
        with self.assertRaises(ValidationError):
            other_partner.with_context(microfinance_context=True).write({
                'microfinance_selected_product_id': self.product.id,
            })


class TestPartnerCreditSelectionProductLock(MicrofinanceCommon):
    """Verrou de changement de produit : bloqué tant que le dossier courant est en cours
    d'instruction ou que le crédit qui en est issu n'est ni clôturé ni annulé."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_product = cls.env['microfinance.loan.product'].create({
            'name': 'Autre produit (test verrou)', 'code': 'PLOCK',
            'min_amount': 100.0, 'max_amount': 100000.0, 'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat', 'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': cls.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'disbursement_journal_id': cls.disbursement_journal.id, 'payment_journal_id': cls.payment_journal.id,
            'account_principal_individuel_id': cls.loan_account.id,
            'account_principal_groupe_id': cls.loan_account_groupe.id,
            'account_interets_recus_individuel_id': cls.interest_account.id,
            'account_interets_recus_groupe_id': cls.interest_account_groupe.id,
        })

    def _advance_application_to_loan_created(self, application):
        # Le wizard "Créer le crédit" a été supprimé (retour à la création directe de
        # microfinance.loan, cf. réversion du point d'entrée unique) : loan_id reste un champ
        # normal (readonly en vue seulement, jamais côté ORM), rattaché ici directement pour
        # reproduire le seul rattachement manuel désormais possible.
        application.action_start_visite()
        application.action_start_contre_visite()
        application.action_mark_fait()
        loan = self.env['microfinance.loan'].create({
            'partner_id': application.partner_id.id,
            'product_id': application.loan_product_id.id,
            'loan_amount': 1000.0,
            'term': 6,
        })
        application.write({'loan_id': loan.id})
        return loan

    def _new_partner_with_product(self):
        return self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': 'Client Test Verrou',
            'microfinance_partner_type': 'client',
            'microfinance_selected_product_id': self.product.id,
        })

    def test_change_blocked_while_application_in_progress(self):
        partner = self._new_partner_with_product()
        application = partner.microfinance_current_loan_application_id
        application.action_start_visite()
        with self.assertRaises(ValidationError):
            partner.with_context(microfinance_context=True).write({
                'microfinance_selected_product_id': self.other_product.id,
            })

    def test_change_blocked_while_loan_active_then_allowed_once_closed(self):
        partner = self._new_partner_with_product()
        application = partner.microfinance_current_loan_application_id
        loan = self._advance_application_to_loan_created(application)
        loan.write({'state': 'active'})
        with self.assertRaises(ValidationError):
            partner.with_context(microfinance_context=True).write({
                'microfinance_selected_product_id': self.other_product.id,
            })
        loan.write({'state': 'closed'})
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.other_product.id,
        })
        self.assertEqual(partner.microfinance_selected_product_id, self.other_product)

    def test_change_allowed_once_loan_cancelled(self):
        partner = self._new_partner_with_product()
        application = partner.microfinance_current_loan_application_id
        loan = self._advance_application_to_loan_created(application)
        loan.write({'state': 'cancelled'})
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.other_product.id,
        })
        self.assertEqual(partner.microfinance_selected_product_id, self.other_product)

    @unittest.skip(
        "TODO(fusion): plus d'état 'refused' explicite depuis la simplification du cycle de "
        "microfinance.loan.application (draft/visite/contre_visite/fait) — même TODO que "
        "_microfinance_product_change_unlocked() dans le modèle. Un dossier simplement "
        "laissé sans suite (draft/visite/contre_visite/fait sans loan_id) reste verrouillé "
        "avec la logique actuelle (fail-safe), contrairement à l'ancien déblocage explicite "
        "sur refus. À réactiver une fois tranché avec Micka si un scénario de refus doit "
        "rouvrir la sélection de produit autrement."
    )
    def test_change_allowed_once_application_refused(self):
        partner = self._new_partner_with_product()
        application = partner.microfinance_current_loan_application_id
        application.action_start_visite()
        application.action_start_contre_visite()
        application.action_mark_fait()
        # Pas d'action de refus équivalente dans le nouveau cycle : cf. TODO ci-dessus.
        partner.with_context(microfinance_context=True).write({
            'microfinance_selected_product_id': self.other_product.id,
        })
        self.assertEqual(partner.microfinance_selected_product_id, self.other_product)
