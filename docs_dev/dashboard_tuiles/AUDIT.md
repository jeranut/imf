# AUDIT — Tuiles « Vue d'ensemble » du tableau de bord : libellé = domaine = lien = liste

Date : 2026-10-07. Base : MOWGLI (lecture seule). Agence de référence : CEFOR Andoharanofotsy (AD, société 9).
Aucune modification de code. Décisions à trancher en **§ 5**.

## 1. Où sont définies les tuiles
- Calcul : `microfinance.loan.get_dashboard_data()` [microfinance_loan.py:757](../../microfinance_loan_management/models/microfinance_loan.py#L757). Lecture en `sudo()`, société active uniquement.
- Épargne : `microfinance_savings_management/models/microfinance_dashboard_extension.py` (2 tuiles ajoutées par héritage).
- Fonds : `microfinance.fond.credit.get_dashboard_kpi()` [microfinance_fond_credit.py:341](../../microfinance_loan_management/models/microfinance_fond_credit.py#L341).
- Liens : **domaines écrits en dur dans le XML** ([microfinance_loan_dashboard.xml:49-115](../../microfinance_loan_management/static/src/xml/microfinance_loan_dashboard.xml#L49-L115), `microfinance_savings_dashboard.xml`), différents de ceux du serveur, et `openKpiAction` ne filtre pas sur la société active.

## 2. État actuel tuile par tuile (AD, mesuré)

| Tuile (libellé actuel) | Domaine serveur | Domaine du lien | Tuile | Liste (manager, AD seule) |
|---|---|---|---|---|
| Credits actifs | `state='active'` **+ `disbursement_date` renseignée** | `state='active'` | **2** | **7** |
| Montant decaisse | `state in (active, closed, defaulted)` + décaissé, somme `loan_amount` | `state in (active, closed, defaulted)` | 1 500 000 | 4 400 000 |
| Encours total | `state in (active, defaulted)` + décaissé, somme `balance_total` | `state in (active, defaulted)` | 1 533 076,92 | 4 470 461,54 |
| Impayes | somme `loan.overdue_amount` des crédits actifs/défaut décaissés | **échéances** `state='overdue'` (autre modèle) | 0 | 0 |
| Taux defaut | nb défaut / nb actifs décaissés × 100 | crédits `state='defaulted'` (un compte, pas un taux) | 0 % | 0 |
| Fonds bailleurs (N actifs) | fonds actifs de l'agence + fonds partagés **ayant une allocation pour l'agence** ; total = part allouée | `active=True` | 2 fonds / 158 418 181,82 | 2 (3 avec 11 sociétés cochées) |
| Comptes épargne actifs | `state='active'`, conteneurs **inclus** | `state='active'` | 3 (dont 1 conteneur) | 3 |
| Encours épargne | somme `balance` des mêmes | idem | 100 000 | 100 000 |

### Pourquoi « Crédits actifs » = 2 au lieu de 7
Le serveur ajoute `disbursement_date != False` à `active_domain` (commentaire : « 'active' ne prouve plus qu'un crédit a été décaissé », découplage activation/décaissement). Les 5 crédits actifs sans date de décaissement sont exclus du chiffre, mais pas de la liste.

**Crédits actifs sans date de décaissement (anomalie à signaler, pas à cacher)** — tous à AD, agent `jeranutmickael@gmail.com` :

| Réf. | Client | Montant | Activé le | Libéré pour le guichet (`disbursement_release_ready`) |
|---|---|---|---|---|
| AD/000003 | TEST Rakoto 20260926041444000000 | 300 000 | 2026-09-26 | oui |
| AD/000004 | TEST Rakoto 20260926041445000000 | 300 000 | 2026-09-27 | oui |
| AD/000005 | TEST Rakoto 20260926041445000000 | 300 000 | 2026-09-27 | **non** |
| AD/000012 | randriana | 1 000 000 | 2026-10-05 | oui |
| AD/000013 | RINDRA BE | 1 000 000 | 2026-10-05 | oui |

Ce sont des crédits activés en attente de décaissement au guichet : c'est le circuit normal depuis le découplage, mais ils n'ont pas encore été réellement décaissés. Total 2 900 000 Ar. Avec tes définitions, ils entrent dans « Crédits actifs » (7), « Montant décaissé (crédits actifs) » (4 400 000) et « Encours des crédits actifs » (4 470 461,54) : voir D1.

## 3. Autres écarts constatés
1. **Liens sans filtre société.** `openKpiAction` n'ajoute pas `company_id = société active`. Avec 11 sociétés cochées, la liste « Crédits actifs » montre 12 lignes au lieu de 7, « Comptes épargne » 8 au lieu de 3, « Fonds » 3 au lieu de 2.
2. **Agent : tuile ≠ liste par construction.** Les tuiles sont calculées en `sudo()` sur toute l'agence (décision A4 : « Vue d'ensemble » identique pour tous les rôles). Les listes, elles, appliquent la règle d'isolation par agent (`microfinance_loan_officer_self_rule`). Pour ccl1, « Crédits actifs » affiche 2 mais la liste en montre 0. Voir D3.
3. **« Montant décaissé »** : le lien inclut `closed`, la tuile aussi, mais seulement les crédits décaissés. Ta définition le ramène aux crédits actifs.
4. **« Impayés »** : la tuile somme `microfinance.loan.overdue_amount` (stocké), le lien ouvre des échéances. Ce ne sont pas les mêmes lignes, même si les sommes coïncident quand tout est à jour.
5. **« Taux défaut »** : la formule (nombre de défauts / nombre d'actifs) n'a pas la même base que `get_par_buckets` (encours `balance_total` des actifs + défauts décaissés). Le lien ouvre une liste de crédits, pas un taux.
6. **« Fonds bailleurs »** : le total est la **part allouée à l'agence** (`allocation.solde_disponible`) pour les fonds partagés, alors que la liste `microfinance.fond.credit` affiche le solde **global** de chaque fonds. Le compteur (2) peut égaler la liste, mais pas la somme. Le fonds « Fonds spec » (maison mère, société 1) apparaît dans la liste dès que la maison mère est cochée.
7. **Épargne** : un conteneur actif (solde 0) est compté dans « Comptes épargne actifs ». Le groupe « Agent crédit » n'a pas de droit de lecture sur les comptes épargne : la liste lèverait une erreur d'accès pour un pur agent.

## 4. Corrections prévues (sans décision nécessaire)
- Un domaine par KPI, défini **une seule fois** côté serveur, renvoyé dans `get_dashboard_data()` (`kpi_links`), et utilisé tel quel par le lien. Il contient toujours `company_id = société active`, et la liste s'ouvre sans filtre par défaut.
- « Crédits actifs » = `state='active'` (7 pour AD) ; tuile **« Crédits en défaut »** séparée (`state='defaulted'`, avec son lien) ; les défauts ne sont jamais comptés dans « Crédits actifs ».
- « Montant décaissé (crédits actifs) » = somme `loan_amount` du domaine « Crédits actifs » (4 400 000) ; lien = même domaine.
- « Impayés » : lien vers la liste des **crédits** ayant `overdue_amount > 0` dans le domaine retenu (D4), somme = tuile.
- « Taux de défaut » : formule affichée dans une info-bulle (D5).
- Épargne : libellé selon D2 ; lien = même domaine que la tuile.
- Test obligatoire : pour chaque tuile cliquable, valeur == nombre de lignes (ou somme) de `search(domaine du lien)`. Jeu de données : actifs décaissés, actifs non décaissés, en défaut, brouillon, soldés, dans deux sociétés.

## 5. Décisions à trancher

**D1 — Crédits actifs non encore décaissés (5 à AD, 2 900 000 Ar).**
Suivre ta définition fait apparaître « Montant décaissé (crédits actifs) » = 4 400 000, alors que seuls 1 500 000 ont été réellement décaissés.
- (a) Libellé « Montant accordé (crédits actifs) » : 4 400 000, exact.
- (b) Garder « Montant décaissé (crédits actifs) », mais avec un compteur `disbursement_date` renseignée : 1 500 000 ; libellé « Montant décaissé (crédits actifs décaissés) » et lien sur ce domaine. Les 5 autres restent visibles dans « Crédits actifs ».
- (c) Ta définition telle quelle : 4 400 000 sous « Montant décaissé ». Je le déconseille, le chiffre serait faux au sens comptable.
- **Recommandé : (a).**

**D2 — Conteneurs épargne.** Ce sont des comptes techniques (solde 0) qui portent le numéro permanent. **Recommandé : les exclure**, avec le libellé « Comptes épargne actifs (hors conteneurs) », soit 2 à AD.

**D3 — Agents : tuiles d'agence en `sudo()` contre listes restreintes à l'agent.**
- (a) Tuiles calculées avec les droits de l'utilisateur. Un agent voit ses propres chiffres, et la liste correspond. « Vue d'ensemble » n'est alors plus identique pour tous les rôles, contrairement à la décision A4.
- (b) Chiffres d'agence pour tous, mais sans lien cliquable pour les rôles soumis à l'isolation, avec la mention « (agence) ».
- **Recommandé : (a)**, seule option qui garde « compteur = liste » pour tous les rôles cliquables.

**D4 — Encours, impayés et non décaissés : quel libellé pour l'encours ?**
- (a) « Encours des crédits actifs » = `balance_total` des actifs (4 470 461,54).
- (b) « Encours (actifs + en défaut) » = `state in (active, defaulted)`, avec son lien. Même base que le PAR et le taux de défaut ; identique aujourd'hui (aucun défaut à AD).
- **Recommandé : (b)**, cohérent avec le PAR. Les impayés suivent le même domaine que l'encours retenu.
- Point lié : les échéances pré-générées d'un crédit actif non décaissé peuvent passer `overdue` sans impayé réel. Faut-il les compter dans « Impayés » ? Si non, le libellé devient « Impayés (crédits décaissés) ».

**D5 — Base du taux de défaut.** Tu demandes « base identique à `get_par_buckets` ». Or `get_par_buckets` exclut les crédits non décaissés (`disbursement_date` renseignée).
- (a) Taux = encours des crédits en défaut / encours des crédits actifs + en défaut **décaissés** × 100 (base PAR actuelle, inchangée), avec une info-bulle qui le dit. La base diffère alors de la tuile Encours si D1/D4 inclut les non décaissés.
- (b) Retirer le filtre de décaissement de `get_par_buckets`, pour que PAR, taux et encours aient la même base. Cela dilue le PAR avec des crédits qui ne peuvent pas encore être en retard réel.
- **Recommandé : (a)**, avec l'info-bulle « Encours en défaut ÷ encours décaissé (actifs + défaut), même base que le PAR ».

**D6 — Fonds bailleurs.** Le total de la tuile est la part de l'agence, alors que la liste des fonds montre le solde global.
- (a) Lien vers la liste des **allocations** de l'agence (`microfinance.fond.allocation`, `company_id = agence`, fonds actif) plus les fonds mono-agence de l'agence. Libellé « Fonds disponibles pour l'agence (part allouée) ». Compteur et somme égaux à la liste, mais deux modèles à réunir.
- (b) Garder la liste des fonds et ne garder dans la tuile que le **nombre** de fonds, sous le libellé « Fonds accessibles à l'agence ». Le montant passe dans un libellé secondaire sans lien.
- **Recommandé : (b)**, plus simple et sans ambiguïté sur ce que la liste montre.
