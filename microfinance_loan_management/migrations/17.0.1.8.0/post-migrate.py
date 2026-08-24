# -*- coding: utf-8 -*-
"""Alignement LPF (décision du 2026-08-18) : periods_per_year devient la source de vérité
pour _period_interest_factor(), remplaçant le calcul en jours calendaires réels
(period_value / 365) pour les périodicités infra-mensuelles. Ce script met à jour les
enregistrements microfinance.repayment.frequency déjà chargés en noupdate="1", que la
mise à jour du data file seule ne toucherait pas."""

PERIODS_PER_YEAR_BY_CODE = {
    'daily': 365,
    'weekly': 52,
    'biweekly': 26,
    'four_weekly': 13,
    'monthly': 12,
    'bimonthly': 6,
    'quarterly': 4,
    'four_monthly': 3,
    'semiannual': 2,
    'annual': 1,
}


def migrate(cr, version):
    for code, periods in PERIODS_PER_YEAR_BY_CODE.items():
        cr.execute(
            "UPDATE microfinance_repayment_frequency SET periods_per_year = %s WHERE code = %s",
            (periods, code),
        )
