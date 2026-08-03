#!/usr/bin/env python3
import argparse
from collections import defaultdict

import psycopg2


CATEGORIES = {
    "family_income": {
        "label": "Revenus familiaux",
        "designation_table": "microfinance_financial_designation_income",
        "designation_column": "income_designation_id",
    },
    "activity_expense": {
        "label": "Dépenses d'activité",
        "designation_table": "microfinance_financial_designation_activity_expense",
        "designation_column": "activity_expense_designation_id",
    },
    "family_expense": {
        "label": "Dépenses familiales",
        "designation_table": "microfinance_financial_designation_family_expense",
        "designation_column": "family_expense_designation_id",
    },
}
SITUATIONS = {
    "current": "Actuelle",
    "forecast": "Prévisionnelle",
}


def connect(dbname):
    return psycopg2.connect(
        host="127.0.0.1",
        port=5432,
        user="odoo",
        password="rotas@135",
        dbname=dbname,
    )


def list_databases():
    with connect("postgres") as conn, conn.cursor() as cr:
        cr.execute(
            "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
        )
        return [row[0] for row in cr.fetchall()]


def table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def module_installed(cr):
    if not table_exists(cr, "ir_module_module"):
        return False
    cr.execute(
        """
        SELECT 1
          FROM ir_module_module
         WHERE name = 'microfinance_loan_management'
           AND state = 'installed'
         LIMIT 1
        """
    )
    return bool(cr.fetchone())


def expected_designations(cr, info):
    cr.execute(
        f"""
        SELECT id, name
          FROM {info["designation_table"]}
         WHERE active IS TRUE
         ORDER BY sequence, id
        """
    )
    return cr.fetchall()


def application_label(row):
    app_id, name, partner_name = row
    parts = [f"id={app_id}"]
    if name:
        parts.append(str(name))
    if partner_name:
        parts.append(str(partner_name))
    return " / ".join(parts)


def audit_database(dbname, apply=False, require_installed=True):
    with connect(dbname) as conn, conn.cursor() as cr:
        if require_installed and not module_installed(cr):
            return None
        required_tables = [
            "microfinance_loan_application",
            "microfinance_loan_application_income_line",
            "microfinance_financial_designation_income",
            "microfinance_financial_designation_activity_expense",
            "microfinance_financial_designation_family_expense",
            "microfinance_financial_frequency",
            "res_partner",
        ]
        if any(not table_exists(cr, table) for table in required_tables):
            return None

        expected_by_category = {
            category: expected_designations(cr, info)
            for category, info in CATEGORIES.items()
        }
        expected_ids_by_category = {
            category: {row[0] for row in rows}
            for category, rows in expected_by_category.items()
        }

        cr.execute(
            """
            SELECT app.id, app.name, partner.name
              FROM microfinance_loan_application app
         LEFT JOIN res_partner partner ON partner.id = app.partner_id
             ORDER BY app.id
            """
        )
        applications = cr.fetchall()

        report = {
            "db": dbname,
            "applications": len(applications),
            "expected": {
                category: len(rows) for category, rows in expected_by_category.items()
            },
            "before": [],
            "after": [],
            "deleted_empty": 0,
            "deleted_duplicate": 0,
            "deleted_inactive": 0,
            "created_missing": 0,
        }

        for app in applications:
            app_id = app[0]
            for category, info in CATEGORIES.items():
                designation_column = info["designation_column"]
                expected_ids = expected_ids_by_category[category]
                for situation in SITUATIONS:
                    cr.execute(
                        f"""
                        SELECT id, {designation_column}
                          FROM microfinance_loan_application_income_line
                         WHERE application_id = %s
                           AND category = %s
                           AND situation = %s
                         ORDER BY id
                        """,
                        (app_id, category, situation),
                    )
                    lines = cr.fetchall()
                    by_designation = defaultdict(list)
                    empty_ids = []
                    inactive_ids = []
                    for line_id, designation_id in lines:
                        if not designation_id:
                            empty_ids.append(line_id)
                        elif designation_id not in expected_ids:
                            inactive_ids.append(line_id)
                        else:
                            by_designation[designation_id].append(line_id)

                    duplicate_ids = []
                    for ids in by_designation.values():
                        duplicate_ids.extend(ids[1:])

                    missing_designation_ids = sorted(
                        expected_ids.difference(by_designation.keys())
                    )

                    status = {
                        "application": application_label(app),
                        "category": category,
                        "situation": situation,
                        "actual": len(lines),
                        "expected": len(expected_ids),
                        "empty": len(empty_ids),
                        "duplicates": len(duplicate_ids),
                        "inactive": len(inactive_ids),
                        "missing": len(missing_designation_ids),
                    }
                    report["before"].append(status)

                    if apply:
                        delete_ids = empty_ids + duplicate_ids + inactive_ids
                        if delete_ids:
                            cr.execute(
                                """
                                DELETE FROM microfinance_loan_application_income_line
                                 WHERE id = ANY(%s)
                                """,
                                (delete_ids,),
                            )
                            report["deleted_empty"] += len(empty_ids)
                            report["deleted_duplicate"] += len(duplicate_ids)
                            report["deleted_inactive"] += len(inactive_ids)

                        if missing_designation_ids:
                            cr.execute(
                                """
                                SELECT id
                                  FROM microfinance_financial_frequency
                                 WHERE active IS TRUE
                                 ORDER BY CASE WHEN name = 'Mensuel' THEN 0 ELSE 1 END,
                                          sequence,
                                          id
                                 LIMIT 1
                                """
                            )
                            frequency_row = cr.fetchone()
                            frequency_id = frequency_row[0] if frequency_row else None
                            for designation_id in missing_designation_ids:
                                cr.execute(
                                    f"""
                                    INSERT INTO microfinance_loan_application_income_line
                                        (application_id, category, situation,
                                         {designation_column}, amount, frequency_id,
                                         monthly_amount, create_uid, create_date,
                                         write_uid, write_date)
                                    VALUES
                                        (%s, %s, %s, %s, 0, %s, 0, 1, NOW(), 1, NOW())
                                    """,
                                    (
                                        app_id,
                                        category,
                                        situation,
                                        designation_id,
                                        frequency_id,
                                    ),
                                )
                            report["created_missing"] += len(missing_designation_ids)

        if apply:
            conn.commit()

            for app in applications:
                app_id = app[0]
                for category, info in CATEGORIES.items():
                    designation_column = info["designation_column"]
                    expected_ids = expected_ids_by_category[category]
                    for situation in SITUATIONS:
                        cr.execute(
                            f"""
                            SELECT COUNT(*),
                                   COUNT(*) FILTER (WHERE {designation_column} IS NULL),
                                   COUNT(DISTINCT {designation_column})
                              FROM microfinance_loan_application_income_line
                             WHERE application_id = %s
                               AND category = %s
                               AND situation = %s
                            """,
                            (app_id, category, situation),
                        )
                        actual, empty, distinct_designations = cr.fetchone()
                        report["after"].append({
                            "application": application_label(app),
                            "category": category,
                            "situation": situation,
                            "actual": actual,
                            "expected": len(expected_ids),
                            "empty": empty,
                            "distinct": distinct_designations,
                        })

        return report


def print_report(report, show_clean=False):
    if report is None:
        return
    print(
        f"\nDB {report['db']}: {report['applications']} dossier(s), attendus "
        f"revenus={report['expected']['family_income']}, "
        f"dep_activite={report['expected']['activity_expense']}, "
        f"dep_famille={report['expected']['family_expense']}"
    )
    problems = [
        row for row in report["before"]
        if row["actual"] != row["expected"]
        or row["empty"]
        or row["duplicates"]
        or row["inactive"]
        or row["missing"]
    ]
    rows = report["before"] if show_clean else problems
    if not rows:
        print("  Avant: aucun écart.")
    else:
        print("  Avant:")
        for row in rows:
            print(
                "   - {application} | {category}/{situation}: "
                "actuel={actual}, attendu={expected}, vides={empty}, "
                "doublons={duplicates}, inactifs={inactive}, manquants={missing}".format(**row)
            )

    if report["after"]:
        bad_after = [
            row for row in report["after"]
            if row["actual"] != row["expected"]
            or row["empty"]
            or row["distinct"] != row["expected"]
        ]
        print(
            "  Nettoyage: vides supprimées={deleted_empty}, "
            "doublons supprimés={deleted_duplicate}, "
            "inactifs supprimés={deleted_inactive}, "
            "manquantes recréées={created_missing}".format(**report)
        )
        if bad_after:
            print("  Après: ECARTS RESTANTS")
            for row in bad_after:
                print(
                    "   - {application} | {category}/{situation}: "
                    "actuel={actual}, attendu={expected}, vides={empty}, distinct={distinct}".format(**row)
                )
        else:
            print("  Après: tous les tableaux sont conformes.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-uninstalled", action="store_true")
    parser.add_argument("--show-clean", action="store_true")
    parser.add_argument("dbnames", nargs="*")
    args = parser.parse_args()

    dbnames = args.dbnames or list_databases()
    any_report = False
    for dbname in dbnames:
        report = audit_database(
            dbname,
            apply=args.apply,
            require_installed=not args.include_uninstalled,
        )
        if report is None:
            continue
        any_report = True
        print_report(report, show_clean=args.show_clean)
    if not any_report:
        print("Aucune base avec microfinance_loan_management installé trouvée.")


if __name__ == "__main__":
    main()
