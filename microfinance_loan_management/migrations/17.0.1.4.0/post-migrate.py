# -*- coding: utf-8 -*-
"""Backfill de arrears_onset_date pour les échéances déjà en retard au moment de la mise à jour
du module (mêmes conditions que la branche 'overdue' de installment._compute_state, reproduites
en SQL direct). Limite assumée : seules les échéances actuellement en retard sont initialisées ;
les épisodes d'impayés déjà soldés avant cette migration ne peuvent pas être reconstitués faute
d'historique, et n'apparaîtront donc pas dans les mois passés du graphique "Évolution des
impayés" du tableau de bord (cf. docs_dev/dashboard/evolution_impayes.md)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE microfinance_loan_installment
        SET arrears_onset_date = due_date
        WHERE due_date < CURRENT_DATE
          AND residual_amount > 0.01
          AND residual_amount >= total_amount - 0.01
          AND arrears_onset_date IS NULL
    """)
