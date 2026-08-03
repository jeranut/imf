# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo.fields import Date

from odoo.addons.microfinance_loan_management.hooks import _load_activity_reference_data

from .common import MicrofinanceCommon


class TestActivityCategoryModels(MicrofinanceCommon):
    """Catégorie d'activité / Activité (Bloc IV) : deux modèles séparés (une catégorie peut
    avoir plusieurs activités), unicité de code globale sur l'activité (pas relative à la
    catégorie) — cf. décision sur les doublons du jeu de données initial,
    docs_dev/programme_progressif/STATUS.md."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def _create_category(self, code='CATTEST', name='Catégorie test'):
        return self.env['microfinance.loan.application.activity.category'].create({
            'code': code, 'name': name,
        })

    def test_category_code_unique(self):
        self._create_category(code='DUP')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._create_category(code='DUP')

    def test_activity_code_unique_across_categories(self):
        # Unicité globale du code activité : même deux catégories différentes ne peuvent pas
        # partager une activité avec le même code.
        category_a = self._create_category(code='CATA', name='Catégorie A')
        category_b = self._create_category(code='CATB', name='Catégorie B')
        self.env['microfinance.loan.application.activity'].create({
            'code': 'ACT1', 'name': 'Première activité', 'category_id': category_a.id,
        })
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['microfinance.loan.application.activity'].create({
                    'code': 'ACT1', 'name': 'Doublon', 'category_id': category_b.id,
                })

    def test_category_can_have_several_activities(self):
        category = self._create_category()
        self.env['microfinance.loan.application.activity'].create([
            {'code': 'ACT2', 'name': 'Activité 2', 'category_id': category.id},
            {'code': 'ACT3', 'name': 'Activité 3', 'category_id': category.id},
        ])
        self.assertEqual(len(category.activity_ids), 2)


class TestApplicationActivityBlocIV(MicrofinanceCommon):
    """Intégration Bloc IV : activity_id (sélection ou création depuis la fiche),
    activity_sector_id dérivé automatiquement, aucune saisie manuelle de secteur."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_selecting_existing_activity_derives_sector(self):
        category = self.env['microfinance.loan.application.activity.category'].create({
            'code': 'CATSEL', 'name': 'Catégorie sélection',
        })
        activity = self.env['microfinance.loan.application.activity'].create({
            'code': 'ACTSEL', 'name': 'Activité sélection', 'category_id': category.id,
        })
        application = self._create_application()
        application.activity_id = activity
        self.assertEqual(application.activity_sector_id, category)

    def test_creating_new_activity_with_existing_code_is_blocked(self):
        category = self.env['microfinance.loan.application.activity.category'].create({
            'code': 'CATBLOCK', 'name': 'Catégorie blocage',
        })
        self.env['microfinance.loan.application.activity'].create({
            'code': 'ACTEXIST', 'name': 'Activité existante', 'category_id': category.id,
        })
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['microfinance.loan.application.activity'].create({
                    'code': 'ACTEXIST', 'name': 'Nouvelle tentative', 'category_id': category.id,
                })

    def test_creating_new_activity_with_new_code_succeeds_and_is_reusable(self):
        category = self.env['microfinance.loan.application.activity.category'].create({
            'code': 'CATNEW', 'name': 'Catégorie nouvelle',
        })
        application = self._create_application()
        new_activity = self.env['microfinance.loan.application.activity'].create({
            'code': 'ACTNEW', 'name': 'Nouvelle activité', 'category_id': category.id,
        })
        application.activity_id = new_activity
        self.assertEqual(application.activity_sector_id, category)
        # Disponible ensuite dans Configuration > Activités (recherche standard).
        found = self.env['microfinance.loan.application.activity'].search([('code', '=', 'ACTNEW')])
        self.assertEqual(found, new_activity)


class TestActivityReferenceDataLoading(MicrofinanceCommon):
    """Chargement du référentiel initial (post_init_hook) : cf. hooks._load_activity_reference_data.
    Le hook post_init_hook ne s'exécute qu'à l'installation initiale du module (new_install,
    cf. odoo/modules/loading.py) — ce test appelle directement la fonction de chargement pour
    vérifier son comportement indépendamment de l'historique d'installation de la base de
    test, y compris son idempotence (un rappel ne doit rien dupliquer)."""

    def test_loading_counts_and_duplicate_handling(self):
        Category = self.env['microfinance.loan.application.activity.category']
        Activity = self.env['microfinance.loan.application.activity']
        _load_activity_reference_data(self.env)
        count_categories_first = Category.search_count([])
        count_activities_first = Activity.search_count([])
        self.assertGreaterEqual(count_categories_first, 37)
        self.assertGreaterEqual(count_activities_first, 50)

        # Idempotent : un second appel ne doit rien dupliquer.
        _load_activity_reference_data(self.env)
        self.assertEqual(Category.search_count([]), count_categories_first)
        self.assertEqual(Activity.search_count([]), count_activities_first)

        # Décision Option A sur les 2 codes en double : la première occurrence dans l'ordre du
        # tableau source est conservée.
        code_27 = Activity.search([('code', '=', '27')])
        self.assertEqual(len(code_27), 1)
        self.assertEqual(code_27.category_id.code, 'S9529')
        code_30 = Activity.search([('code', '=', '30')])
        self.assertEqual(len(code_30), 1)
        self.assertEqual(code_30.category_id.code, 'Q8892')

        # Q8892 garde ses 4 activités restantes après dédoublonnage.
        q8892 = self.env['microfinance.loan.application.activity.category'].search([('code', '=', 'Q8892')])
        self.assertEqual(
            set(q8892.activity_ids.mapped('name')),
            {'Lavanderie', 'Photos', 'Tailleur', 'Autres services'},
        )


class TestApplicationActivityDuration(MicrofinanceCommon):
    """activity_duration : compute non stocké (recalculé à chaque affichage), format "X ans et
    Y mois" avec gestion des cas limites — cf. repagination/ajustements Bloc IV, 2026-07-19."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_duration_empty_when_no_start_date(self):
        application = self._create_application()
        self.assertFalse(application.activity_duration)

    def test_duration_today_is_less_than_a_month(self):
        application = self._create_application(activity_start_date=Date.context_today(self.env['microfinance.loan.application']))
        self.assertEqual(application.activity_duration, "Moins d'un mois")

    def test_duration_six_months(self):
        today = Date.context_today(self.env['microfinance.loan.application'])
        application = self._create_application(activity_start_date=today - relativedelta(months=6))
        self.assertEqual(application.activity_duration, '6 mois')

    def test_duration_exactly_one_year(self):
        today = Date.context_today(self.env['microfinance.loan.application'])
        application = self._create_application(activity_start_date=today - relativedelta(years=1))
        self.assertEqual(application.activity_duration, '1 an')

    def test_duration_five_years_and_seven_months(self):
        today = Date.context_today(self.env['microfinance.loan.application'])
        application = self._create_application(
            activity_start_date=today - relativedelta(years=5, months=7))
        self.assertEqual(application.activity_duration, '5 ans et 7 mois')


class TestSaleLocationEnclosed(MicrofinanceCommon):
    """sale_location_enclosed : Selection (déjà le cas avant ce lot, pas un Boolean à migrer),
    défaut 'open' (Ouvert), affiché en radio Ouvert/Fermé."""

    def _create_application(self, **kwargs):
        vals = {'partner_id': self.partner.id, 'loan_product_id': self.product.id}
        vals.update(kwargs)
        return self.env['microfinance.loan.application'].create(vals)

    def test_default_is_open_for_new_application(self):
        application = self._create_application()
        self.assertEqual(application.sale_location_enclosed, 'open')

    def test_can_be_set_to_closed(self):
        application = self._create_application(sale_location_enclosed='closed')
        self.assertEqual(application.sale_location_enclosed, 'closed')
