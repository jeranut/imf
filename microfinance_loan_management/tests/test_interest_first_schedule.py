# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestInterestFirstSchedule(MicrofinanceCommon):
    """Politique CEFOR "intérêt d'abord" (interest-first) sur la génération d'échéancier
    (action_generate_schedule, méthode flat uniquement - cf. commentaire de la méthode pour la
    méthode dégressive, hors périmètre) : chaque tranche cible un montant total identique
    (total_dû / nb_tranches), l'intérêt total du crédit est consommé en priorité sur les
    premières tranches, le principal ne comble que le reste."""

    def test_is01913_reference_case_interest_exhausted_over_three_installments(self):
        # Cas réel de référence (reçu imprimé IS/01913) : 700 000 Ar, 36%/an, 11 mensualités.
        # Intérêt total = 700 000 x 0,36 x 11/12 = 231 000 (exact, sans arrondi).
        #
        # Arrondi de la cible par tranche (installment_rounding_unit, défaut produit = 1000 Ar,
        # champ de config - pas une valeur codée en dur ici) au plus proche multiple de 1000 :
        # cible brute 931000/11 = 84 636,36 -> arrondie à 85 000, exactement comme sur le document
        # de référence. La dernière tranche absorbe le reliquat exact (81 000, différent de la
        # cible arrondie) - reliquat d'arrondi, pas une erreur.
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        # Le produit de test générique désactive l'arrondi par défaut (cf. common.py) : activé
        # explicitement ici, ce test étant dédié à sa vérification.
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=700000.0, term=11)
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 11)

        total_interest = 700000.0 * 0.36 * (11 / 12.0)
        self.assertAlmostEqual(total_interest, 231000.0, places=2)

        # Tranches 1-2 : 100% intérêt (85 000 chacune), tel qu'imprimé sur IS/01913.
        for inst in installments[:2]:
            self.assertAlmostEqual(inst.interest_amount, 85000.0, places=2)
            self.assertAlmostEqual(inst.principal_amount, 0.0, places=2)

        # Tranche 3 : bascule - 61 000 d'intérêt (reliquat du pool : 231000 - 2x85000), 24 000 de
        # principal (85000 - 61000).
        third = installments[2]
        self.assertAlmostEqual(third.interest_amount, 61000.0, places=2)
        self.assertAlmostEqual(third.principal_amount, 24000.0, places=2)

        # Tranches 4-10 : 100% principal (85 000 chacune), plus aucun intérêt (pool épuisé).
        for inst in installments[3:10]:
            self.assertAlmostEqual(inst.interest_amount, 0.0, places=2)
            self.assertAlmostEqual(inst.principal_amount, 85000.0, places=2)

        # Dernière tranche : reliquat exact (81 000), pas la cible arrondie (85 000).
        last = installments[10]
        self.assertAlmostEqual(last.interest_amount, 0.0, places=2)
        self.assertAlmostEqual(last.principal_amount, 81000.0, places=2)

        # Invariants globaux : les totaux somment exactement au capital et à l'intérêt total,
        # malgré l'arrondi de la cible intermédiaire (absorbé par la dernière tranche).
        self.assertAlmostEqual(sum(installments.mapped('principal_amount')), 700000.0, places=2)
        self.assertAlmostEqual(sum(installments.mapped('interest_amount')), total_interest, places=2)

    def test_small_credit_rounded_target_reaches_zero_without_special_case(self):
        # Aucune règle spéciale pour les petits crédits (Décision de vérification post-Lot 1) :
        # l'arrondi à 1000 Ar s'applique même si la cible arrondie tombe à 0 - pas de seuil
        # minimal qui désactiverait l'arrondi ou basculerait sur une unité plus fine. Ici la
        # cible brute (208/4=52) arrondit à 0 : les 3 premières tranches sont donc entièrement à
        # 0 (principal ET intérêt, plafonnés par une cible nulle), la dernière tranche absorbe la
        # totalité du capital et de l'intérêt en une seule fois - résultat attendu de la formule
        # appliquée littéralement, pas un bug.
        # Mode 'nearest' explicite (Lot 1 : 'ceiling' est désormais le défaut, qui n'arrondirait
        # pas cette cible à 0 - ce test porte spécifiquement sur le comportement 'nearest' à
        # cette borne, conservé comme option, cf. test_nearest_rounding_mode_reproduces_old_behavior).
        self.product.installment_rounding_mode = 'nearest'
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=200.0, term=4)  # taux produit par défaut 12%/an
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 4)

        total_interest = 200.0 * 0.12 * (1 / 12.0) * 4
        self.assertAlmostEqual(total_interest, 8.0, places=2)
        raw_target = (200.0 + total_interest) / 4
        self.assertLess(raw_target, 500.0)  # confirme que la cible brute arrondit bien à 0

        for inst in installments[:3]:
            self.assertAlmostEqual(inst.principal_amount, 0.0, places=2)
            self.assertAlmostEqual(inst.interest_amount, 0.0, places=2)

        last = installments[3]
        self.assertAlmostEqual(last.principal_amount, 200.0, places=2)
        self.assertAlmostEqual(last.interest_amount, total_interest, places=2)

        self.assertAlmostEqual(sum(installments.mapped('principal_amount')), 200.0, places=2)
        self.assertAlmostEqual(sum(installments.mapped('interest_amount')), total_interest, places=2)

    def test_short_loan_interest_fits_entirely_in_first_installment(self):
        # Cas simple sans débordement : l'intérêt total tient dans la cible de la 1ère tranche,
        # aucune tranche suivante n'a donc d'intérêt (pas de bascule sur plusieurs tranches comme
        # dans le cas IS/01913 ci-dessus) - vérifie qu'on ne casse pas ce cas plus simple.
        # Arrondi désactivé : ce test porte sur la forme interest-first elle-même, pas sur
        # l'arrondi (couvert par les deux tests dédiés ci-dessus).
        self.product.installment_rounding_unit = 0
        loan = self._create_loan(loan_amount=1000.0, term=2)  # taux produit par défaut 12%/an
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 2)

        total_interest = 1000.0 * 0.12 * (1 / 12.0) * 2
        self.assertAlmostEqual(total_interest, 20.0, places=2)
        installment_target = (1000.0 + total_interest) / 2  # 510.0

        first, last = installments[0], installments[1]
        self.assertAlmostEqual(first.interest_amount, total_interest, places=2)
        self.assertAlmostEqual(first.principal_amount, installment_target - total_interest, places=2)
        self.assertAlmostEqual(last.interest_amount, 0.0, places=2)
        self.assertAlmostEqual(last.principal_amount, 1000.0 - first.principal_amount, places=2)

    def test_distributed_rounding_mode_spreads_remainder_over_last_installments(self):
        """Reprend le cas IS/000289 (500.000 Ar, taux 36%, 24 échéances hebdo, arrondi 1000).
        En mode 'distributed', la dernière tranche ne doit plus concentrer tout le reliquat
        (31.076,92 en mode 'last_installment') : l'écart doit être réparti sur plusieurs
        tranches en incréments de 1000, la dernière tranche gardant seulement la fraction
        résiduelle sous le millier."""
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=500000.0, term=24)

        loan.action_generate_schedule(rounding_mode='distributed')
        installments = loan.installment_ids.sorted('sequence')
        total_amounts = [inst.principal_amount + inst.interest_amount for inst in installments]

        # Le total exact ne change pas selon le mode.
        total_due = 500000.0 + sum(installments.mapped('interest_amount'))
        self.assertAlmostEqual(sum(total_amounts), total_due, places=2)

        # La dernière tranche ne doit plus être seule à porter tout l'écart : son montant doit
        # être nettement plus proche de la cible moyenne qu'en mode absorption.
        last_amount = total_amounts[-1]
        average = total_due / 24
        self.assertLess(abs(last_amount - average), 1000.0)

        # Au moins une autre tranche que la dernière doit différer de la cible plancher, preuve
        # que la répartition a bien touché plusieurs tranches et pas seulement la dernière.
        distinct_amounts = set(round(a, 2) for a in total_amounts[:-1])
        self.assertGreater(len(distinct_amounts), 1)

    def test_last_installment_reliquat_mode_still_default_with_new_ceiling_rounding(self):
        """Sans argument explicite, action_generate_schedule() garde 'last_installment' comme
        mode de répartition du RELIQUAT par défaut (non-régression pour tous les appels
        existants du module) - mais le mode d'ARRONDI par défaut est désormais 'ceiling'
        (Lot 1, correction du bug confirmé sur l'échéancier papier IS/000289) : la cible passe
        de 24 000 à 25 000 Ar, le reliquat de 31 076,92 à 8 076,92 Ar. Cf.
        test_nearest_rounding_mode_reproduces_old_behavior_explicitly pour la non-régression sur
        l'ancien comportement, toujours disponible en option explicite."""
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id
        self.product.installment_rounding_unit = 1000.0
        loan = self._create_loan(loan_amount=500000.0, term=24)
        loan.action_generate_schedule()  # pas de rounding_mode -> défaut 'last_installment'
        installments = loan.installment_ids.sorted('sequence')
        last_total = installments[-1].principal_amount + installments[-1].interest_amount
        others_total = installments[0].principal_amount + installments[0].interest_amount
        self.assertGreater(abs(last_total - others_total), 5000.0)
        self.assertAlmostEqual(others_total, 25000.0, places=2)
        self.assertAlmostEqual(last_total, 8076.92, places=2)
        # Somme exacte inchangée quel que soit le mode d'arrondi (23 tranches + reliquat).
        self.assertAlmostEqual(23 * others_total + last_total, 583076.92, places=2)

    def test_nearest_rounding_mode_reproduces_old_behavior_explicitly(self):
        """L'ancien comportement (arrondi au plus proche) reste disponible en configurant
        explicitement installment_rounding_mode='nearest' sur le produit - ce n'est plus le
        défaut, mais l'option doit toujours produire exactement l'ancien résultat (24 000 /
        31 076,92), pour garder une couverture sur les deux modes plutôt que de la supprimer."""
        self.product.interest_rate = 36.0
        self.product.max_amount = 1000000.0
        self.product.repayment_frequency_id = self.env.ref(
            'microfinance_loan_management.repayment_frequency_weekly'
        ).id
        self.product.installment_rounding_unit = 1000.0
        self.product.installment_rounding_mode = 'nearest'
        loan = self._create_loan(loan_amount=500000.0, term=24)
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        last_total = installments[-1].principal_amount + installments[-1].interest_amount
        others_total = installments[0].principal_amount + installments[0].interest_amount
        self.assertAlmostEqual(others_total, 24000.0, places=2)
        self.assertAlmostEqual(last_total, 31076.92, places=2)


class TestInstallmentTargetRoundingMode(MicrofinanceCommon):
    """Lot 1 (correction_diviseur_echeancier) : le mode d'arrondi de la cible d'échéance
    (installment_rounding_mode sur le produit) est désormais 'ceiling' par défaut - comportement
    LPF de référence, prouvé sans exception sur les échéanciers papier/export 1.XLS et IS/000289
    (cf. docs_dev/correction_diviseur_echeancier/) - remplaçant l'ancien défaut 'nearest'. Tests
    directs sur _compute_installment_targets (pas de génération complète d'échéancier) pour
    isoler précisément l'arithmétique de chaque cas de preuve."""

    def test_target_1xls_case_ceiling_and_nearest_agree_non_discriminant(self):
        # 1.XLS / IS/01913 : total dû 931 000 Ar, n=11, unit=1000 -> target 85 000. Cas NON
        # discriminant (931000/11=84636,36 : ceiling ET nearest arrondissent tous les deux à
        # 85 000) - sert de non-régression sur le cas historique, pas de preuve à lui seul.
        loan = self._create_loan(term=11)
        self.product.installment_rounding_unit = 1000.0
        targets = loan._compute_installment_targets(931000.0, 1000.0, 'last_installment')
        self.assertEqual(len(targets), 10)
        for target in targets:
            self.assertAlmostEqual(target, 85000.0, places=2)

    def test_target_is000289_case_ceiling_matches_lpf_paper(self):
        # IS/000289 (papier) : total dû 583 077 Ar, n=24, unit=1000 -> target attendu 25 000
        # (discriminant : 583077/24=24294,875 - nearest donnerait 24 000, l'ancien bug).
        loan = self._create_loan(term=24)
        self.product.installment_rounding_unit = 1000.0
        targets = loan._compute_installment_targets(583077.0, 1000.0, 'last_installment')
        self.assertEqual(len(targets), 23)
        for target in targets:
            self.assertAlmostEqual(target, 25000.0, places=2)
        # Reconstitution exacte : 23 tranches à 25 000 + reliquat = total dû à l'Ariary près.
        reliquat = 583077.0 - sum(targets)
        self.assertAlmostEqual(reliquat, 8077.0, places=2)
        self.assertAlmostEqual(sum(targets) + reliquat, 583077.0, places=2)

    def test_target_exact_division_non_discriminant(self):
        # 2.XLS : division exacte (520 000 / 10 = 52 000 pile) - aucun reste à arrondir, ceiling
        # et nearest s'accordent nécessairement. Non discriminant, couvre le cas trivial.
        loan = self._create_loan(term=10)
        self.product.installment_rounding_unit = 1000.0
        targets = loan._compute_installment_targets(520000.0, 1000.0, 'last_installment')
        self.assertEqual(len(targets), 9)
        for target in targets:
            self.assertAlmostEqual(target, 52000.0, places=2)

    def test_target_single_installment_list_is_empty_never_exceeds_total_due(self):
        # n=1 : pas de tranche de reliquat pour absorber un dépassement d'arrondi (ceiling peut
        # dépasser total_due) - la liste des cibles intermédiaires est vide par construction
        # (n-1=0) et jamais consultée par _build_installment_commands pour une échéance unique.
        loan = self._create_loan(term=1)
        self.product.installment_rounding_unit = 1000.0
        targets = loan._compute_installment_targets(12345.0, 1000.0, 'last_installment')
        self.assertEqual(targets, [])

    def test_single_installment_generated_schedule_uses_exact_total_due_not_rounded_up(self):
        # Bout en bout : term=1, montant volontairement non multiple de l'unité d'arrondi (12 345
        # Ar, taux 0% pour un total dû exact et maîtrisé) - l'unique échéance générée doit valoir
        # exactement 12 345 Ar, jamais 13 000 (ce que donnerait un ceiling naïf sans ce garde-fou).
        self.product.installment_rounding_unit = 1000.0
        self.product.interest_rate = 0.0
        loan = self._create_loan(loan_amount=12345.0, term=1)
        loan.action_generate_schedule()
        self.assertEqual(len(loan.installment_ids), 1)
        installment = loan.installment_ids[0]
        self.assertAlmostEqual(installment.principal_amount + installment.interest_amount, 12345.0, places=2)

    def test_onchange_single_installment_preview_uses_exact_total_due_not_rounded_up(self):
        # Même garde-fou côté deuxième site de calcul (_onchange_loan_amount_recompute_installment,
        # champ "Échéance" affiché avant génération) : l'aperçu ne doit pas non plus dépasser
        # total_due pour une échéance unique.
        self.product.installment_rounding_unit = 1000.0
        self.product.interest_rate = 0.0
        loan = self._create_loan(loan_amount=12345.0, term=1)
        loan._onchange_loan_amount_recompute_installment()
        self.assertAlmostEqual(loan.installment_amount, 12345.0, places=2)
