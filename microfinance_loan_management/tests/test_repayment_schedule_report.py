# -*- coding: utf-8 -*-
from .common import MicrofinanceCommon


class TestRepaymentScheduleReport(MicrofinanceCommon):
    """Impression du calendrier de remboursement (bouton dédié microfinance.loan.
    action_print_repayment_schedule) : le PDF ne doit jamais être proposé au téléchargement
    direct, uniquement posté en pièce jointe dans le chatter du crédit."""

    def test_repayment_schedule_html_matches_installment_amounts(self):
        # Cas déterministe (repris de test_short_loan_interest_fits_entirely_in_first_installment) :
        # 1000 Ar, 12%/an, 2 mensualités, arrondi désactivé -> intérêt total = 20.0, réparti
        # interest-first (1ère tranche 20.0 intérêt + 490.0 principal, 2e tranche 510.0 principal).
        loan = self._create_loan(loan_amount=1000.0, term=2)
        loan.action_generate_schedule()
        installments = loan.installment_ids.sorted('sequence')
        self.assertEqual(len(installments), 2)

        report = self.env.ref('microfinance_loan_management.action_report_microfinance_loan_repayment_schedule')
        html = report._render_qweb_html(report.report_name, loan.ids)[0].decode('utf-8')

        # Les montants de chaque tranche réelle doivent apparaître exactement dans le rendu.
        # Widget monétaire du rapport : décimale au point tant qu'aucune langue localisée
        # (ex. fr_FR, qui donnerait une virgule) n'est installée/active sur la base — ce test ne
        # doit pas dépendre d'une langue précise étant installée, aucun autre test de la suite ne
        # fait cette hypothèse.
        def _fmt(value):
            return '%.2f' % value

        for inst in installments:
            self.assertIn(_fmt(inst.principal_amount), html)
            self.assertIn(_fmt(inst.interest_amount), html)
            self.assertIn(_fmt(inst.total_amount), html)

        self.assertIn(loan.partner_id.name, html)
        self.assertIn(loan.name, html)

    def test_print_posts_attachment_in_chatter_without_download_action(self):
        # action_print_repayment_schedule() ne requiert pas un crédit décaissé (juste un
        # échéancier existant) : pas besoin de _activate_loan() (workflow complet jusqu'au
        # décaissement, hors sujet ici et sensible à la configuration des fonds bailleurs déjà
        # en place dans la base utilisée pour les tests).
        loan = self._create_loan(loan_amount=900.0, term=3)
        loan.action_generate_schedule()
        message_count_before = len(loan.message_ids)

        result = loan.action_print_repayment_schedule()

        # Aucune action de type rapport/téléchargement : uniquement une notification légère.
        self.assertEqual(result.get('type'), 'ir.actions.client')
        self.assertEqual(result.get('tag'), 'display_notification')

        self.assertEqual(len(loan.message_ids), message_count_before + 1)
        new_message = loan.message_ids.sorted('id', reverse=True)[0]
        self.assertIn('Calendrier de remboursement', new_message.body)
        self.assertEqual(len(new_message.attachment_ids), 1)

        attachment = new_message.attachment_ids[0]
        self.assertEqual(attachment.res_model, 'microfinance.loan')
        self.assertEqual(attachment.res_id, loan.id)
        self.assertEqual(attachment.company_id, loan.company_id)
        self.assertEqual(attachment.mimetype, 'application/pdf')
        self.assertTrue(attachment.datas)

    def test_print_with_guarantor_and_guarantee_renders_both_blocks(self):
        guarantor = self.env['res.partner'].create({
            'name': 'Caution Test', 'street': '5 Rue du Garant', 'city': 'Fianarantsoa',
        })
        loan = self._create_loan(loan_amount=700.0, term=2)
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'guarantor',
            'description': 'Caution personnelle du frère',
            'estimated_value': 500.0,
            'guarantor_partner_id': guarantor.id,
        })
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'land',
            'description': 'Terrain rizicole 2ha',
            'estimated_value': 2000000.0,
        })
        loan.action_generate_schedule()

        report = self.env.ref('microfinance_loan_management.action_report_microfinance_loan_repayment_schedule')
        html = report._render_qweb_html(report.report_name, loan.ids)[0].decode('utf-8')
        self.assertIn(guarantor.name, html)
        self.assertIn('Fianarantsoa', html)
        self.assertIn('Caution personnelle du frère', html)
        self.assertIn('Terrain rizicole 2ha', html)

    def test_print_without_guarantees_does_not_crash(self):
        loan = self._create_loan(loan_amount=500.0, term=3)
        loan.action_generate_schedule()
        self.assertFalse(loan.guarantee_ids)
        # Ne doit lever aucune exception malgré l'absence de garant/garantie sur le crédit.
        result = loan.action_print_repayment_schedule()
        self.assertEqual(result.get('tag'), 'display_notification')

    def _create_company_with_product(self, label, city):
        # Deux sociétés entièrement maîtrisées par le test (nom du partenaire de la société
        # synchronisé à la création, comptes/produit dédiés) plutôt que de réutiliser
        # self.env.company : évite de dépendre des données déjà présentes dans la base
        # (le partenaire de la société "par défaut" d'une base réelle peut avoir un nom non
        # synchronisé avec res.company.name - non pertinent pour ce que ce test vérifie).
        company = self.env['res.company'].create({
            'name': 'Agence %s calendrier (test)' % label,
            'street': '12 Rue de l\'Agence %s' % label,
            'city': city,
            'agency_code': 'RS%s' % label,
        })
        principal_account = self.env['account.account'].create({
            'name': 'Prêts clients test %s' % label, 'code': 'TPRET%s' % label,
            'account_type': 'asset_current', 'company_id': company.id,
        })
        principal_account_groupe = self.env['account.account'].create({
            'name': 'Prêts clients groupe test %s' % label, 'code': 'TPRETG%s' % label,
            'account_type': 'asset_current', 'company_id': company.id,
        })
        interest_account = self.env['account.account'].create({
            'name': 'Produits intérêts test %s' % label, 'code': 'TINT%s' % label,
            'account_type': 'income', 'company_id': company.id,
        })
        interest_account_groupe = self.env['account.account'].create({
            'name': 'Produits intérêts groupe test %s' % label, 'code': 'TINTG%s' % label,
            'account_type': 'income', 'company_id': company.id,
        })
        product = self.env['microfinance.loan.product'].create({
            'name': 'Produit Test %s' % label, 'code': 'PTEST%s' % label,
            'min_amount': 100.0, 'max_amount': 100000.0,
            'min_term': 1, 'max_term': 36,
            'interest_rate': 12.0, 'interest_method': 'flat',
            'installment_rounding_unit': 0,
            'repayment_frequency_mode': 'fixed',
            'repayment_frequency_id': self.env.ref('microfinance_loan_management.repayment_frequency_monthly').id,
            'account_principal_individuel_id': principal_account.id,
            'account_principal_groupe_id': principal_account_groupe.id,
            'account_interets_recus_individuel_id': interest_account.id,
            'account_interets_recus_groupe_id': interest_account_groupe.id,
            'company_id': company.id,
        })
        partner = self.env['res.partner'].create({'name': 'Client Agence %s' % label})
        loan = self.env['microfinance.loan'].with_context(microfinance_loan_creation_allowed=True).create({
            'partner_id': partner.id,
            'product_id': product.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'loan_amount': 1000.0,
            'term': 2,
        })
        loan.action_generate_schedule()
        return company, loan

    def test_repayment_schedule_header_uses_loan_company_not_hardcoded(self):
        company_a, loan_a = self._create_company_with_product('A', 'Antananarivo')
        company_b, loan_b = self._create_company_with_product('B', 'Antsirabe')

        report = self.env.ref('microfinance_loan_management.action_report_microfinance_loan_repayment_schedule')
        html_a = report._render_qweb_html(report.report_name, loan_a.ids)[0].decode('utf-8')
        html_b = report._render_qweb_html(report.report_name, loan_b.ids)[0].decode('utf-8')

        self.assertIn(company_a.name, html_a)
        self.assertIn('Antananarivo', html_a)
        self.assertNotIn('Antsirabe', html_a)

        self.assertIn(company_b.name, html_b)
        self.assertIn('Antsirabe', html_b)
        self.assertNotIn('Antananarivo', html_b)
