# -*- coding: utf-8 -*-
"""Sous-lot D — garde-fou sur la LIVRAISON du frontend (pas seulement sa présence
sur le disque).

Contexte : le sous-lot D a d'abord été livré avec le patch JS et le template XML
présents dans le module mais le template + le SCSS ABSENTS de la clé `assets` du
manifeste (état « ISOLATION »). Résultat : l'onglet « Transfert » et la recherche
cross-agence n'apparaissaient pas au guichet, alors que toute la couche backend
(search_other_agency_clients, register_transfert, …) fonctionnait et que TOUS les
tests du sous-lot D passaient — ils étaient 100 % backend.

Second piège : un `expr` de xpath contenant « -- » (p. ex. la classe BEM
`o_microfinance_pos__col--numpad`) fait planter la génération du bundle backend
NON minifié (mode debug=assets) : Odoo recopie l'`expr` dans un commentaire XML de
traçabilité (assetsbundle.py, AssetsBundle.xml / show_inherit_info), or « -- » y
est interdit.

Aucun test de méthode backend ne peut détecter ces deux régressions.
"""
import ast
import re

from lxml import etree

from odoo.tests.common import TransactionCase
from odoo.modules.module import get_module_path

MODULE = 'microfinance_transfert_inter_agence'
JS = 'static/src/js/microfinance_caisse_pos_transfert.js'
XML = 'static/src/xml/microfinance_caisse_pos_transfert.xml'
SCSS = 'static/src/scss/microfinance_caisse_pos_transfert.scss'
FRONT_FILES = (JS, XML, SCSS)


class TestFrontendAssetsDeclared(TransactionCase):

    def test_manifest_declares_all_three_front_files(self):
        """Le manifeste doit déclarer les 3 fichiers frontend dans
        web.assets_backend — pas seulement le JS (régression « ISOLATION »)."""
        with open(get_module_path(MODULE) + '/__manifest__.py', encoding='utf-8') as fh:
            manifest = ast.literal_eval(fh.read())
        backend = manifest.get('assets', {}).get('web.assets_backend', [])
        for rel in FRONT_FILES:
            self.assertIn(
                '%s/%s' % (MODULE, rel), backend,
                "%s doit être listé dans assets['web.assets_backend'] du manifeste, "
                "sinon l'onglet Transfert n'est jamais rendu au guichet." % rel,
            )

    def test_backend_bundle_actually_resolves_the_three_files(self):
        """Vérifie via le mécanisme réel d'Odoo (_get_asset_content) que les 3
        fichiers entrent bien dans le bundle web.assets_backend calculé."""
        files, _external = self.env['ir.qweb']._get_asset_content('web.assets_backend')
        urls = {f['url'].lstrip('/') for f in files}
        for rel in FRONT_FILES:
            self.assertIn('%s/%s' % (MODULE, rel), urls)


class TestFrontendTemplateXpath(TransactionCase):

    def test_xpath_expr_contain_no_double_dash(self):
        """Aucun `expr` de xpath du template hérité ne doit contenir « -- » :
        en mode debug=assets, Odoo l'écrit dans un commentaire XML (interdit),
        ce qui casse TOUT le bundle backend non minifié."""
        tree = etree.parse(get_module_path(MODULE) + '/' + XML)
        exprs = tree.xpath('//xpath/@expr') + tree.xpath('//*/@expr')
        self.assertTrue(exprs, "le template devrait contenir au moins un xpath")
        for expr in exprs:
            self.assertNotIn(
                '--', expr,
                "xpath expr=%r contient « -- » : la génération du bundle backend "
                "non minifié (debug=assets) lèvera ValueError. Cibler le noeud "
                "autrement (position, classe sans double tiret)." % expr,
            )

    def test_template_inherits_the_guichet_component(self):
        tree = etree.parse(get_module_path(MODULE) + '/' + XML)
        inherits = tree.xpath('//t/@t-inherit')
        self.assertIn('microfinance_loan_management.MicrofinanceCaissePos', inherits)
