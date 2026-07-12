# -*- coding: utf-8 -*-
"""res.partner.microfinance_profession passe de Char (texte libre) à Many2one vers le nouveau
modèle microfinance.profession. Un changement de type in-place (même nom de champ) ferait
tenter à l'ORM un ALTER COLUMN ... TYPE int4 USING microfinance_profession::int4, qui échoue
dès qu'une valeur existante n'est pas numérique (ex. "Vendeur" trouvé en donnée réelle) — on
sauvegarde donc l'ancienne colonne texte avant que l'ORM ne l'altère, pour reconstituer le lien
en post-migrate une fois le nouveau modèle chargé."""


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'microfinance_profession'
    """)
    if cr.fetchone():
        cr.execute(
            "ALTER TABLE res_partner RENAME COLUMN microfinance_profession TO microfinance_profession_old_char"
        )
