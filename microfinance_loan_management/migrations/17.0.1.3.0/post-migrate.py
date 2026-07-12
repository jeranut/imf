# -*- coding: utf-8 -*-
"""Reconstitue le lien res.partner.microfinance_profession (Many2one) à partir de l'ancienne
colonne texte sauvegardée en pre-migrate. Les enregistrements microfinance.profession de la
donnée de démo (data/microfinance_profession_data.xml, déjà chargée à ce stade) sont réutilisés
par correspondance insensible à la casse ; toute valeur texte existante sans correspondance
(profession libre non prévue dans la liste de départ) obtient son propre enregistrement créé à
la volée, pour ne perdre aucune donnée réelle."""


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'microfinance_profession_old_char'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT id, microfinance_profession_old_char FROM res_partner
        WHERE microfinance_profession_old_char IS NOT NULL
          AND btrim(microfinance_profession_old_char) != ''
    """)
    rows = cr.fetchall()

    name_to_id = {}
    for partner_id, raw_name in rows:
        name = raw_name.strip()
        key = name.lower()
        profession_id = name_to_id.get(key)
        if profession_id is None:
            cr.execute("SELECT id FROM microfinance_profession WHERE lower(name) = %s LIMIT 1", (key,))
            existing = cr.fetchone()
            if existing:
                profession_id = existing[0]
            else:
                cr.execute(
                    "INSERT INTO microfinance_profession (name, active) VALUES (%s, true) RETURNING id",
                    (name,),
                )
                profession_id = cr.fetchone()[0]
            name_to_id[key] = profession_id
        cr.execute(
            "UPDATE res_partner SET microfinance_profession = %s WHERE id = %s",
            (profession_id, partner_id),
        )

    cr.execute("ALTER TABLE res_partner DROP COLUMN microfinance_profession_old_char")
