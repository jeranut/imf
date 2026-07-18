# Audit ciblé — Échec de chargement du bundle web_editor.backend_assets_wysiwyg

Audit diagnostic uniquement (aucun correctif appliqué). Contexte : le wizard
natif `base.document.layout` (Réglages > Paramètres généraux > Mise en page du
document) lève `AssetsLoadingError` sur
`/web/assets/e05f7b3/web_editor.backend_assets_wysiwyg.min.js`.

## Résumé de la cause

**Ce n'est pas une erreur de compilation JS/SCSS.** C'est un **fichier de
filestore manquant** : l'enregistrement `ir.attachment` du bundle compilé
existe en base, mais le blob physique qu'il référence n'a jamais été écrit (ou
a disparu) sur disque. Aucun module custom du dépôt n'est impliqué dans la
génération de ce bundle.

---

## 1. Cause réelle de l'échec du bundle

**Preuve** : log serveur (`/opt/odoo17/odoo.log:241561-241589`), requête du
16/07/2026 17:29:46 :

```
2026-07-16 17:29:46,169 96666 ERROR SEFOR odoo.http: Exception during request handling.
Traceback (most recent call last):
  File "/opt/odoo17/odoo/http.py", line 2409, in __call__
    response = request._serve_db()
  ...
  File "/opt/odoo17/addons/web/controllers/binary.py", line 137, in content_assets
    stream = request.env['ir.binary']._get_stream_from(attachment, 'raw', filename)
  File "/opt/odoo17/odoo/addons/base/models/ir_binary.py", line 126, in _get_stream_from
    stream = self._record_to_stream(record, field_name)
  File "/opt/odoo17/addons/website/models/ir_binary.py", line 41, in _record_to_stream
    return super()._record_to_stream(record, field_name)
  File "/opt/odoo17/odoo/addons/base/models/ir_binary.py", line 73, in _record_to_stream
    return Stream.from_attachment(record)
  File "/opt/odoo17/odoo/http.py", line 538, in from_attachment
    stat = os.stat(self.path)
FileNotFoundError: [Errno 2] No such file or directory: '/opt/odoo17/.local/share/Odoo/filestore/SEFOR/92/92767bfc20ad8b1855de4f651fc7c817c0528bc3'
2026-07-16 17:29:46,171 96666 INFO SEFOR werkzeug: 127.0.0.1 - - "GET /web/assets/.../web_editor.backend_assets_wysiwyg.min.js HTTP/1.1" 500 - 3 0.002 0.006
```

Requête directe (`curl` de vérification, session en cours) : la même URL
`e05f7b3` retourne maintenant un **404** (le comportement 404 vs 500 dépend du
mode debug de la requête ; la cause sous-jacente — fichier absent — est
identique).

**Conclusion** : la pile d'appels ne passe à aucun moment par un compilateur
JS/SCSS (webpack, esbuild, sass). Elle échoue uniquement au moment de streamer
le contenu déjà « compilé » depuis le disque (`os.stat`). Le message
navigateur (`AssetsLoadingError`) est donc une conséquence d'un problème de
stockage, pas d'un bug de code frontend.

---

## 2. Modules custom contribuant à ce bundle

**Preuve** :
```
grep -rn "backend_assets_wysiwyg\|web_editor" --include="__manifest__.py" .
→ (aucun résultat)
```
Sections `assets` de tous les manifests custom du dépôt
(`microfinance_loan_management`, `microfinance_savings_management`,
`microfinance_mowgli_assistant`, `microfinance_data_reset_wizard`,
`web_responsive`, `plan_compta_pcec`, `website_login_db_manager_link`) :
aucun n'injecte quoi que ce soit dans `web_editor.backend_assets_wysiwyg`.
Tous ciblent exclusivement `web.assets_backend` (et `web._assets_primary_variables`
pour `web_responsive`).

**Conclusion** : aucun module custom ne contribue à ce bundle, ni directement
ni indirectement.

---

## 3. Log serveur au moment de la compilation du bundle

**Preuve** : tous les enregistrements `ir.attachment` de bundles manquants sur
disque dans la base `SEFOR` partagent le **même timestamp de création à la
microseconde près** : `2026-07-16 12:20:45.895985` (36 lignes, voir section 4).
En PostgreSQL, `now()`/`CURRENT_TIMESTAMP` renvoie une valeur figée par
transaction : ces 36 lignes ont donc été insérées en **une seule transaction**
(une régénération/pré-chauffage groupé de bundles), pas une par une au fil de
requêtes indépendantes.

Immédiatement avant (12:20:42), le log montre une erreur distincte mais
révélatrice d'un rechargement de registre en cours :
```
2026-07-16 12:20:42,826 ... ERROR SEFOR odoo.sql_db: bad query: ...
psycopg2.errors.UndefinedColumn: column res_partner.microfinance_gps_coordinates does not exist
```
(un cron a tenté de lire `res_partner` avec un schéma ORM plus récent que la
table réelle à cet instant précis — signe d'un rechargement/upgrade de module
en cours à ce moment-là).

Historique des redémarrages du 16/07 (`grep "HTTP service (werkzeug) running"`)
montre des redémarrages très fréquents ce jour-là (toutes les 10-45 min entre
10:52 et 17:27), cohérent avec un cycle de développement actif (redémarrages
manuels/`-u`) plutôt qu'un crash.

**Conclusion** : le bundle en question n'a jamais échoué à se *compiler* — son
enregistrement d'attachment a été créé avec succès en base lors d'une
opération groupée le 16/07 à 12:20:45, mais **sans que le fichier physique
correspondant ne soit jamais écrit sur disque**.

---

## 4. Attachments de bundle compilé obsolètes/corrompus

**Preuve** — comptage global (base `SEFOR`) :
```sql
select count(*) from ir_attachment where store_fname is not null;  -- 641
```
vs fichiers réellement présents sur disque : **457** fichiers dans
`/opt/odoo17/.local/share/Odoo/filestore/SEFOR`.

**36 attachments de la base SEFOR référencent un fichier absent**, tous
`res_model = 'ir.ui.view'` (bundles compilés), créés au même timestamp
`2026-07-16 12:20:45.895985` :

```
web_editor.backend_assets_wysiwyg.min.js        (id 1684)  ← celui du bug rapporté
web_editor.assets_wysiwyg.min.js                (id 1683)
web_editor.assets_legacy_wysiwyg.min.js         (id 1682)
web_editor.wysiwyg_iframe_editor_assets.min.js  (id 1686)
web_editor.mocha_tests.min.js                   (id 1685)
website.backend_assets_all_wysiwyg.min.js       (id 1688)
website.assets_all_wysiwyg_inside.min.js        (id 1687)
web.assets_web_dark.min.js / .min.css           (id 1676 / 1698)
web.assets_tests.min.js, web.tests_assets.min.js, web.qunit_*...
mail.assets_public.min.js/css, im_livechat.*, snailmail.*, spreadsheet.*...
+ res.company.scss (id 13, res_model vide, non lié aux bundles)
```

Preuve complémentaire — le dossier `filestore/SEFOR/92/` (celui qui devrait
contenir le blob `92767bfc...` de l'attachment 1684) a pour date de dernière
modification **2026-07-12 11:33:03**, soit *avant* la création de l'attachment
(2026-07-16 12:20:45). Si le fichier avait été écrit puis supprimé après coup,
le dossier aurait une mtime postérieure au 16/07. Son absence de mtime récente
prouve qu'**aucun fichier n'a jamais été déposé dans ce dossier au moment de la
création du row DB** — la ligne `ir_attachment` a été committée sans que
l'écriture disque correspondante n'ait jamais eu lieu.

**Portée au-delà de SEFOR** : le même schéma d'erreur (`FileNotFoundError` sur
un chemin `filestore/<DB>/xx/<checksum>`) apparaît aussi pour d'autres bases
hébergées sur cette même instance : `BASE`, `DATA`, `EATDAT`. Ce n'est donc pas
un incident isolé à SEFOR ni à ce bundle précis, mais un problème
d'infrastructure (stockage/filestore) touchant plusieurs bases.

**Facteur environnemental notable** : la partition racine est à **94 %
d'utilisation (5,4 Go libres sur 87 Go)**. C'est cohérent avec un échec
d'écriture silencieux côté filestore (l'écriture du blob n'est pas
transactionnelle avec l'insertion PostgreSQL dans Odoo : la ligne peut donc
être committée même si l'écriture disque du fichier a échoué ou a été sautée
par erreur par la logique de déduplication par checksum).

**Conclusion** : désynchronisation avérée entre `ir_attachment` et le
filestore physique, concentrée sur des enregistrements créés en une seule
transaction le 16/07 à 12:20:45 — tous des bundles d'assets auto-générés
(donc théoriquement régénérables sans perte de données), dans un contexte de
disque quasi plein.

---

## 5. État du module web_editor

**Preuve** :
```sql
select name, state, latest_version from ir_module_module where name='web_editor';
→ web_editor | installed | 17.0.1.0
```
`grep -rn "web_editor" --include=*.py --include=*.xml .` sur tout le dépôt
custom : aucun résultat. Aucun module custom n'hérite, ne surcharge ni ne
référence `web_editor`.

**Conclusion** : le module est sain et à jour côté registre. Le problème n'est
pas une incohérence de version/état de module.

---

## 6. Portée du problème

**Preuve** : parmi les 36 attachments SEFOR au fichier manquant figurent
`web_editor.assets_wysiwyg.min.js` (id 1683) et
`web_editor.wysiwyg_iframe_editor_assets.min.js` (id 1686), qui sont des
bundles **partagés** par d'autres points d'entrée de l'éditeur wysiwyg natif
(ex. `mail.template`, description produit, éditeur HTML de rapport) — pas
seulement par `base.document.layout`.

**Conclusion** : l'incident n'est **pas spécifique** au wizard
`base.document.layout`. Toute autre vue backend chargeant un de ces 36 bundles
touchés est exposée au même échec tant que l'attachment correspondant n'a pas
été régénéré (bundle par bundle, à la première requête qui en déclenche la
reconstruction — comme observé pour le CSS du même bundle, régénéré avec
succès juste après l'échec du JS, cf. section 1, ligne `id:2277`).

---

## Cause probable

Désynchronisation ponctuelle entre les lignes `ir_attachment` (base `SEFOR`,
et probablement d'autres bases sur la même instance) et les fichiers du
filestore, apparue lors d'une opération groupée le **2026-07-16 à 12:20:45**
(un rechargement de registre / cycle de redémarrage en contexte de
développement actif, avec un disque système presque plein — 94 % d'usage).
36 bundles d'assets auto-générés ont vu leur enregistrement DB créé sans que
le blob physique ne soit jamais écrit sur disque. `web_editor.backend_assets_wysiwyg.min.js`
n'est qu'un des 36 bundles touchés — le problème est générique aux bundles
d'assets (Odoo core), pas causé par un module custom du dépôt.

## Correctif proposé (à valider avant application)

1. **Libérer de l'espace disque** sur la partition racine (94 % utilisé) avant
   toute autre action, pour éviter que le problème ne se reproduise lors de la
   prochaine régénération.
2. **Supprimer les 36 lignes `ir_attachment` orphelines** identifiées en
   section 4 (celles dont `store_fname` ne correspond à aucun fichier sur
   disque) — ce sont uniquement des bundles compilés (`res_model='ir.ui.view'`,
   pas de documents utilisateur), régénérés automatiquement par Odoo à la
   prochaine requête qui les invoque. Alternative plus large : lancer
   Réglages > Technique > Interface > **Régénérer les assets** (action
   standard Odoo) après suppression, pour forcer une reconstruction propre de
   tous les bundles concernés.
3. Vérifier si le même diagnostic (comptage `ir_attachment` vs fichiers
   filestore réels) doit être reproduit sur les autres bases touchées (`BASE`,
   `DATA`, `EATDAT`) si elles sont encore en production.
4. Aucune modification de code (custom ou core) n'est nécessaire — le
   problème est purement un état de données/stockage.
