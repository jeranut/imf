# -*- coding: utf-8 -*-
"""Renomme microfinance_fond_credit.bank_journal_id (journal bancaire saisi à la main, 17.0.1.26) en
fund_journal_id (journal de fonds calculé depuis la banque du fonds) pour conserver les valeurs
existantes ; l'entrée ir.model.fields suit pour que la colonne ne soit pas supprimée à la mise à jour.
Schéma uniquement, idempotent."""


def migrate(cr, version):
    cr.execute("""SELECT column_name FROM information_schema.columns
                  WHERE table_name = 'microfinance_fond_credit' AND column_name IN ('bank_journal_id', 'fund_journal_id')""")
    cols = {r[0] for r in cr.fetchall()}
    if 'bank_journal_id' in cols and 'fund_journal_id' not in cols:
        cr.execute("ALTER TABLE microfinance_fond_credit RENAME COLUMN bank_journal_id TO fund_journal_id")
        cr.execute("""UPDATE ir_model_fields SET name = 'fund_journal_id'
                      WHERE model = 'microfinance.fond.credit' AND name = 'bank_journal_id'""")
    # La vue héritée qui affichait bank_journal_id est recréée par views/microfinance_fond_liaison_views.xml ;
    # tant qu'elle existe en base avec l'ancien champ, la validation de la vue parente échoue au chargement.
    cr.execute("""SELECT res_id FROM ir_model_data
                  WHERE module = 'microfinance_loan_management' AND model = 'ir.ui.view'
                    AND name = 'view_microfinance_fond_credit_form_bank_journal'""")
    row = cr.fetchone()
    if row:
        cr.execute("DELETE FROM ir_ui_view WHERE id = %s", (row[0],))
        cr.execute("""DELETE FROM ir_model_data WHERE module = 'microfinance_loan_management'
                      AND model = 'ir.ui.view' AND name = 'view_microfinance_fond_credit_form_bank_journal'""")
