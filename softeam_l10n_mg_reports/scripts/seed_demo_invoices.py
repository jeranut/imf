"""Seed Madagascar demo invoices via odoo shell.

Crée 4 factures démo couvrant les principaux cas TVA Madagascar :

* MG-DEMO-V001 — Vente locale 1 000 000 MGA HT + TVA 20 % collectée
* MG-DEMO-V002 — Vente export 800 000 MGA HT + TVA 0 % (export)
* MG-DEMO-A001 — Achat B&S 500 000 MGA HT + TVA 20 % déductible
* MG-DEMO-A002 — Achat immobilisations 2 000 000 MGA HT + TVA 20 % déd. immo

Prérequis :
* Le PCG 2005 Madagascar (``softeam_l10n_mg``) doit être chargé sur la société
  active de l'utilisateur (Settings → Companies → "Madagascar - PCG 2005").
* Les partenaires démo (``demo_partner_tana``, ``demo_partner_export``,
  ``demo_partner_faniry``) doivent exister — installés par
  ``softeam_l10n_mg_reports`` en mode démo.

Usage Docker :

    docker exec -i sr_v18_odoo odoo shell --config=/etc/odoo/odoo.conf \\
        -d <database> --no-http <<'EOF'
    exec(open('/mnt/extra-addons/softeam_l10n_mg_reports/scripts/seed_demo_invoices.py').read())
    EOF

Usage direct (Odoo Python):

    >>> exec(open('softeam_l10n_mg_reports/scripts/seed_demo_invoices.py').read())

Le script est idempotent : les factures référencées par leur champ ``ref``
(MG-DEMO-*) ne sont pas recréées si elles existent déjà.
"""
import logging

_logger = logging.getLogger(__name__)


def seed(env):
    company = env.company
    Move = env['account.move']
    Partner = env['res.partner']
    Tax = env['account.tax']

    # Idempotence
    if Move.search_count([
        ('company_id', '=', company.id),
        ('ref', 'like', 'MG-DEMO-%'),
    ]):
        print("Factures démo déjà présentes — rien à faire.")
        return

    # Verify chart loaded
    company_field = 'company_ids' if 'company_ids' in env['account.account']._fields else 'company_id'
    company_op = 'in' if company_field == 'company_ids' else '='
    if not env['account.account'].search_count([
        (company_field, company_op, company.id),
        ('code', '=like', '4111%'),
    ]):
        print("PCG 2005 Madagascar non chargé sur la société '{}' — abandon."
              .format(company.display_name))
        print("Charger le plan via Settings → Companies → 'Madagascar - PCG 2005'.")
        return

    # Resolve taxes
    tva_sale_20 = Tax.search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'sale'),
        ('amount', '=', 20.0),
        ('country_id.code', '=', 'MG'),
    ], limit=1)
    tva_export_0 = Tax.search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'sale'),
        ('amount', '=', 0.0),
        ('name', 'ilike', 'export'),
    ], limit=1)
    tva_purchase_bs = Tax.search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'purchase'),
        ('amount', '=', 20.0),
        ('name', 'ilike', 'biens'),
    ], limit=1)
    tva_purchase_immo = Tax.search([
        ('company_id', '=', company.id),
        ('type_tax_use', '=', 'purchase'),
        ('amount', '=', 20.0),
        ('name', 'ilike', 'immobilisations'),
    ], limit=1)

    if not (tva_sale_20 and tva_purchase_bs):
        print("Taxes 20 % introuvables — vérifier que le chart est complet.")
        return

    # Resolve partners (created by demo data)
    client_local = env.ref('softeam_l10n_mg_reports.demo_partner_tana', raise_if_not_found=False)
    client_export = env.ref('softeam_l10n_mg_reports.demo_partner_export', raise_if_not_found=False)
    fournisseur = env.ref('softeam_l10n_mg_reports.demo_partner_faniry', raise_if_not_found=False)

    if not client_local:
        client_local = Partner.create({'name': 'TANA SARL (démo)', 'country_id': env.ref('base.mg').id})
    if not client_export:
        client_export = Partner.create({'name': 'USA Trading Inc. (démo)', 'country_id': env.ref('base.us').id})
    if not fournisseur:
        fournisseur = Partner.create({'name': 'FANIRY Sarl (démo)', 'country_id': env.ref('base.mg').id})

    invoices_to_create = [
        ('out_invoice', client_local, 'MG-DEMO-V001',
         'Prestation de conseil — Antananarivo', 1_000_000.0, tva_sale_20),
        ('out_invoice', client_export, 'MG-DEMO-V002',
         'Export — Logiciel sur mesure', 800_000.0, tva_export_0 or tva_sale_20),
        ('in_invoice', fournisseur, 'MG-DEMO-A001',
         'Fournitures de bureau', 500_000.0, tva_purchase_bs),
        ('in_invoice', fournisseur, 'MG-DEMO-A002',
         'Acquisition matériel informatique',
         2_000_000.0, tva_purchase_immo or tva_purchase_bs),
    ]

    created = Move.browse([])
    for move_type, partner, ref, label, price, tax in invoices_to_create:
        if not tax:
            print(f"Skip {ref} : taxe non disponible.")
            continue
        move = Move.create({
            'move_type': move_type,
            'partner_id': partner.id,
            'company_id': company.id,
            'ref': ref,
            'invoice_date': '2026-04-15',
            'invoice_line_ids': [(0, 0, {
                'name': label,
                'quantity': 1.0,
                'price_unit': price,
                'tax_ids': [(6, 0, tax.ids)],
            })],
        })
        created |= move

    created.action_post()
    print(f"Créé {len(created)} factures démo pour {company.display_name} :")
    for m in created:
        print(f"  - {m.ref:15s} {m.move_type:12s} {m.partner_id.name:30s} "
              f"{m.amount_total:>15,.2f} {m.currency_id.name}")


# Execute when run via odoo shell or env is provided
try:
    seed(env)  # type: ignore[name-defined]  # provided by odoo shell
except NameError:
    print("Lancer ce script via `odoo shell` (env doit être disponible).")
