# -*- coding: utf-8 -*-
from odoo.tests import Form

from .common import MicrofinanceCommon


class TestInstallmentSchedulePersistence(MicrofinanceCommon):
    """Non-régression Lot 1 : `installment_ids` est marqué readonly="1" en vue - un onchange qui
    le modifie n'est jamais inclus dans la sauvegarde du formulaire (comportement standard du
    client web Odoo, cf. odoo/tests/form.py "does not save readonly fields"). Avant correctif,
    retoucher `term`/`loan_amount`/etc. sur un crédit dont l'échéancier avait déjà été généré une
    première fois laissait l'échéancier détaillé silencieusement obsolète en base, alors même que
    l'aperçu affiché avant enregistrement était correct - reproduit et documenté sur les dossiers
    réels IS/000289 et IS/001076, cf. docs_dev/echeancier_obsolete_readonly/AUDIT.md. Ces tests
    utilisent Form(), qui rejoue exactement la cascade onchange + sauvegarde du client web - même
    méthode que l'audit."""

    def setUp(self):
        super().setUp()
        self.env['microfinance.fond.credit'].sudo().search([]).write({'active': False})
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.installment_rounding_unit = 1000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id

    def test_term_change_after_generation_persists_to_installment_ids(self):
        """Reproduction directe du symptôme IS/001076 : échéancier déjà généré une première fois
        (24 lignes), `term` retouché puis ramené à sa valeur d'origine (comme un résidu d'un test
        antérieur avec un autre `term`) - l'échéancier réel en base doit refléter le `term`
        actuel après sauvegarde, pas rester sur son ancien contenu."""
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
        loan = f.save()
        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 24)

        # Simule le résidu IS/001076 : un échéancier à 27 lignes, généré à un `term` différent.
        with Form(loan) as f:
            f.term = 27
        f.save()
        self.assertEqual(len(loan.installment_ids), 27)

        # Le symptôme : revenir à term=24 doit désormais persister un échéancier à 24 lignes,
        # pas laisser les 27 lignes précédentes en base (bug avant correctif : write() ne
        # régénérait rien, l'aperçu à 24 lignes du formulaire n'atteignait jamais la table).
        with Form(loan) as f:
            f.term = 24
        f.save()
        self.assertEqual(len(loan.installment_ids), 24)
        self.assertAlmostEqual(sum(loan.installment_ids.mapped('principal_amount')), 500000.0, places=2)

    def test_loan_amount_change_after_generation_persists(self):
        """Même bug, déclenché par `loan_amount` plutôt que `term` : la somme des principaux de
        l'échéancier réel doit suivre le nouveau `loan_amount` après sauvegarde."""
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
        loan = f.save()
        loan.action_generate_schedule()
        self.assertAlmostEqual(sum(loan.installment_ids.mapped('principal_amount')), 500000.0, places=2)

        with Form(loan) as f:
            f.loan_amount = 800000.0
        f.save()
        self.assertAlmostEqual(sum(loan.installment_ids.mapped('principal_amount')), 800000.0, places=2)

    def test_write_does_not_regenerate_before_first_generation(self):
        """Ne force pas une première génération hors du wizard "Générer échéancier" (qui laisse
        le choix du rounding_mode) : tant qu'installment_ids est vide, une écriture sur
        loan_amount/term ne doit pas le peupler toute seule."""
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
        loan = f.save()
        self.assertFalse(loan.installment_ids)

        with Form(loan) as f:
            f.loan_amount = 600000.0
        f.save()
        self.assertFalse(loan.installment_ids)

    def test_write_does_not_regenerate_once_active(self):
        """Ne doit pas écraser un échéancier réel (avec paiements) une fois le crédit décaissé -
        write() ne régénère que dans _EDITABLE_SCHEDULE_STATES."""
        with Form(self.env['microfinance.loan']) as f:
            f.partner_id = self.partner
            f.product_id = self.product
            f.loan_amount = 500000.0
            f.term = 24
        loan = f.save()
        loan.action_generate_schedule()
        installment_ids_before = loan.installment_ids.ids
        loan.write({'state': 'active'})
        # Écriture directe (hors Form, hors onchange) d'un champ déclencheur de
        # _SCHEDULE_TRIGGER_FIELDS non verrouillé (repayment_frequency_id - installment_amount
        # est désormais bloqué en amont par le verrou du Lot "verrouillage_calcul_credit", cf.
        # test_locked_dossier_fields.py) : ne doit rien régénérer une fois le crédit actif,
        # l'échéancier réel (paiements potentiels) doit rester intact.
        loan.write({'repayment_frequency_id': loan.repayment_frequency_id.id})
        self.assertEqual(loan.installment_ids.ids, installment_ids_before)
