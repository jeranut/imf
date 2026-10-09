# STATUS — Tuiles « Vue d'ensemble » : libellé = domaine = lien = liste

Mise à jour : 2026-10-07. Audit : [AUDIT.md](AUDIT.md). Décisions appliquées : D1 à D6. Diff **non commité**.

## Décision A4 révisée (rôle du sudo dans le tableau de bord)
- **Avant (A4)** : « Vue d'ensemble » est un tableau de bord d'agence, identique pour tous les rôles, calculé en `sudo()`. Cette décision était citée dans le code comme « résidu A4 de AUDIT_portefeuille_agent.md » ; ce document n'est pas dans le dépôt.
- **Désormais (D3, 2026-10-07)** : les tuiles « Vue d'ensemble » et les panneaux « Activité récente » sont calculés **avec les droits de l'utilisateur**. Ils dépendent donc du rôle : un agent voit ses propres crédits, un manager ou un gestionnaire toute l'agence active. Une tuile dont le modèle n'est pas lisible par l'utilisateur est **masquée**, jamais affichée à 0. Les graphiques « Analyses » (sans lien vers une liste) restent des agrégats d'agence en `sudo()`.

## Fait
### Serveur (`microfinance_loan_management/models/microfinance_loan.py`)
- `_overview_loan_domains(company_id)` : **un seul** domaine par KPI, toujours avec `company_id = société active` (`env.company`, domaine explicite, jamais seulement `allowed_company_ids`).
- `_get_overview_tiles()` : les tuiles, sans `sudo()`. Chaque tuile renvoie libellé, valeur, type, domaine, modèle, libellé du lien, info-bulle et texte secondaire. Le domaine renvoyé est celui qui a servi au calcul.
- `_overview_tile()` : chaque calcul tourne dans un savepoint. Une erreur est journalisée (`_logger.exception`) et la tuile affiche « — » avec une info-bulle d'erreur, jamais 0.
- `get_dashboard_data()` renvoie `tiles` (liste ordonnée) et `kpis` (`{clé: valeur}`, même source, conservé pour les appels existants).
- Activité récente : « Derniers prêts » et « Échéances du jour » avec les droits de l'utilisateur. Le lien « Voir les échéances du jour » ouvre exactement le domaine du panneau (`_get_due_today_domain`), au lieu de toutes les échéances.
- Fonds : `microfinance.fond.credit._get_agency_accessible_funds()` (fonds actifs de l'agence + fonds partagés ayant une allocation pour l'agence) est utilisée par la tuile **et** par `get_dashboard_kpi`. Le lien porte les ids calculés côté serveur. Le seul `sudo()` restant est la lecture du montant de l'allocation (documentée : l'agence ne voit par règle que sa propre allocation).
- Épargne (`microfinance_savings_management/models/microfinance_dashboard_extension.py`) : deux tuiles hors conteneurs, sans `sudo()`, masquées si l'utilisateur ne peut pas lire les comptes épargne. L'ancienne surcharge en `sudo()` est supprimée.

### Tuiles finales
| # | Libellé | Domaine (toujours + `company_id = société active`) | Valeur | Lien |
|---|---|---|---|---|
| 1 | Crédits actifs | `state='active'` | nombre | même domaine |
| 2 | Actifs en attente de décaissement | `state='active'`, `disbursement_date` vide | nombre | même domaine |
| 3 | Crédits en défaut | `state='defaulted'` | nombre | même domaine |
| 4 | Montant accordé (crédits actifs) | domaine 1 | somme `loan_amount` | domaine 1 |
| 5 | Encours décaissé (actifs + en défaut) | `state in (active, defaulted)`, `disbursement_date` renseignée | somme `balance_total` | même domaine |
| 6 | Impayés (crédits décaissés) | domaine 5 + `overdue_amount > 0` | somme `overdue_amount` | liste des **crédits** de ce domaine |
| 7 | Taux de défaut | encours des défauts décaissés ÷ encours du domaine 5 × 100 (base `get_par_buckets`, inchangée) | % | aucun ; info-bulle « Encours en défaut ÷ encours décaissé (actifs + défaut), même base que le PAR » |
| 8 | Fonds accessibles à l'agence | ids de `_get_agency_accessible_funds` | nombre ; « dont part allouée à l'agence : X » sans lien | liste des fonds (mêmes ids) |
| 9 | Comptes épargne actifs (hors conteneurs) | `state='active'`, `is_container=False` | nombre | même domaine |
| 10 | Encours épargne (hors conteneurs) | domaine 9 | somme `balance` | domaine 9 |

### Interface
- `microfinance_loan_dashboard.xml` : les tuiles sont rendues en boucle à partir de `tiles`. **Plus aucun domaine écrit en dur.** Une erreur s'affiche « — » avec son info-bulle ; le taux affiche une icône d'information avec sa formule ; la tuile des fonds a son texte secondaire.
- `openKpiTile(tile)` ouvre la liste avec le domaine reçu tel quel, `context: {}` (aucun `search_default_*`, aucune facette parasite). Les anciens `openKpiAction` et `openAllInstallments` sont supprimés.
- Bouton « Actualiser » (recharge `get_dashboard_data`). Aucun cache serveur ; le tableau de bord se recharge à chaque ouverture.
- `microfinance_savings_dashboard.xml` (tuiles épargne écrites en dur) est supprimé du module épargne, ainsi que de ses assets ; le SCSS épargne est conservé pour les couleurs.
- Nouvelle couleur de tuile `--attente` (gris neutre) et barre d'outils dans le SCSS du dashboard.

## Avant / après — MOWGLI, Andoharanofotsy (copie de la base, mesuré)
Manager/auditeur (`jeranutmickael@gmail.com`) ; « liste » = lignes, ou somme, de la liste ouverte par le lien.

| Tuile | Avant : tuile | Avant : liste (AD seule / 11 sociétés cochées) | Après : tuile | Après : liste (AD seule / 11 sociétés) |
|---|---|---|---|---|
| Crédits actifs | 2 | 7 / 12 | **7** | 7 / 7 |
| Actifs en attente de décaissement | — (n'existait pas) | — | **5** | 5 / 5 |
| Crédits en défaut | — (lien seulement) | 0 | 0 | 0 / 0 |
| Montant accordé (crédits actifs) — avant « Montant decaisse » | 1 500 000 | 4 400 000 / 6 300 000 | **4 400 000** | 4 400 000 / 4 400 000 |
| Encours décaissé (actifs + en défaut) — avant « Encours total » | 1 533 076,92 | 4 470 461,54 / 6 450 769,23 | **1 533 076,92** | idem / idem |
| Impayés (crédits décaissés) | 0 (lien vers des échéances) | 0 | 0 | 0 / 0 |
| Taux de défaut | 0 % (nb défauts / nb actifs) | lien vers défauts | 0 % (base encours) | pas de lien |
| Fonds accessibles à l'agence — avant « Fonds bailleurs » | 2 (158 418 181,82) | 2 / 3 | **2**, part allouée 158 418 181,82 | 2 / 2 |
| Comptes épargne actifs (hors conteneurs) | 3 (conteneur inclus) | 3 / 8 | **2** | 2 / 2 |
| Encours épargne (hors conteneurs) | 100 000 | 100 000 / 175 000 | 100 000 | 100 000 / 100 000 |

Agent ccl1 (aucun crédit à son nom) : avant, la tuile « Crédits actifs » affichait 2 et la liste 0. Après, toutes ses tuiles crédit valent 0 et leurs listes 0 ; il a un accès épargne, donc ses tuiles épargne sont visibles (2 et 100 000, égales à leurs listes).

Contrôle : 2 décaissés + 5 en attente = 7 crédits actifs. L'encours (1 533 076,92) ne porte que sur les 2 décaissés, conformément à D4 ; les 5 en attente restent visibles dans les tuiles 1, 2 et 4.

## Tests
- `microfinance_loan_management/tests/test_dashboard_tiles.py` (8 tests, `MicrofinanceNoFundMixin`). Jeu de données dans 2 sociétés : actif décaissé avec impayé, actif sans date de décaissement, en défaut, brouillon, soldé.
  - Chaque tuile cliquable est égale à `search(domaine renvoyé)`, en nombre ou en somme.
  - Définitions et répartition : défaut jamais dans actifs, décaissés + en attente = actifs, encours sans les non-décaissés, impayés sur des crédits.
  - Société B invisible depuis A même avec les deux cochées ; `company_id` présent dans chaque domaine.
  - Taux de défaut égal au calcul sur la base de `get_par_buckets`.
  - Agent : ses tuiles égalent ses listes, et les tuiles épargne sont masquées.
  - Fonds : compteur, part allouée et liste.
  - Erreur injectée : « — » + erreur journalisée, jamais 0.
  - Lien des échéances du jour : même domaine.
- `microfinance_savings_management/tests/test_dashboard_savings_kpis.py` (+2) : tuiles hors conteneurs égales à leurs listes ; tuiles masquées sans droit de lecture.
- Non-régression : suites complètes des 4 modules (crédit, épargne, payroll, test de charge) sur une copie de MOWGLI, comparées au code d'avant ces lots : **les mêmes 114 échecs** des deux côtés, tous préexistants (fonds rotatif réel de MOWGLI, échéancier, caisse) ; 1051 tests contre 1014, les 37 ajoutés passent.
- « Crédits actifs = 7 pour AD » dépend des données réelles : c'est vérifié sur la copie de MOWGLI (tableau ci-dessus), pas par un test unitaire, qui serait fragile.

## Onglets non alignés dans ce lot
| Onglet / panneau | Pourquoi |
|---|---|
| Analyses : crédits par état, décaissements et remboursements par mois, impayés mensuels, PAR, répartition du risque, top des impayés | graphiques sans lien vers une liste, aucune ambiguïté compteur/liste ; restent des agrégats d'agence en `sudo()`. Pour un agent, ils montrent donc plus que ses tuiles : à arbitrer si « Analyses » doit aussi dépendre du rôle. |
| Fonds bailleurs : graphiques d'utilisation, matrice fonds × agences | aucun lien vers une liste ; la matrice couvre volontairement toutes les sociétés de l'utilisateur (docstring de `get_fond_matrix`). |
| Activité récente : « Voir tous les prêts » | ouvre le menu Crédits complet ; le libellé dit « tous », il n'y a pas de compteur associé. |
| Activité récente : « Derniers prêts » | 5 lignes sans lien ni compteur. |

## À faire
- Vérification dans le navigateur : rendu des tuiles, info-bulles, bouton Actualiser, ouverture des listes. Vider le cache (Ctrl+Maj+R) après déploiement.
