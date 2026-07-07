# -*- coding: utf-8 -*-
"""repayment_frequency (Selection figée) est remplacé par repayment_frequency_mode +
repayment_frequency_id (+ allowed_repayment_frequency_ids pour le mode choix du client).
Tous les produits existants sont repris en mode 'fixed', avec repayment_frequency_id pointant
vers l'enregistrement microfinance.repayment.frequency correspondant à leur ancienne valeur
(seed data déjà chargée avant ce script, cf. data/repayment_frequency_data.xml). Les crédits déjà
créés sont ensuite alignés sur la périodicité de leur propre produit, pour que l'échéancier déjà
généré et l'historique de rééchelonnement restent cohérents avec la nouvelle logique."""

FREQUENCY_XMLID_BY_CODE = {
    'daily': 'repayment_frequency_daily',
    'weekly': 'repayment_frequency_weekly',
    'biweekly': 'repayment_frequency_biweekly',
    'four_weekly': 'repayment_frequency_four_weekly',
    'monthly': 'repayment_frequency_monthly',
    'bimonthly': 'repayment_frequency_bimonthly',
    'quarterly': 'repayment_frequency_quarterly',
    'four_monthly': 'repayment_frequency_four_monthly',
    'semiannual': 'repayment_frequency_semiannual',
    'annual': 'repayment_frequency_annual',
}


def migrate(cr, version):
    cr.execute("""
        SELECT name, res_id FROM ir_model_data
        WHERE module = 'microfinance_loan_management' AND name = ANY(%s)
    """, (list(FREQUENCY_XMLID_BY_CODE.values()),))
    frequency_id_by_xmlid = dict(cr.fetchall())

    cr.execute("SELECT id, repayment_frequency FROM microfinance_loan_product")
    for product_id, old_code in cr.fetchall():
        xmlid = FREQUENCY_XMLID_BY_CODE.get(old_code, FREQUENCY_XMLID_BY_CODE['monthly'])
        frequency_id = frequency_id_by_xmlid.get(xmlid)
        if not frequency_id:
            continue
        cr.execute("""
            UPDATE microfinance_loan_product
            SET repayment_frequency_mode = 'fixed', repayment_frequency_id = %s
            WHERE id = %s
        """, (frequency_id, product_id))

    cr.execute("""
        UPDATE microfinance_loan l
        SET repayment_frequency_id = p.repayment_frequency_id
        FROM microfinance_loan_product p
        WHERE l.product_id = p.id AND l.repayment_frequency_id IS NULL
    """)
