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
