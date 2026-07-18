# Audit ciblé — Chatter absent sur microfinance.loan

Diagnostic uniquement. Aucun correctif appliqué dans cette passe.

Base de données concernée : `SEFOR` (identifiée comme celle contenant le dossier
`CR/2026/00001` cité dans le contexte — les autres bases avec le module installé,
`imf_menu_filter_test`, `imf_scratch_test`, `imf_test_dev`, n'ont pas ce dossier).

## Résumé de la cause probable (à lire en premier)

Le fichier source `views/microfinance_loan_views.xml:176` utilise la balise
auto-fermante `<chatter/>`. **Cette balise n'existe pas dans Odoo 17.0** — c'est
une syntaxe introduite en Odoo 18. Dans cette version (17.0, confirmée en base),
le compilateur de formulaire JS (`addons/mail/static/src/views/web/form/form_compiler.js:73-76`)
ne reconnaît que le sélecteur `div.oe_chatter` :

```js
registry.category("form_compilers").add("chatter_compiler", {
    selector: "div.oe_chatter",
    fn: compileChatter,
});
```

`<chatter/>` n'étant pas `div.oe_chatter`, aucun compilateur ne le prend en charge.
Le navigateur le traite comme un élément HTML personnalisé inconnu, vide (balise
auto-fermante, sans enfants) : il ne produit ni erreur JS, ni contenu visible.
Tout le reste de la chaîne (modèle, champs, vue combinée, droits, RPC) fonctionne
normalement, ce qui explique pourquoi rien d'anormal n'apparaît côté serveur ni
dans la console JS.

---

## 1. Champs mail réellement présents en base

**Preuve** — requête SQL sur `SEFOR` :
```sql
select name, ttype, state from ir_model_fields
where model='microfinance.loan'
  and name in ('message_follower_ids','message_ids','message_partner_ids',
               'activity_ids','message_attachment_count');
```
Résultat : les 5 champs existent, `state = base` (donc bien déclarés par le
mixin `mail.thread`/`mail.activity.mixin`, pas des champs orphelins).

Confirmé également via le shell Odoo :
```python
FIELDS_OK: True
```

**Conclusion** : le mixin est correctement chargé, les champs mail sont bien
enregistrés pour `microfinance.loan`. Aucune anomalie ici.

---

## 2. Vue compilée réellement chargée

**Preuve** — toutes les vues `form` en base pour `microfinance.loan` (y compris
non versionnées) :
```
2246  microfinance.loan.form                    (base)      microfinance_loan_management
2254  microfinance.loan.form.scoring.inherit     inherit_id=2246   microfinance_loan_management
2280  microfinance.loan.form.inherit.savings     inherit_id=2246   microfinance_savings_management
```
→ Il existe une **troisième vue héritante non mentionnée** dans le contexte
initial de l'audit : `view_microfinance_loan_form_inherit_savings` (module
`microfinance_savings_management`). Vérifiée : elle ajoute des champs après
`co_borrower_id` et `fee_move_id`, elle ne touche ni `<sheet>` ni `<chatter/>`.
Elle n'est donc pas en cause, mais son existence méritait d'être signalée — elle
n'était pas documentée comme héritant du formulaire.

`arch_db` de la vue de base 2246 (contenu réellement stocké en base, pas le
fichier source) :
```
ligne 22  : <sheet>
ligne 116 : </sheet>
ligne 117 : <chatter/>
```
→ Identique au fichier source. Le `-u` a bien pris en compte le fichier XML tel
quel.

Vue combinée réelle envoyée au client, obtenue via `env['microfinance.loan'].get_view(view_type='form')` (shell Odoo) :
```
CHATTER_IN_COMBINED_ARCH: True
...
                </sheet>
                <chatter/>
            </form>
```
→ La balise `<chatter/>` est bien présente telle quelle, non transformée, dans
l'arch final envoyé au client.

**Conclusion** : ni une vue cachée/non versionnée, ni un problème d'héritage.
La balise arrive intacte jusqu'au client — c'est bien elle-même qui pose
problème (cf. cause probable).

---

## 3. Droits d'accès sur les modèles mail

**Preuve** — shell Odoo, avec l'utilisateur Administrator :
```python
ACCESS mail.message: OK
ACCESS mail.followers: OK
ACCESS mail.activity: OK
```
Et lecture réelle des champs sur le dossier CR/2026/00001 :
```python
READ RESULT: [{'id': 1,
  'message_follower_ids': [45],
  'message_ids': [1974, 208, 207, 206, 203, 202, 196, 190, 189, 188, 187, 186, 185],
  'message_partner_ids': [3],
  'activity_ids': []}]
```
→ 13 messages existent réellement pour ce dossier, lisibles sans erreur.

**Conclusion** : aucune règle `ir.rule` ni ACL ne bloque la lecture. Le
composant chatter aurait toutes les données nécessaires s'il était monté.

---

## 4. Logs serveur Odoo au chargement de la fiche

**Preuve** — `odoo.log`, requêtes horodatées correspondant aux ouvertures de la
fiche :
```
"POST /web/dataset/call_kw/microfinance.loan/get_views HTTP/1.1" 200 - ...
"POST /web/dataset/call_kw/microfinance.loan/web_read HTTP/1.1" 200 - 47 ...
```
Toutes en 200, aucune trace ni traceback lié à `microfinance.loan` ou au
chatter. La seule erreur présente dans le log (`ir_autovacuum` /
`financial.report`) est un cron sans rapport.

**Conclusion** : aucune erreur serveur avalée silencieusement. Le serveur sert
correctement la vue et les données à chaque requête.

---

## 5. Requête réseau réelle (RPC)

**Preuve** — le `web_read` loggé ci-dessus renvoie 47 champs en 200 OK, et le
test direct en shell (point 3) confirme que `message_follower_ids`/`message_ids`
sont bien réclamés et retournés avec des valeurs non vides. Le contenu JSON de
la réponse contient donc les données du chatter.

**Conclusion** : le problème n'est pas côté définition des champs demandés par
le client ni côté payload — les données arrivent bien jusqu'au navigateur.

---

## 6. Présence DOM du composant chatter

**Non vérifiable directement dans cet environnement** (pas d'accès navigateur
interactif depuis cet audit). Mais l'analyse du compilateur JS (section
"cause probable") permet de prédire le résultat avec certitude : le DOM rendu
contiendra un élément littéral `<chatter></chatter>` (élément HTML personnalisé
non reconnu, donc sans styles ni comportement), **et non** un nœud
`o-mail-ChatterContainer` / `o_ChatterContainer`. Le composant Owl `Chatter`
n'est jamais instancié : `compileChatter()` n'est appelé que pour les nœuds
matchant `div.oe_chatter`, jamais pour `<chatter/>`.

C'est cohérent avec l'observation initiale : pas d'erreur JS (un tag inconnu
ne lève pas d'exception, juste un warning de custom element dans certains
navigateurs, souvent invisible parmi le bruit du bundle minifié), et rien
d'affiché.

---

## Cause probable

`views/microfinance_loan_views.xml:176` utilise la syntaxe Odoo 18
`<chatter/>` dans un dépôt/environnement Odoo **17.0**. Cette balise n'a aucune
signification pour le compilateur de formulaire de cette version — seul le
motif `<div class="oe_chatter"> + champs message_follower_ids/activity_ids/
message_ids</div>` est reconnu (`addons/mail/static/src/views/web/form/form_compiler.js:73-76`).
Aucune étape de validation (ni au `-u`, ni côté RNG) n'a rejeté la vue, donc
l'erreur est passée inaperçue jusqu'au rendu navigateur, où elle échoue
silencieusement.

Tout le reste de la chaîne — mixins, champs, droits, vue combinée, RPC — est
sain, ce qui confirme que le problème est localisé à cette seule ligne.

## Correctif proposé (à valider avant application)

Remplacer, dans `views/microfinance_loan_views.xml`, à la ligne 176 :
```xml
<chatter/>
```
par le motif standard Odoo 17 :
```xml
<div class="oe_chatter">
    <field name="message_follower_ids" widget="mail_followers"/>
    <field name="activity_ids" widget="mail_activity"/>
    <field name="message_ids" widget="mail_thread"/>
</div>
```
Cette modification suffit en théorie à faire réapparaître le chatter, sans
toucher au reste de la vue (le `</sheet>` juste au-dessus n'a pas besoin de
changer). À confirmer par un test visuel après application.
