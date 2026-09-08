# LOT — Mise en page de l'encart emprunteur (NY MPINDRAM-BOLA / MOMBAMOMBA)

Implémentation directe (pas d'audit préalable), calquée sur
`reference_mise_en_page_carnet.png`. **Aucune valeur de champ modifiée** : uniquement CSS +
structure de mise en forme de l'encart du recto. Le tableau carnet, le texte d'attestation et
le verso ne sont pas touchés.

## Fait — `report_carnet_remboursement.xml`

### CSS (`<style>`)

- `.carnet-header-title` : `margin-bottom` 6px → 8px.
- `.carnet-box` : suppression de `border: 1.5px solid #000` et `padding: 6px 10px` — les deux
  sections ne sont plus encadrées (conforme à la référence), la classe ne sert plus que
  d'espaceur (`margin-bottom: 10px`). Le cadre extérieur `.carnet-col-right` est conservé.
- `.carnet-box-title` : `font-size: 13px` (au lieu de 11px hérité), `margin: 2px 0 13px`
  (titres centrés agrandis, plus d'air en dessous).
- `.carnet-row` : `margin-bottom` 4px → 10px, `line-height: 1.25` — interlignes aérés comme la
  référence.
- Nouveau `.carnet-row .cr-label` : `display:inline-block; min-width: 34%; vertical-align: top`
  → colonne de libellés à largeur fixe, deux-points et valeurs alignés verticalement. Les
  libellés plus longs que 34 % débordent et poussent leur valeur (comportement visible sur la
  référence : « Famerenanana… », « Fotoana farany… »).
- Nouveau `.carnet-row .cr-sec` : `margin-left: 18px` → écart régulier avant la 2ᵉ paire
  libellé/valeur d'une ligne.
- Nouveau `.carnet-row.cr-tight` : `margin-bottom: 2px` → paire resserrée Datin'ny findramana
  / Mpikarakara.

Commentaire de bloc ajouté au-dessus des règles pour tracer l'intention et le périmètre
(classes propres à cet encart, le verso utilise `.carnet-foot`).

### Structure (les deux `<div class="carnet-box">` du recto)

- Chaque libellé principal `<u>…</u> :` (deux-points et éventuel suffixe `(1)`, `(2)`,
  `(1)+(2)` inclus) enveloppé dans `<span class="cr-label">…</span>`.
- Chaque 2ᵉ paire de ligne (`Kara-panondro n°`, `Téléphone`, `Produit`, `Fifanarahana n°`,
  `Agent BL`) enveloppée dans `<span class="cr-sec">…</span>`, en remplacement des
  séparateurs `&#160;&#160;`.
- Ligne « Datin'ny findramana » : ajout de la classe `cr-tight`.
- `style` du `<img>` du logo : `max-height:32px;max-width:120px` → `38px` / `130px`.

Aucun `t-field` / `t-esc` / formule / texte malgache modifié.

## Vérifications

- `xmllint --noout` : OK.
- Cycle `stop → -u microfinance_loan_management --stop-after-init --no-http -d SEFOR → start` :
  93 modules chargés sans erreur, service actif.
- Rendu PDF réel via `odoo-bin shell` sur `IS/001076` : recto conforme à la référence
  (alignement libellés/valeurs, sections sans cadre, paire resserrée, interlignes, surlignage
  de date), verso inchangé. Le dossier de test a des données partenaire éparses (profession /
  téléphone / adresse vides) donc l'encart paraît plus vide que l'exemple de référence, mais
  l'agencement est identique. Le logo n'apparaît pas sur ce rendu : fichier absent du
  filestore de cette machine (`FileNotFoundError` sur l'attachement `res.company.logo`), pas
  un défaut du gabarit.

Aucun commit effectué — review et commit manuels par Micka.
