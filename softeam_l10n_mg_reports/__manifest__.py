{
    'name': 'Rapports de Comptabilité Malagasy (PCG 2005)',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Localizations/Reporting',
    'summary': 'Compta Malagasy Madagascar — Rapports : déclaration TVA, Bilan PCG 2005, Compte de Résultat par nature, l10n_mg reports, comptabilité Malagasy',
    'description': "<h2>Rapports de Comptabilit&eacute; Malagasy (PCG 2005)</h2>"
                   "<p>Rapports financiers conformes au <strong>Plan Comptable G&eacute;n&eacute;ral 2005</strong> Malagasy (d&eacute;cret n&deg;2004-272 du 18 f&eacute;vrier 2004).</p>"
                   "<p><em>Mots-cl&eacute;s :</em> Madagascar, Malagasy, compta Malagasy, comptabilit&eacute; Madagascar, d&eacute;claration TVA Madagascar, bilan Madagascar, compte de r&eacute;sultat Madagascar, PCG 2005, &eacute;tats financiers Malagasy.</p>"
                   "<h3>Contenu</h3>"
                   "<ul>"
                   "<li><strong>D&eacute;claration TVA Madagascar</strong> : ventilation par nature d'op&eacute;ration (CA taxable / non-taxable / export, TVA collect&eacute;e / d&eacute;ductible B&amp;S / d&eacute;ductible immobilisations, calcul du solde &agrave; d&eacute;caisser).</li>"
                   "<li><strong>Bilan PCG 2005</strong> : Actif (non-courant + courant) / Capitaux propres &amp; passifs (capitaux propres + passifs non-courants + passifs courants), avec totaux et sous-totaux.</li>"
                   "<li><strong>Compte de R&eacute;sultat par nature</strong> : structure officielle PCG 2005 (chiffre d'affaires, achats consomm&eacute;s, charges externes, charges de personnel, dotations, r&eacute;sultat op&eacute;rationnel, r&eacute;sultat financier, imp&ocirc;ts, r&eacute;sultat net).</li>"
                   "</ul>"
                   "<h3>Compatibilit&eacute;</h3>"
                   "<p>Compatible <strong>Odoo 17 / 18 / 19</strong>. La visualisation interactive n&eacute;cessite <strong>Odoo Enterprise</strong> (module <code>account_reports</code>). Sur Community, les records sont charg&eacute;s mais le viewer n'est pas disponible.</p>"
                   "<p>Pour Odoo 16, utiliser l'ancien module <code>softeam_l10n_mg</code> (legacy).</p>"
                   "<h3>Source officielle</h3>"
                   "<ul>"
                   "<li>D&eacute;cret n&deg;2004-272 du 18 f&eacute;vrier 2004</li>"
                   "<li>Annexe I PCG 2005 (mod&egrave;les d'&eacute;tats financiers)</li>"
                   "</ul>"
                   "<h3>Support</h3>"
                   "<p><a href=\"mailto:support@softeamg.com\">support@softeamg.com</a> &middot; <a href=\"https://softeamg.com\">softeamg.com</a></p>",
    'author': 'SofteamG',
    'website': 'https://softeamg.com',
    'support': 'support@softeamg.com',
    'license': 'LGPL-3',
    'depends': [
        'softeam_l10n_mg',
        'account',
    ],
    'data': [
        'data/tax_report_data.xml',
        'data/balance_sheet_data.xml',
        'data/income_statement_data.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'images': [
        'static/description/banner.png',
        'static/description/icon.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
