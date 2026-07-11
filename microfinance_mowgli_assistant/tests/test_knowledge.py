# -*- coding: utf-8 -*-
import base64
import os
import tempfile
import zipfile
from io import BytesIO
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestMowgliKnowledge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync = cls.env["mowgli.knowledge.dataset.sync"].sudo()
        cls.Article = cls.env["mowgli.knowledge.article"].sudo()
        cls.Workflow = cls.env["mowgli.knowledge.workflow"].sudo()

    def _write_dataset(self, base_dir):
        workflow_dir = os.path.join(base_dir, "workflows", "location")
        os.makedirs(workflow_dir, exist_ok=True)
        with open(os.path.join(workflow_dir, "dataset.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
workflow: location
name: Location
version: "17.0"
roles: [Location]
categories:
  - name: Bien à louer
articles:
  - id: location-001
    title: Créer un bien à louer
    category: Bien à louer
    difficulty: beginner
    roles: [Location]
    suggested: true
    priority: 10
    question: Comment créer un bien à louer ?
    answer: <p>Créer un bien à louer.</p>
    keywords: [bien, location]
    youtube:
      - url: https://youtube.com/watch?v=legacy
        title: Vidéo legacy ignorée
    links:
      - url: https://example.com/location
        title: Guide location
faq:
  - id: location-faq-001
    question: Où trouver les loyers ?
    answer: <p>Dans les factures du contrat.</p>
    keywords: [loyer]
"""
            )

    def _write_structured_dataset(self, base_dir):
        workflow_dir = os.path.join(base_dir, "location")
        os.makedirs(workflow_dir, exist_ok=True)
        with open(os.path.join(workflow_dir, "dataset.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
workflow:
  text: location
name:
  fr: Location
version: "17.0"
roles:
  - text: Location
categories:
  - name:
      fr: Bien à louer
articles:
  - id:
      text: location-structured-001
    title:
      text: Titre structuré
    category:
      fr: Bien à louer
    difficulty:
      text: beginner
    roles:
      - fr: Location
    suggested: true
    question:
      fr: Comment importer un YAML structuré ?
      en: How to import structured YAML?
    answer:
      text: <p>Réponse structurée.</p>
    keywords:
      - label: structuré
      - fr: dictionnaire
    links:
      - url:
          text: https://example.com/structured
        title:
          fr: Lien structuré
        description:
          text: Description structurée
    related_questions:
      - text: location-structured-001
"""
            )

    def _write_multiple_questions_dataset(self, base_dir):
        workflow_dir = os.path.join(base_dir, "location")
        os.makedirs(workflow_dir, exist_ok=True)
        with open(os.path.join(workflow_dir, "dataset.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
workflow: location
name: Location
roles: [location]
articles:
  - id: location-multi-001
    title: Créer un mandat de location
    category: Mandat
    roles: [location]
    suggested: true
    priority: 100
    menu: Location > Mandats > Nouveau
    model: property.mandate
    questions:
      - Comment créer un mandat de location ?
      - Créer un mandat
      - Nouveau mandat
      - Ajouter un mandat
      - Je veux créer un mandat
    keywords: [mandat, location]
    prerequisites:
      - Bien créé
      - Propriétaire vérifié
    steps:
      - Ouvrir le bien
      - Cliquer sur Mandat
    tips: Vérifier la durée du mandat.
    errors: Mandat absent ou expiré.
    see_also:
      - location-multi-002
    images:
      - manual-image-reference.png
    videos:
      - https://youtube.com/watch?v=manual
    documents:
      - mandat.pdf
    answer: <p>Réponse mandat.</p>
  - id: location-multi-002
    title: Publier un bien
    roles: [location]
    suggested: true
    priority: 20
    question: Comment publier un bien ?
    answer: <p>Réponse publication.</p>
"""
            )

    def _write_multifile_dataset(self, base_dir):
        workflow_dir = os.path.join(base_dir, "location")
        os.makedirs(workflow_dir, exist_ok=True)
        with open(os.path.join(workflow_dir, "dataset.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
workflow:
  code: location
  name: Location
  version: "1.0"
  description: Workflow Location multi-fichiers.
imports:
  - 01_workflow.yaml
  - 02_missing.yaml
  - 03_links.yaml
"""
            )
        with open(os.path.join(workflow_dir, "01_workflow.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
categories:
  - code: property
    name: Gestion des biens
articles:
  - id: location_property_create
    category: property
    title: Créer un bien à louer
    questions:
      - Comment créer un bien à louer ?
      - Ajouter une villa à louer
    answer: <p>Créer depuis Location.</p>
    suggested: true
    priority: 100
faq:
  - id: location_faq_001
    question: Pourquoi mon bien ne passe pas disponible ?
    article: location_property_create
"""
            )
        with open(os.path.join(workflow_dir, "03_links.yaml"), "w", encoding="utf-8") as stream:
            stream.write(
                """
links:
  - id: location_link_001
    article: location_property_create
    title: Ouvrir les biens
    url: /web#menu_id=1
"""
            )

    def test_01_no_default_dataset(self):
        self.env["ir.config_parameter"].sudo().set_param("microfinance_mowgli_assistant.mowgli_dataset_path", "")
        stats = self.sync.sync_datasets()
        self.assertEqual(stats["datasets"], 0)
        self.assertTrue(stats["missing_configuration"])
        self.assertEqual(stats["message"], "Veuillez configurer le chemin des datasets MOWGLI dans les paramètres.")
        self.assertFalse(self.Workflow.search([("code", "=", "location")], limit=1))

    def test_02_import_dataset_when_added_later(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()
        self.assertEqual(stats["datasets"], 1)
        self.assertEqual(stats["workflows_created"], 1)
        self.assertEqual(stats["articles_created"], 2)
        self.assertEqual(stats["links"], 1)
        self.assertEqual(stats["faq"], 1)
        self.assertTrue(self.Workflow.search([("code", "=", "location")], limit=1))
        article = self.Article.search([("external_id", "=", "location-001")], limit=1)
        self.assertTrue(article)
        self.assertFalse(article.video_ids)
        self.assertTrue(self.Article.search([("external_id", "=", "location-faq-001")], limit=1))

    def test_02b_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
                stats = self.sync.sync_datasets()
        self.assertEqual(stats["workflows_created"], 0)
        self.assertEqual(stats["workflows_updated"], 1)
        self.assertEqual(stats["articles_created"], 0)
        self.assertEqual(stats["articles_updated"], 2)

    def test_02c_import_accepts_structured_yaml_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_structured_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()
        self.assertEqual(stats["errors"], 0)
        article = self.Article.search([("external_id", "=", "location-structured-001")], limit=1)
        self.assertTrue(article)
        self.assertEqual(article.title, "Titre structuré")
        self.assertIn("Réponse structurée", article.answer)
        self.assertEqual(set(article.keyword_ids.mapped("name")), {"structuré", "dictionnaire"})
        self.assertEqual(article.link_ids.url, "https://example.com/structured")

    def test_02d_import_multiple_questions_and_search_variant(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_multiple_questions_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()
        self.assertEqual(stats["errors"], 0)
        article = self.Article.search([("external_id", "=", "location-multi-001")], limit=1)
        self.assertTrue(article)
        self.assertEqual(article.question, "Comment créer un mandat de location ?")
        self.assertEqual(len(article.question_variant_ids), 5)
        self.assertEqual(article.menu_path, "Location > Mandats > Nouveau")
        self.assertEqual(article.target_model, "property.mandate")
        self.assertFalse(article.image_ids)
        self.assertFalse(article.video_ids)
        self.assertFalse(article.document_ids)
        matched, score = self.Article.find_best_article("Je veux créer un mandat", user=self.env.user)
        self.assertEqual(matched, article)
        self.assertGreaterEqual(score, 0.45)
        self.assertEqual(article.related_question_ids.external_id, "location-multi-002")

    def test_02e_import_multifile_manifest_dataset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_multifile_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()
        self.assertEqual(stats["datasets"], 1)
        self.assertEqual(stats["yaml_files_read"], 3)
        self.assertEqual(stats["yaml_files_missing"], 1)
        self.assertEqual(stats["articles_created"], 2)
        self.assertEqual(stats["links_created"], 1)
        article = self.Article.search([("external_id", "=", "location_property_create")], limit=1)
        self.assertTrue(article)
        self.assertEqual(article.category_id.name, "Gestion des biens")
        self.assertEqual(article.link_ids.url, "/web#menu_id=1")

    def test_02f_import_decodes_html_entities_in_text_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workflow_dir = os.path.join(tmp_dir, "location")
            os.makedirs(workflow_dir, exist_ok=True)
            with open(os.path.join(workflow_dir, "dataset.yaml"), "w", encoding="utf-8") as stream:
                stream.write(
                    """
workflow: location
name: Location
articles:
  - id: location-entities-001
    title: Qu&#x27;est-ce que le workflow Location ?
    suggested: true
    priority: 100
    question: Qu&#x27;est-ce que le workflow Location ?
    answer: <p>Réponse avec é è à ù ê ô ç œ &#x27; &quot;</p>
    questions:
      - Qu&#x27;est-ce que le workflow Location ?
      - C&#x27;est quoi un mandat ?
"""
                )
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()

        self.assertEqual(stats["errors"], 0)
        article = self.Article.search([("external_id", "=", "location-entities-001")], limit=1)
        self.assertTrue(article)
        self.assertEqual(article.title, "Qu'est-ce que le workflow Location ?")
        self.assertEqual(article.question, "Qu'est-ce que le workflow Location ?")
        self.assertIn("C'est quoi un mandat ?", article.question_variant_ids.mapped("name"))
        self.assertIn("é è à ù ê ô ç œ", article.answer)
        self.assertNotIn("&#x27;", article.answer)
        self.assertNotIn("&quot;", article.answer)

    def test_03_suggested_questions_for_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_multiple_questions_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
        questions = self.Article._get_suggested_questions_for_user(self.env.user, limit=15)
        self.assertLessEqual(len(questions), 15)
        self.assertTrue(all(article.suggested for article in questions))
        self.assertEqual(questions[:1].external_id, "location-multi-001")

    def test_03b_suggested_questions_keep_utf8_without_html_entities(self):
        workflow = self.Workflow.create({
            "name": "Location",
            "code": "location-html",
        })
        questions = [
            "Qu'est-ce que le workflow Location ?",
            "C'est quoi un mandat ?",
            "Comment créer un contrat de location ?",
        ]
        stored_questions_input = [
            "Qu&#x27;est-ce que le workflow Location ?",
            "C&#x27;est quoi un mandat ?",
            "Comment créer un contrat de location ?",
        ]
        for index, question in enumerate(stored_questions_input):
            self.Article.create({
                "workflow_id": workflow.id,
                "external_id": "location-html-%s" % index,
                "title": question,
                "question": question,
                "answer": "<p>Réponse avec é è à ù ê ô ç œ ' \"</p>",
                "suggested": True,
                "priority": 100 - index,
            })

        stored_questions = self.Article.search(
            [("workflow_id", "=", workflow.id)],
            order="priority desc, id",
            limit=3,
        ).mapped("question")
        self.assertEqual(stored_questions, questions)

        body = str(self.env["mowgli.bot.assistant"].sudo()._render_suggested_questions_message(
            self.env.user,
            limit=3,
        ))

        for question in questions:
            self.assertIn(question, body)
        for entity in ("&#x27;", "&#39;", "&apos;", "&quot;", "&#34;"):
            self.assertNotIn(entity, body)
        self.assertIn("é", body)
        self.assertIn("ç", body)

        assistant = self.env["mowgli.bot.assistant"].sudo()
        assistant._ensure_mowgli_setup()
        bot_user = self.env.ref("microfinance_mowgli_assistant.user_mowgli_bot")
        channel_info = self.env["discuss.channel"].with_user(self.env.user).with_context(
            mowgli_no_reply=True,
        ).channel_get([bot_user.partner_id.id], pin=True)
        mowgli_channel = self.env["discuss.channel"].browse(channel_info["id"])
        self.assertTrue(assistant._post_mowgli_suggestions(self.env.user, channel=mowgli_channel, limit=3))

        message = self.env["mail.message"].search([
            ("model", "=", "discuss.channel"),
            ("res_id", "=", mowgli_channel.id),
            ("body", "ilike", "Questions suggérées"),
        ], order="id desc", limit=1)
        self.assertTrue(message)
        for question in questions:
            self.assertIn(question, message.body)
        for entity in ("&#x27;", "&#39;", "&apos;", "&quot;", "&#34;"):
            self.assertNotIn(entity, message.body)

    def test_04_unanswered_question_recorded_without_dataset(self):
        self.env["ir.config_parameter"].sudo().set_param("microfinance_mowgli_assistant.mowgli_dataset_path", "")
        stats = self.sync.sync_datasets()
        self.assertEqual(stats["datasets"], 0)
        self.env["ir.config_parameter"].sudo().set_param(
            "microfinance_mowgli_assistant.mowgli_min_score",
            "0.99",
        )
        reply = self.Article.render_knowledge_reply("question inconnue xyz", user=self.env.user)
        self.assertIn("pas encore de réponse", str(reply))
        unanswered = self.env["mowgli.knowledge.unanswered.question"].search([
            ("question", "=", "question inconnue xyz"),
        ], limit=1)
        self.assertTrue(unanswered)

    def test_05_media_preserved_after_sync(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
            article = self.Article.search([("external_id", "=", "location-001")], limit=1)
            image = self.env["mowgli.knowledge.image"].create({
                "article_id": article.id,
                "title": "Image manuelle",
                "image": (
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
                    "EQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
                ),
            })
            video = self.env["mowgli.knowledge.video"].create({
                "article_id": article.id,
                "title": "Vidéo manuelle",
                "youtube_url": "https://youtube.com/watch?v=manual",
            })
            document = self.env["mowgli.knowledge.document"].create({
                "article_id": article.id,
                "name": "PDF manuel",
                "filename": "manuel.pdf",
                "file": base64.b64encode(b"%PDF-1.4\n%manual\n").decode(),
            })
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
        self.assertTrue(image.exists())
        self.assertTrue(video.exists())
        self.assertTrue(document.exists())

    def test_05b_sync_preserves_manual_links_and_missing_articles_by_default(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
            article = self.Article.search([("external_id", "=", "location-001")], limit=1)
            manual_link = self.env["mowgli.knowledge.link"].create({
                "article_id": article.id,
                "title": "Lien manuel",
                "url": "https://example.com/manual",
            })
            manual_article = self.Article.create({
                "workflow_id": article.workflow_id.id,
                "external_id": "manual-existing",
                "title": "Article manuel",
                "question": "Question manuelle ?",
                "answer": "<p>Réponse manuelle.</p>",
            })
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets()
        self.assertTrue(manual_link.exists())
        self.assertTrue(manual_article.exists())
        self.assertEqual(stats["articles_deleted"], 0)
        self.assertGreaterEqual(stats["media_preserved"], 1)

    def test_05c_sync_options_can_ignore_create_or_update(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets(options={"create_new_articles": False})
            self.assertEqual(stats["articles_created"], 0)
            self.assertEqual(stats["articles_ignored"], 2)

            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()
            article = self.Article.search([("external_id", "=", "location-001")], limit=1)
            article.write({"title": "Titre conservé"})
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                stats = self.sync.sync_datasets(options={"update_existing_articles": False})
        self.assertEqual(stats["articles_updated"], 0)
        self.assertGreaterEqual(stats["articles_ignored"], 2)
        self.assertEqual(article.title, "Titre conservé")

    def test_06_import_zip_extracts_yaml_then_syncs(self):
        payload = BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(
                "location/dataset.yaml",
                """
workflow: location
name: Location
articles:
  - id: location-zip-001
    question: Question ZIP ?
    answer: <p>Réponse ZIP.</p>
""",
            )
            archive.writestr("README.md", "Datasets MOWGLI")
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.env["ir.config_parameter"].sudo().set_param(
                "microfinance_mowgli_assistant.mowgli_dataset_path",
                tmp_dir,
            )
            stats = self.sync.import_zip_and_sync(base64.b64encode(payload.getvalue()), filename="datasets.zip")
            self.assertEqual(stats["zip_files_extracted"], 2)
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "location", "dataset.yaml")))
        self.assertTrue(self.Article.search([("external_id", "=", "location-zip-001")], limit=1))

    def test_07_import_zip_rejects_path_traversal(self):
        payload = BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("../dataset.yaml", "workflow: location")
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.env["ir.config_parameter"].sudo().set_param(
                "microfinance_mowgli_assistant.mowgli_dataset_path",
                tmp_dir,
            )
            with self.assertRaises(UserError):
                self.sync.import_zip_and_sync(base64.b64encode(payload.getvalue()), filename="datasets.zip")

    def test_09_mowgli_session_prepare_clears_only_mowgli_channel(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_multiple_questions_dataset(tmp_dir)
            with patch.object(type(self.sync), "_get_knowledge_root", return_value=tmp_dir):
                self.sync.sync_datasets()

        assistant = self.env["mowgli.bot.assistant"].sudo()
        assistant._ensure_mowgli_setup()
        bot_user = self.env.ref("microfinance_mowgli_assistant.user_mowgli_bot")
        channel_info = self.env["discuss.channel"].with_user(self.env.user).with_context(
            mowgli_no_reply=True,
        ).channel_get([bot_user.partner_id.id], pin=True)
        mowgli_channel = self.env["discuss.channel"].browse(channel_info["id"])
        mowgli_channel.with_context(mowgli_no_reply=True).message_post(
            body="<p>Ancien message MOWGLI</p>",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        other_channel = self.env["discuss.channel"].create({
            "name": "Canal non MOWGLI",
            "channel_type": "channel",
        })
        other_message = other_channel.with_context(mowgli_no_reply=True).message_post(
            body="<p>Message à conserver</p>",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        unanswered = self.env["mowgli.knowledge.unanswered.question"].create({
            "question": "Question sans réponse à conserver",
            "user_id": self.env.user.id,
        })

        self.assertTrue(mowgli_channel.mowgli_prepare_session())

        mowgli_messages = self.env["mail.message"].search([
            ("model", "=", "discuss.channel"),
            ("res_id", "=", mowgli_channel.id),
        ])
        self.assertFalse(any("Ancien message MOWGLI" in (message.body or "") for message in mowgli_messages))
        self.assertTrue(any("Bonjour" in (message.body or "") for message in mowgli_messages))
        self.assertTrue(any("Questions suggérées" in (message.body or "") for message in mowgli_messages))
        self.assertTrue(other_message.exists())
        self.assertTrue(unanswered.exists())
