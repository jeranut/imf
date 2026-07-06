def migrate(cr, version):
    """Marque le plus ancien account.daily.balance de chaque société comme
    ayant un solde initial défini : ces enregistrements historiques ont déjà
    un solde de départ légitime mais n'ont pas encore le nouveau flag."""
    cr.execute("""
        UPDATE account_daily_balance b
        SET solde_initial_defini = TRUE
        FROM (
            SELECT DISTINCT ON (company_id) id
            FROM account_daily_balance
            ORDER BY company_id, date ASC, id ASC
        ) oldest
        WHERE b.id = oldest.id
    """)
