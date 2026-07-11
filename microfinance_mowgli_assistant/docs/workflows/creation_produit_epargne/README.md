# Workflow Création produit d'épargne

## 1. Objectif métier
Ce workflow couvre le paramétrage des produits d'épargne proposés par l'IMF : conditions financières (taux d'intérêt, méthode de calcul du solde, capitalisation), plafonds et limites (montant minimum d'ouverture, solde minimum à maintenir, plafond de retrait), frais de tenue de compte, et rattachement aux comptes comptables PCEC / journaux utilisés lors des dépôts et retraits. Il est porté par le modèle unique `microfinance.savings.product`. N'est PAS couvert ici : l'ouverture d'un compte d'épargne pour un client (`microfinance.savings.account`), ni l'enregistrement des transactions de dépôt/retrait (`microfinance.savings.transaction`), qui font l'objet d'autres workflows (comptabilité, gestion des comptes épargne).

## 2. Utilisateurs concernés
D'après `microfinance_savings_management/security/ir.model.access.csv` et `microfinance_savings_management/security/savings_security.xml` :
- **Manager épargne** (`group_savings_manager`) : accès complet (lecture, écriture, création, suppression).
- **Agent épargne** (`group_savings_agent`) : lecture seule.
- **Manager crédit** (`microfinance_loan_management.group_microfinance_manager`) : lecture seule.
- **Auditeur microfinance** (`microfinance_loan_management.group_microfinance_auditor`) : lecture seule.

## 3. Menus utilisés
Microfinance > Configuration > Produits d'épargne

Chaîne exacte reconstituée depuis les `<menuitem>` :
- `menu_microfinance_root` ("Microfinance", racine du module MLM)
- `menu_microfinance_config` ("Configuration", parent = `menu_microfinance_root`, réservé au groupe `group_microfinance_manager`)
- `menu_microfinance_savings_products` ("Produits d'épargne", parent = `microfinance_loan_management.menu_microfinance_config`, action = `action_microfinance_savings_product`), défini dans `microfinance_savings_management/views/microfinance_savings_menus.xml`.

## 4. Étapes principales
Séquence dérivée du formulaire (`microfinance_savings_product_views.xml`), sans bouton `action_*` dédié (le modèle ne contient aucune méthode `action_*` métier) :
1. Ouvrir Microfinance > Configuration > Produits d'épargne et cliquer sur « Nouveau ».
2. Saisir le nom et le code du produit (le code doit être unique par société).
3. Choisir le type de produit (Obligatoire / Volontaire / À terme) et la société.
4. Si le type est « À terme », renseigner la durée en mois (champ obligatoire dans ce cas) et la pénalité de retrait anticipé.
5. Renseigner l'onglet « Intérêts » : taux d'intérêt annuel, méthode de calcul du solde, fréquence de capitalisation.
6. Renseigner l'onglet « Limites » : montant minimum d'ouverture, solde minimum à maintenir, plafond de retrait (montant + période), frais de tenue de compte (montant + fréquence).
7. Renseigner l'onglet « Comptabilité » : journaux de dépôt/retrait et comptes PCEC (épargne, intérêts, pénalités, commissions, comptes partagés) ; des valeurs par défaut sont proposées automatiquement si le plan PCEC de la société contient les comptes correspondants.
8. Enregistrer. Les contraintes `@api.constrains` sont vérifiées à la sauvegarde.

## 5. Champs importants
**En-tête**
- `name` (Nom) : nom du produit d'épargne.
- `code` (Code) : code unique par société (contrainte SQL `code_company_unique`).
- `company_id` (Société), `currency_id` (Devise, related sur la société, lecture seule), `active` (Actif).
- `product_type` (Type de produit) : Obligatoire (liée à un crédit) / Volontaire / À terme (dépôt à terme).
- `term_months` (Durée en mois) : visible et requis uniquement si `product_type = 'term_deposit'`.
- `early_withdrawal_penalty_rate` (Pénalité de retrait anticipé %) : visible uniquement si `product_type = 'term_deposit'`.

**Onglet Intérêts**
- `interest_rate` (Taux intérêt annuel %).
- `balance_method` (Méthode de calcul du solde) : Solde minimum de la période / Solde moyen de la période / Solde en fin de période.
- `capitalization_frequency` (Fréquence de capitalisation) : Mensuelle / Trimestrielle / Annuelle.

**Onglet Limites**
- `min_opening_amount` (Montant minimum d'ouverture).
- `min_balance` (Solde minimum à maintenir) : solde gelé, un retrait ne peut pas faire descendre le compte en dessous de ce montant sauf dérogation explicite (selon le `help` du champ).
- `withdrawal_limit_amount` (Plafond de retrait) et `withdrawal_limit_period` (Par transaction / Par mois).
- `maintenance_fee_amount` (Frais de tenue de compte) et `maintenance_fee_frequency` (Mensuelle / Trimestrielle / Annuelle).

**Onglet Comptabilité**
- Journaux : `deposit_journal_id` (Journal dépôt), `withdrawal_journal_id` (Journal retrait) — domaine `type in (bank, cash)`, défaut = journal de code `EPG` de la société.
- Comptes Épargne (obligatoires) : `account_epargne_individuel_id`, `account_epargne_groupe_id`, `account_epargne_entreprise_id` — un compte par type de client (Individuel / Groupe / Entreprise), domaine `account_type = liability_current`.
- Comptes Intérêts (facultatifs) : `account_interet_paye_*_id` (charge), `account_interets_avance_*_id` (compte d'avance, passif), `account_cout_interet_payer_*_id` (passif), chacun décliné en Individuel/Groupe/Entreprise.
- Comptes partagés (facultatifs) : `account_penalites_id` (Pénalités sur épargne, produit), `account_commission_id` (Commission sur épargne, produit — requis uniquement si des frais sont prélevés), `account_commission_cheques_rejetes_id` (Commission sur chèques rejetés, produit), `account_retenue_taxe_id` (Retenue de taxe, passif — compte technique 467000 hors nomenclature PCEC officielle selon le commentaire du code), `account_papeterie_id` (Papeterie pour l'épargne, produit).
- Tous les comptes ont pour défaut calculé une recherche par code PCEC + société courante (fonction `_pcec_default`), et restent vides si le compte n'existe pas encore pour la société (plan PCEC non chargé).

## 6. Boutons et actions
Aucun bouton `type="object"` dans la vue formulaire (`view_microfinance_savings_product_form`) : le modèle ne définit aucune méthode `action_*`. La création/modification se fait uniquement par saisie de champs et enregistrement standard Odoo.

## 7. Règles métier
Contraintes `@api.constrains('interest_rate', 'min_opening_amount', 'min_balance', 'withdrawal_limit_amount', 'maintenance_fee_amount', 'early_withdrawal_penalty_rate', 'term_months', 'product_type')` (méthode `_check_values`) :
- Le taux d'intérêt ne peut pas être négatif.
- Les montants minimum (`min_opening_amount`, `min_balance`) ne peuvent pas être négatifs.
- Le plafond de retrait ne peut pas être négatif.
- Les frais de tenue de compte ne peuvent pas être négatifs.
- La pénalité de retrait anticipé ne peut pas être négative.
- Un produit à terme (`product_type = 'term_deposit'`) doit avoir une durée en mois (`term_months`).

Contrainte SQL : `code_company_unique` — le code produit doit être unique par société.

Méthode utilitaire `_get_account(self, kind, partner)` : retourne dynamiquement le compte comptable (`account_<kind>_individuel_id` / `_groupe_id` / `_entreprise_id`) selon le champ `microfinance_client_type` du partenaire (mappé sur `company` → « entreprise », `group` → « groupe », tout autre valeur → « individuel »). Utilisée par le module pour choisir le bon compte lors des écritures de transactions d'épargne (hors périmètre de ce workflow).

Valeurs par défaut : tous les comptes PCEC et les journaux sont pré-remplis par recherche automatique sur le code comptable/journal + société courante (jamais par référence XML statique), afin de fonctionner correctement en environnement multi-société.

## 8. Contrôles et blocages
- Impossible d'enregistrer un produit avec un taux d'intérêt, un montant minimum d'ouverture, un solde minimum, un plafond de retrait, des frais de tenue de compte ou une pénalité de retrait anticipé négatifs (message d'erreur dédié pour chaque cas, voir section 7).
- Impossible d'enregistrer un produit « À terme » sans durée en mois : « Un produit à terme doit avoir une durée en mois. »
- Impossible de créer deux produits avec le même code dans la même société (contrainte SQL `code_company_unique`) : « Le code produit doit être unique par société. »
- Les champs `account_epargne_individuel_id`, `account_epargne_groupe_id`, `account_epargne_entreprise_id` sont `required=True` : l'enregistrement est bloqué par Odoo si l'un d'eux est vide.

## 9. Statuts
Le modèle `microfinance.savings.product` n'a pas de champ `state`. Le seul indicateur de cycle de vie est le champ booléen `active` (Actif), qui contrôle l'archivage standard Odoo (un produit inactif est masqué des vues par défaut mais reste consultable via le filtre archivé). Aucune machine à états, aucun `statusbar_visible`.

## 10. Rapports ou PDF
Aucun rapport dédié à ce jour.

## 11. Tableaux de bord
Aucun indicateur lié à `microfinance.savings.product` trouvé dans `microfinance_loan_management/models/microfinance_dashboard.py` (dashboard de portefeuille crédit uniquement, hors périmètre épargne). À compléter si un tableau de bord épargne existe ailleurs dans le code (non identifié dans les fichiers sources listés).

## 12. Sécurité et groupes utilisateurs
Table issue de `microfinance_savings_management/security/ir.model.access.csv` (modèle `model_microfinance_savings_product`) :

| Groupe | Lecture | Écriture | Création | Suppression |
|---|---|---|---|---|
| Agent épargne (`group_savings_agent`) | Oui | Non | Non | Non |
| Manager épargne (`group_savings_manager`) | Oui | Oui | Oui | Oui |
| Manager crédit (`microfinance_loan_management.group_microfinance_manager`) | Oui | Non | Non | Non |
| Auditeur microfinance (`microfinance_loan_management.group_microfinance_auditor`) | Oui | Non | Non | Non |

Le menu « Configuration » (`menu_microfinance_config`), parent de « Produits d'épargne », est en outre restreint dans son affichage au groupe `microfinance_loan_management.group_microfinance_manager` (attribut `groups=` du `<menuitem>`), ce qui signifie en pratique que seul un Manager crédit ou un Manager épargne disposant aussi de ce groupe voit l'entrée de menu, même si l'accès technique en lecture est plus large.

## 13. Cas d'utilisation complets
1. **Création d'un produit d'épargne volontaire.** Un Manager épargne va dans Microfinance > Configuration > Produits d'épargne, clique sur « Nouveau », saisit Nom = « Épargne libre », Code = « EPL », laisse Type de produit = « Volontaire », renseigne le taux d'intérêt annuel et la fréquence de capitalisation dans l'onglet Intérêts, le solde minimum dans l'onglet Limites, vérifie les comptes PCEC proposés par défaut dans l'onglet Comptabilité, puis enregistre.
2. **Création d'un produit à terme.** Le Manager épargne choisit Type de produit = « À terme (dépôt à terme) » ; le champ Durée (mois) devient obligatoire et le champ Pénalité de retrait anticipé apparaît ; s'il enregistre sans durée, Odoo bloque avec le message « Un produit à terme doit avoir une durée en mois. »
3. **Consultation par un auditeur.** Un utilisateur du groupe Auditeur microfinance accède au menu (si visible) ou à la liste des produits d'épargne en lecture seule pour vérifier les taux et comptes configurés, sans pouvoir modifier ni créer de produit.

## 14. Erreurs fréquentes
- « Le taux d'intérêt ne peut pas être négatif. »
- « Les montants minimum ne peuvent pas être négatifs. »
- « Le plafond de retrait ne peut pas être négatif. »
- « Les frais de tenue de compte ne peuvent pas être négatifs. »
- « La pénalité de retrait anticipé ne peut pas être négative. »
- « Un produit à terme doit avoir une durée en mois. »
- « Le code produit doit être unique par société. » (violation de la contrainte SQL lors de la création/duplication).
- Blocage Odoo générique si l'un des trois comptes d'épargne obligatoires (`account_epargne_individuel_id`, `account_epargne_groupe_id`, `account_epargne_entreprise_id`) est laissé vide.

## 15. Bonnes pratiques
- Vérifier que le plan comptable PCEC de la société est chargé avant de créer un produit d'épargne, afin que les comptes par défaut (recherche automatique par code) se pré-remplissent correctement plutôt que de rester vides.
- Renseigner les comptes d'intérêts, pénalités et commissions même s'ils sont facultatifs dans le code, dès lors que le mécanisme correspondant (intérêts, frais de tenue de compte, pénalité de retrait anticipé) est effectivement utilisé par CEFOR, pour éviter des écritures comptables incomplètes en aval.
- Pour un produit à terme, définir systématiquement la durée en mois avant tout autre paramétrage, car le champ devient bloquant à l'enregistrement.
- Réserver la création/modification des produits d'épargne au groupe Manager épargne, conformément aux droits définis dans `ir.model.access.csv` (les autres groupes n'ont qu'un accès lecture).

## 16. Questions/Réponses MOWGLI potentielles
1. Comment créer un nouveau produit d'épargne dans MOWGLI ?
2. Où configurer le taux d'intérêt d'un compte d'épargne ?
3. Quel est le solde minimum à maintenir sur tel produit d'épargne ?
4. Comment paramétrer un produit à terme (dépôt à terme) ?
5. Pourquoi le système me demande une durée en mois pour ce produit d'épargne ?
6. Quels comptes comptables sont utilisés pour l'épargne individuelle par rapport à l'épargne de groupe ?
7. Qui a le droit de créer ou modifier un produit d'épargne ?
8. Comment fonctionne le plafond de retrait sur un produit d'épargne ?
9. Pourquoi je ne peux pas enregistrer un produit d'épargne avec un taux négatif ?
10. Quelle est la différence entre les méthodes de calcul du solde (minimum, moyen, fin de période) ?
