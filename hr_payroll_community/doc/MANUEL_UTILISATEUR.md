# Manuel Utilisateur — Paie Madagascar (hr_payroll_community)

Ce manuel couvre les fonctionnalités ajoutées au module de paie pour la
gestion de la paie malgache : plafond CNAPS/OSTIE, Déclaration des
Salaires, comptabilisation des bulletins, retenues sur salaire, workflow
de validation, visionneuse PDF et avantages en nature.

## 1. Configuration (Paramètres > Paie)

Menu : **Paie > Configuration > Paramètres**

- **Madagascar** : renseigner le *Montant SME* (Salaire Minimum
  d'Embauche) et le *Multiplicateur du plafond CNAPS* (8 par défaut).
  Le plafond de cotisation CNAPS/OSTIE = Montant SME × Multiplicateur.
- **Accounting** : sélectionner le *Journal de paie*, utilisé pour générer
  l'écriture comptable à la validation des bulletins.

Sur la fiche employé (**Employés**), un champ *Nombre de personnes à
charge* est disponible à côté du champ *Enfants* — utilisé dans le calcul
de l'IRSA (réduction de 2 000 Ar par personne à charge).

## 2. Plafond CNAPS/OSTIE mutualisé

Le plafond est calculé automatiquement dès qu'un contrat appelle
`contract.get_cnaps_ceiling(base)` dans le code Python d'une règle
salariale (CNAPS_SAL, OSTIE_SAL, CNAPS_PAT, OSTIE_PAT). Aucune action
utilisateur requise au-delà de la configuration du §1 : si le montant SME
n'est pas renseigné, aucun plafonnement n'est appliqué.

## 3. Déclaration des Salaires (DS)

Menu : **Paie > Reporting > Déclaration des Salaires**

1. Choisir la période (Du / Au) et la société.
2. Cliquer sur **Générer le fichier XLSX**.
3. Le fichier est téléchargé automatiquement ; il liste, par employé, le
   salaire brut, l'IRSA, le CNAPS+OSTIE salarial et patronal, et le FMFP,
   agrégés sur les bulletins validés (« Validé » ou « Payé ») de la
   période.

## 4. Comptabilisation des bulletins

1. Sur chaque règle salariale (**Paie > Configuration > Règles
   Salariales**), renseigner les comptes *Compte à débiter* / *Compte à
   créditer* dans l'onglet General.
2. À la validation d'un bulletin (bouton **Valider**, voir §6), une
   écriture comptable est générée automatiquement dans le journal de paie
   et postée. Elle regroupe les montants par catégorie (Basic, Allowance,
   Deduction, Company Contribution) et par compte.
3. Le bouton **Écriture comptable** (coin supérieur droit du bulletin)
   ouvre l'écriture générée.

Si aucun journal de paie n'est configuré (§1), un message d'erreur explicite
s'affiche à la validation.

## 5. Retenues sur salaire (avances, pensions alimentaires, saisies)

Menu : **Paie > Configuration > Retenues sur Salaire**

- Créer une retenue : sélectionner un ou plusieurs employés, le type
  (Avance sur salaire / Pension alimentaire / Saisie sur salaire), le
  montant et la période (date de fin facultative = retenue récurrente).
- Un raccourci **Appliquer une Retenue en Masse** (même menu) permet
  d'appliquer la même retenue à plusieurs employés en une seule fois.
- La retenue est automatiquement injectée comme ligne d'input lors du
  calcul de tout bulletin dont la période chevauche la retenue.

## 6. Workflow du bulletin (Brouillon → En attente → Validé → Payé)

1. **Brouillon** : le bulletin peut être librement modifié.
2. **Vérifier** (officier paie) : calcule les lignes et passe le bulletin
   en *En attente*.
3. **Valider** (manager paie) : disponible uniquement depuis *En attente* ;
   génère et poste l'écriture comptable, passe le bulletin en *Validé*.
4. **Marquer Payé** (manager paie) : disponible uniquement depuis
   *Validé* ; passe le bulletin en *Payé* et coche « Made Payment Order ».
5. **Annuler** : disponible tant que le bulletin n'est pas payé.

## 7. Visionneuse PDF intégrée

Sur un bulletin non-brouillon, le bouton **Voir PDF** (en-tête du
formulaire) génère et ouvre directement le PDF du bulletin dans le
navigateur, sans passer par l'aperçu d'impression standard d'Odoo.

## 8. Avantages en nature (véhicule, logement, autre)

Sur la fiche contrat (**Contrats**), un tableau *Avantages en Nature* a
été ajouté sous les avantages en espèces. Deux façons de l'alimenter :

- Ajouter directement une ligne dans le tableau (type, valeur imposable,
  valeur non imposable) ;
- Ou cliquer sur **Configurer un Avantage** pour ouvrir l'assistant dédié.

Chaque avantage génère, au calcul du bulletin, un input distinct pour sa
part imposable et sa part non imposable.

---
*Voir aussi `doc/RELEASE_NOTES.md` pour l'historique des versions.*
