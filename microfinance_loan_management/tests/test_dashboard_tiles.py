# -*- coding: utf-8 -*-
from unittest.mock import patch

from .common import MicrofinanceCommon, MicrofinanceNoFundMixin


class TestDashboardTiles(MicrofinanceNoFundMixin, MicrofinanceCommon):
    """Règle anti-ambiguïté (docs_dev/dashboard_tuiles/) : pour chaque tuile, valeur affichée ==
    lignes (ou somme) de la liste ouverte par son lien, qui utilise le domaine renvoyé tel quel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Agence B tuiles (test)', 'agency_code': 'TUB'})
        cls.env.user.company_ids = [(4, cls.company_b.id)]
        mod = 'microfinance_loan_management.'
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent tuiles', 'login': 'agent_tuiles_test',
            'company_id': cls.company_a.id, 'company_ids': [(6, 0, cls.company_a.ids)],
            'groups_id': [(6, 0, (cls.env.ref('base.group_user') | cls.env.ref(mod + 'group_microfinance_user')).ids)],
        })
        cls.loans_a = {
            'actif_decaisse': cls._loan(cls.company_a, 'active', disbursed=True, officer=cls.agent),
            'actif_attente': cls._loan(cls.company_a, 'active', disbursed=False),
            'defaut': cls._loan(cls.company_a, 'defaulted', disbursed=True),
            'brouillon': cls._loan(cls.company_a, 'draft', disbursed=False),
            'solde': cls._loan(cls.company_a, 'closed', disbursed=True),
        }
        # overdue_amount est calculé stocké (recalculé à toute écriture ORM) : fixé en SQL pour le jeu.
        cls.env.flush_all()
        cls.env.cr.execute("UPDATE microfinance_loan SET overdue_amount = 150 WHERE id = %s",
                           [cls.loans_a['actif_decaisse'].id])
        cls.loans_b = cls._loan(cls.company_b, 'active', disbursed=True) | cls._loan(cls.company_b, 'defaulted', disbursed=True)
        cls.env.invalidate_all()

    @classmethod
    def _loan(cls, company, state, disbursed, officer=None):
        loan = cls.env['microfinance.loan'].create({
            'partner_id': cls.partner.id, 'product_id': cls.product.id, 'loan_amount': 1000.0,
            'term': 6, 'company_id': company.id, 'officer_id': (officer or cls.env.user).id,
        })
        loan.sudo().write({
            'state': state, 'disbursement_date': '2026-09-01' if disbursed else False,
        })
        return loan

    def _tiles(self, env=None, companies=None):
        Loan = (env or self.env)['microfinance.loan']
        if companies:
            Loan = Loan.with_context(allowed_company_ids=companies.ids)
        return {tile['key']: tile for tile in Loan.get_dashboard_data()['tiles']}

    def _assert_tile_matches_list(self, tile, env=None):
        records = (env or self.env)[tile['model']].search(tile['domain'])
        field_name = {
            'granted_amount': 'loan_amount', 'outstanding_amount': 'balance_total',
            'overdue_amount': 'overdue_amount', 'savings_outstanding_total': 'balance',
        }.get(tile['key'])
        expected = sum(records.mapped(field_name)) if field_name else len(records)
        self.assertAlmostEqual(tile['value'], expected, places=2, msg=tile['key'])
        return records

    def test_chaque_tuile_cliquable_egale_sa_liste(self):
        tiles = self._tiles()
        clickable = [tile for tile in tiles.values() if tile['model'] and tile['domain']]
        self.assertTrue(clickable)
        for tile in clickable:
            self._assert_tile_matches_list(tile)

    def test_definitions_et_repartition_des_credits_actifs(self):
        tiles = self._tiles()
        active = self.env['microfinance.loan'].search(tiles['active_loan_count']['domain'])
        pending = self.env['microfinance.loan'].search(tiles['pending_disbursement_count']['domain'])
        defaulted = self.env['microfinance.loan'].search(tiles['defaulted_loan_count']['domain'])
        self.assertIn(self.loans_a['actif_decaisse'], active)
        self.assertIn(self.loans_a['actif_attente'], active)
        self.assertIn(self.loans_a['actif_attente'], pending)
        self.assertNotIn(self.loans_a['actif_decaisse'], pending)
        self.assertNotIn(self.loans_a['defaut'], active, "Un crédit en défaut n'est jamais compté dans les actifs.")
        self.assertIn(self.loans_a['defaut'], defaulted)
        self.assertEqual(len(active.filtered('disbursement_date')) + len(pending), len(active))
        for loan in (self.loans_a['brouillon'], self.loans_a['solde']):
            self.assertNotIn(loan, active | pending | defaulted)
        outstanding = self.env['microfinance.loan'].search(tiles['outstanding_amount']['domain'])
        self.assertNotIn(self.loans_a['actif_attente'], outstanding, "Encours : crédits décaissés seulement.")
        self.assertIn(self.loans_a['defaut'], outstanding)
        overdue = self.env['microfinance.loan'].search(tiles['overdue_amount']['domain'])
        self.assertIn(self.loans_a['actif_decaisse'], overdue)
        self.assertEqual(tiles['overdue_amount']['model'], 'microfinance.loan')

    def test_societe_b_invisible_depuis_a_meme_si_cochee(self):
        tiles = self._tiles(companies=self.company_a | self.company_b)
        for tile in tiles.values():
            if tile['model'] == 'microfinance.loan':
                records = self._assert_tile_matches_list(tile)
                self.assertFalse(records & self.loans_b, tile['key'])
                self.assertIn(('company_id', '=', self.company_a.id), [tuple(t) for t in tile['domain']])

    def test_taux_de_defaut_meme_base_que_le_par(self):
        tiles = self._tiles()
        Loan = self.env['microfinance.loan']
        par_base = Loan.search([
            ('company_id', '=', self.company_a.id), ('state', 'in', ('active', 'defaulted')),
            ('disbursement_date', '!=', False),
        ])
        outstanding = sum(par_base.mapped('balance_total'))
        defaulted = sum(par_base.filtered(lambda loan: loan.state == 'defaulted').mapped('balance_total'))
        self.assertAlmostEqual(tiles['outstanding_amount']['value'], outstanding, places=2)
        self.assertAlmostEqual(tiles['default_rate']['value'], defaulted / outstanding * 100.0, places=4)
        self.assertFalse(tiles['default_rate']['domain'], "Le taux n'a pas de lien.")
        self.assertIn('même base que le PAR', tiles['default_rate']['tooltip'])

    def test_agent_ses_tuiles_egalent_ses_listes(self):
        agent_env = self.env(user=self.agent, context={'allowed_company_ids': self.company_a.ids})
        tiles = self._tiles(env=agent_env)
        self.assertEqual(tiles['active_loan_count']['value'], 1, "L'agent ne voit que ses propres crédits.")
        for tile in tiles.values():
            if tile['model'] and tile['domain']:
                self._assert_tile_matches_list(tile, env=agent_env)
        self.assertNotIn('active_savings_account_count', tiles)
        self.assertNotIn('savings_outstanding_total', tiles)

    def test_tuile_fonds_compteur_egal_liste(self):
        tile = self._tiles()['fund_count']
        funds, allocated = self.env['microfinance.fond.credit']._get_agency_accessible_funds(self.company_a.id)
        self.assertEqual(tile['value'], len(funds))
        self.assertAlmostEqual(tile['secondary'], allocated, places=2)
        self.assertEqual(self.env['microfinance.fond.credit'].search(tile['domain']), funds)

    def test_erreur_de_calcul_jamais_affichee_a_zero(self):
        broken = {key: [('champ_inexistant', '=', 1)] for key in (
            'active', 'pending_disbursement', 'defaulted', 'outstanding', 'defaulted_disbursed', 'overdue')}
        with patch.object(type(self.env['microfinance.loan']), '_overview_loan_domains', lambda self, company_id: broken), \
                self.assertLogs('odoo.addons.microfinance_loan_management.models.microfinance_loan', level='ERROR'):
            tiles = self._tiles()
        for key in ('active_loan_count', 'granted_amount', 'outstanding_amount', 'overdue_amount', 'default_rate'):
            self.assertIsNone(tiles[key]['value'], key)
            self.assertTrue(tiles[key]['error'], key)

    def test_echeances_du_jour_lien_meme_domaine(self):
        data = self.env['microfinance.loan'].get_dashboard_data()
        link = data['today_installments_link']
        self.assertEqual(self.env[link['model']].search_count(link['domain']), data['today_installments_count'])
