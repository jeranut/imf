# -*- coding: utf-8 -*-
import html
import base64
import binascii
import logging
import os
import re
import zipfile
from io import BytesIO

import odoo.modules
import yaml
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .mowgli_bot import MODULE_NAME

_logger = logging.getLogger(__name__)

KNOWLEDGE_FALLBACK_MESSAGE = (
    "<p>Je n'ai pas encore de réponse validée pour cette question. "
    "Votre demande a été enregistrée pour enrichir la base MOWGLI.</p>"
)


def clean_html_entities(value):
    return html.unescape(str(value or ""))


def html_text(value):
    return Markup(html.escape(clean_html_entities(value), quote=False))


def html_attr(value):
    return Markup(html.escape(clean_html_entities(value), quote=True))


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_html_entities(value).strip()
    if isinstance(value, dict):
        for key in ("fr", "text"):
            if key in value:
                normalized = normalize_text(value.get(key))
                if normalized:
                    return normalized
        for candidate in value.values():
            normalized = normalize_text(candidate)
            if normalized:
                return normalized
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(
            normalized
            for normalized in (normalize_text(item) for item in value)
            if normalized
        ).strip()
    return str(value).strip()


def _normalize_text(value):
    return " ".join(re.findall(r"[\wÀ-ÿ']+", normalize_text(value).lower()))


def _tokenize(value):
    return set(re.findall(r"[\wÀ-ÿ']+", normalize_text(value).lower()))


class MowgliKnowledgeWorkflow(models.Model):
    _name = "mowgli.knowledge.workflow"
    _description = "Workflow métier MOWGLI"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    group_ids = fields.Many2many(
        "res.groups",
        "mowgli_knowledge_workflow_group_rel",
        "workflow_id",
        "group_id",
        string="Groupes autorisés",
    )

    _sql_constraints = [
        ("code_unique", "unique(code)", "Le code du workflow doit être unique."),
    ]


class MowgliKnowledgeCategory(models.Model):
    _name = "mowgli.knowledge.category"
    _description = "Catégorie MOWGLI"
    _order = "workflow_id, sequence, name"

    name = fields.Char(required=True, translate=True)
    workflow_id = fields.Many2one(
        "mowgli.knowledge.workflow",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "workflow_name_unique",
            "unique(workflow_id, name)",
            "La catégorie existe déjà dans ce workflow.",
        ),
    ]


class MowgliKnowledgeArticle(models.Model):
    _name = "mowgli.knowledge.article"
    _description = "Article MOWGLI"
    _order = "workflow_id, priority desc, sequence, title, id"
    _html_entity_text_fields = {
        "external_id",
        "title",
        "question",
        "answer",
        "guide_anchor",
        "source_reference",
        "menu_path",
        "target_model",
        "prerequisites",
        "steps",
        "tips",
        "errors",
    }

    DIFFICULTY_SELECTION = [
        ("beginner", "Débutant"),
        ("intermediate", "Intermédiaire"),
        ("advanced", "Avancé"),
    ]

    workflow_id = fields.Many2one(
        "mowgli.knowledge.workflow",
        required=True,
        ondelete="restrict",
    )
    external_id = fields.Char(required=True, index=True)
    title = fields.Char(required=True, translate=True)
    question = fields.Text(required=True, translate=True)
    answer = fields.Html(required=True, translate=True)
    category_id = fields.Many2one(
        "mowgli.knowledge.category",
        ondelete="set null",
    )
    difficulty = fields.Selection(DIFFICULTY_SELECTION, default="beginner")
    priority = fields.Integer(default=10)
    sequence = fields.Integer(default=10)
    suggested = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    version = fields.Char(default="17.0")
    guide_anchor = fields.Char()
    source_reference = fields.Char()
    menu_path = fields.Char(string="Menu Odoo")
    target_model = fields.Char(string="Modèle cible")
    prerequisites = fields.Text(translate=True)
    steps = fields.Text(translate=True)
    tips = fields.Text(translate=True)
    errors = fields.Text(translate=True)
    group_ids = fields.Many2many(
        "res.groups",
        "mowgli_knowledge_article_group_rel",
        "article_id",
        "group_id",
        string="Groupes autorisés",
    )
    keyword_ids = fields.One2many(
        "mowgli.knowledge.keyword",
        "article_id",
        string="Mots-clés",
    )
    question_variant_ids = fields.One2many(
        "mowgli.knowledge.question",
        "article_id",
        string="Formulations",
    )
    image_ids = fields.One2many(
        "mowgli.knowledge.image",
        "article_id",
        string="Images",
    )
    video_ids = fields.One2many(
        "mowgli.knowledge.video",
        "article_id",
        string="Vidéos YouTube",
    )
    document_ids = fields.One2many(
        "mowgli.knowledge.document",
        "article_id",
        string="Documents PDF",
    )
    link_ids = fields.One2many(
        "mowgli.knowledge.link",
        "article_id",
        string="Liens",
    )
    related_question_ids = fields.Many2many(
        "mowgli.knowledge.article",
        "mowgli_knowledge_article_related_rel",
        "article_id",
        "related_id",
        string="Questions similaires",
    )

    _sql_constraints = [
        (
            "workflow_external_id_unique",
            "unique(workflow_id, external_id)",
            "L'identifiant article existe déjà dans ce workflow.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._decode_html_entity_vals(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        return super().write(self._decode_html_entity_vals(vals))

    @api.model
    def _decode_html_entity_vals(self, vals):
        clean_vals = dict(vals)
        for field_name in self._html_entity_text_fields:
            value = clean_vals.get(field_name)
            if isinstance(value, str):
                clean_vals[field_name] = clean_html_entities(value)
        return clean_vals

    @api.constrains("category_id", "workflow_id")
    def _check_category_workflow(self):
        for article in self:
            if article.category_id and article.category_id.workflow_id != article.workflow_id:
                raise ValidationError(_("La catégorie doit appartenir au même workflow."))

    @api.model
    def _get_user_groups(self, user=None):
        user = user or self.env.user
        return user.sudo().groups_id

    @api.model
    def _is_admin_user(self, user=None):
        user = user or self.env.user
        return user.has_group("base.group_system") or user.has_group(
            "%s.group_mowgli_admin" % MODULE_NAME
        )

    @api.model
    def _article_visible_for_user(self, article, user=None):
        user = user or self.env.user
        if self._is_admin_user(user):
            return True
        user_groups = self._get_user_groups(user)
        workflow_groups = article.workflow_id.group_ids
        article_groups = article.group_ids
        if workflow_groups and not (workflow_groups & user_groups):
            return False
        if article_groups and not (article_groups & user_groups):
            return False
        return True

    @api.model
    def _visible_domain_for_user(self, user=None):
        user = user or self.env.user
        if self._is_admin_user(user):
            return [("active", "=", True), ("workflow_id.active", "=", True)]
        group_ids = self._get_user_groups(user).ids
        return [
            ("active", "=", True),
            ("workflow_id.active", "=", True),
            "|",
            ("workflow_id.group_ids", "=", False),
            ("workflow_id.group_ids", "in", group_ids),
            "|",
            ("group_ids", "=", False),
            ("group_ids", "in", group_ids),
        ]

    @api.model
    def _get_suggested_questions_for_user(self, user, limit=15):
        articles = self.sudo().search(
            self._visible_domain_for_user(user) + [("suggested", "=", True)],
            order="priority desc, sequence, id",
            limit=limit,
        )
        return articles.filtered(lambda article: self._article_visible_for_user(article, user))

    @api.model
    def _score_article(self, article, question, user=None):
        normalized_question = _normalize_text(question)
        question_tokens = _tokenize(question)
        if not normalized_question or not question_tokens:
            return 0.0

        score = 0.0
        question_values = article._get_search_questions()
        article_question = _normalize_text(" ".join(question_values))
        article_title = _normalize_text(article.title)
        article_answer = _normalize_text(re.sub(r"<[^>]+>", " ", article.answer or ""))
        category_name = _normalize_text(article.category_id.name)
        workflow_name = _normalize_text(article.workflow_id.name)
        keyword_values = [_normalize_text(keyword.name) for keyword in article.keyword_ids]

        for question_value in question_values:
            variant = _normalize_text(question_value)
            if variant and variant == normalized_question:
                score += 0.55
                break
            if variant and (variant in normalized_question or normalized_question in variant):
                score += 0.40
                break
        if article_question and article_question in normalized_question:
            score += 0.40
        if article_title and article_title in normalized_question:
            score += 0.20
        if workflow_name and workflow_name in normalized_question:
            score += 0.08
        if category_name and category_name in normalized_question:
            score += 0.08

        for keyword in keyword_values:
            if not keyword:
                continue
            keyword_tokens = _tokenize(keyword)
            if keyword in normalized_question:
                score += 0.18
            elif keyword_tokens and keyword_tokens.issubset(question_tokens):
                score += 0.12

        indexed_tokens = _tokenize(" ".join([
            article_question,
            article_title,
            article_answer,
            category_name,
            workflow_name,
            " ".join(keyword_values),
        ]))
        if indexed_tokens:
            overlap = len(question_tokens & indexed_tokens) / max(len(question_tokens), 1)
            score += min(overlap, 1.0) * 0.35

        if user and article.group_ids and article.group_ids & self._get_user_groups(user):
            score += 0.06
        if user and article.workflow_id.group_ids and article.workflow_id.group_ids & self._get_user_groups(user):
            score += 0.04

        return min(score, 1.0)

    def _get_search_questions(self):
        self.ensure_one()
        questions = [self.question]
        questions += self.question_variant_ids.sorted("sequence").mapped("name")
        clean_questions = []
        for question in questions:
            question = normalize_text(question)
            if question and question not in clean_questions:
                clean_questions.append(question)
        return clean_questions

    @api.model
    def _get_min_score(self):
        value = self.env["ir.config_parameter"].sudo().get_param("microfinance_mowgli_assistant.mowgli_min_score", "0.45")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.45

    @api.model
    def find_best_article(self, question, user=None):
        candidates = self.sudo().search(self._visible_domain_for_user(user))
        best_article = self.browse()
        best_score = 0.0
        for article in candidates:
            if not self._article_visible_for_user(article, user):
                continue
            score = self._score_article(article, question, user=user)
            if score > best_score:
                best_article = article
                best_score = score
        if best_score < self._get_min_score():
            return self.browse(), best_score
        return best_article, best_score

    @api.model
    def render_knowledge_reply(self, question, user=None):
        article, score = self.find_best_article(question, user=user)
        if not article:
            self.env["mowgli.knowledge.unanswered.question"].sudo().record_unanswered(
                question,
                user=user,
                best_score=score,
            )
            return Markup(KNOWLEDGE_FALLBACK_MESSAGE)
        return article._render_mowgli_reply()

    def _render_mowgli_reply(self):
        self.ensure_one()
        content = Markup(self.answer or "")

        for image in self.image_ids.filtered("active").sorted("sequence"):
            content += Markup(
                '<div style="margin-top: 12px;">'
                '<img src="/web/image/mowgli.knowledge.image/%s/image" '
                'style="max-width: 100%%; height: auto; border-radius: 6px;"/>'
            ) % image.id
            if image.caption:
                content += Markup('<p><em>%s</em></p>') % html_text(image.caption)
            content += Markup("</div>")

        videos = self.video_ids.filtered("active").sorted("sequence")
        if videos:
            content += Markup("<p><strong>Vidéos YouTube</strong></p><ul>")
            for video in videos:
                content += Markup('<li><a href="%s" target="_blank">%s</a></li>') % (
                    html_attr(video.youtube_url),
                    html_text(video.title or video.youtube_url),
                )
            content += Markup("</ul>")

        documents = self.document_ids.filtered("active").sorted("sequence")
        if documents:
            content += Markup("<p><strong>Documents PDF</strong></p><ul>")
            for document in documents:
                content += Markup(
                    '<li><a href="/web/content/mowgli.knowledge.document/%s/file?download=1" target="_blank">%s</a></li>'
                ) % (document.id, html_text(document.name or document.filename or _("Document PDF")))
            content += Markup("</ul>")

        links = self.link_ids.filtered("active").sorted("sequence")
        if links:
            content += Markup("<p><strong>Liens utiles</strong></p><ul>")
            for link in links:
                content += Markup('<li><a href="%s" target="_blank">%s</a></li>') % (
                    html_attr(link.url),
                    html_text(link.title or link.url),
                )
            content += Markup("</ul>")

        for label, value in [
            (_("Menu Odoo"), self.menu_path),
            (_("Modèle cible"), self.target_model),
        ]:
            if value:
                content += Markup("<p><strong>%s</strong> : %s</p>") % (
                    html_text(label),
                    html_text(value),
                )

        for label, value in [
            (_("Prérequis"), self.prerequisites),
            (_("Étapes"), self.steps),
            (_("Conseils"), self.tips),
            (_("Erreurs fréquentes"), self.errors),
        ]:
            if value:
                formatted_value = html_text(value).replace("\n", Markup("<br/>"))
                content += Markup("<p><strong>%s</strong></p><p>%s</p>") % (
                    html_text(label),
                    formatted_value,
                )

        related = self.related_question_ids.filtered("active")[:5]
        if related:
            content += Markup("<p><strong>Voir aussi</strong></p><ul>")
            for article in related:
                content += Markup("<li>%s</li>") % html_text(article.question or article.title)
            content += Markup("</ul>")

        if self.guide_anchor:
            content += Markup(
                '<p><a href="#%s">Voir le guide associé</a></p>'
            ) % html_attr(self.guide_anchor)
        return content


class MowgliKnowledgeQuestion(models.Model):
    _name = "mowgli.knowledge.question"
    _description = "Formulation de question MOWGLI"
    _order = "article_id, sequence, id"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(required=True, index=True, translate=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        (
            "article_name_unique",
            "unique(article_id, name)",
            "Cette formulation existe déjà pour cet article.",
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._decode_html_entity_vals(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        return super().write(self._decode_html_entity_vals(vals))

    @api.model
    def _decode_html_entity_vals(self, vals):
        clean_vals = dict(vals)
        value = clean_vals.get("name")
        if isinstance(value, str):
            clean_vals["name"] = clean_html_entities(value)
        return clean_vals


class MowgliKnowledgeKeyword(models.Model):
    _name = "mowgli.knowledge.keyword"
    _description = "Mot-clé MOWGLI"
    _order = "article_id, name"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(required=True, index=True)

    _sql_constraints = [
        ("article_name_unique", "unique(article_id, name)", "Le mot-clé existe déjà pour cet article."),
    ]


class MowgliKnowledgeImage(models.Model):
    _name = "mowgli.knowledge.image"
    _description = "Image MOWGLI"
    _order = "article_id, sequence, id"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    image = fields.Image(required=True, max_width=1920, max_height=1080)
    title = fields.Char(required=True)
    caption = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class MowgliKnowledgeVideo(models.Model):
    _name = "mowgli.knowledge.video"
    _description = "Vidéo YouTube MOWGLI"
    _order = "article_id, sequence, id"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    title = fields.Char(required=True)
    youtube_url = fields.Char(required=True)
    duration = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("article_url_unique", "unique(article_id, youtube_url)", "Cette vidéo existe déjà pour l'article."),
    ]


class MowgliKnowledgeDocument(models.Model):
    _name = "mowgli.knowledge.document"
    _description = "Document PDF MOWGLI"
    _order = "article_id, sequence, id"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(required=True)
    file = fields.Binary(required=True, attachment=True)
    filename = fields.Char()
    description = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class MowgliKnowledgeLink(models.Model):
    _name = "mowgli.knowledge.link"
    _description = "Lien MOWGLI"
    _order = "article_id, sequence, id"

    article_id = fields.Many2one(
        "mowgli.knowledge.article",
        required=True,
        ondelete="cascade",
    )
    title = fields.Char(required=True)
    url = fields.Char(required=True)
    description = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("article_url_unique", "unique(article_id, url)", "Ce lien existe déjà pour l'article."),
    ]


class MowgliKnowledgeUnansweredQuestion(models.Model):
    _name = "mowgli.knowledge.unanswered.question"
    _description = "Question MOWGLI sans réponse"
    _order = "create_date desc, id desc"

    STATUS_SELECTION = [
        ("new", "Nouvelle"),
        ("in_review", "En analyse"),
        ("done", "Traitée"),
        ("ignored", "Ignorée"),
    ]

    question = fields.Text(required=True)
    user_id = fields.Many2one("res.users", ondelete="set null")
    user_role = fields.Char()
    workflow_suggested = fields.Char()
    best_score = fields.Float()
    status = fields.Selection(STATUS_SELECTION, default="new", required=True)
    note = fields.Text()
    created_article_id = fields.Many2one(
        "mowgli.knowledge.article",
        string="Article créé",
        ondelete="set null",
    )
    linked_article_id = fields.Many2one(
        "mowgli.knowledge.article",
        string="Article lié",
        ondelete="set null",
    )

    @api.model
    def record_unanswered(self, question, user=None, best_score=0.0, workflow_suggested=False):
        question = normalize_text(question)
        if not question:
            return self.browse()
        user = user or self.env.user
        existing = self.search([
            ("question", "=", question),
            ("user_id", "=", user.id),
            ("status", "in", ["new", "in_review"]),
        ], limit=1)
        vals = {
            "question": question,
            "user_id": user.id,
            "user_role": ", ".join(user.groups_id.mapped("name")[:8]),
            "workflow_suggested": workflow_suggested or False,
            "best_score": best_score,
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    def action_mark_in_review(self):
        self.write({"status": "in_review"})

    def action_mark_done(self):
        self.write({"status": "done"})

    def action_mark_ignored(self):
        self.write({"status": "ignored"})

    def action_create_article(self):
        self.ensure_one()
        workflow = self.env["mowgli.knowledge.workflow"].search([("active", "=", True)], order="sequence, id", limit=1)
        action = self.env.ref("%s.action_mowgli_knowledge_articles" % MODULE_NAME).read()[0]
        action["views"] = [(False, "form")]
        action["context"] = {
            "default_workflow_id": workflow.id,
            "default_external_id": "manual-%s" % self.id,
            "default_title": self.question[:80],
            "default_question": self.question,
            "default_answer": "<p></p>",
            "default_suggested": False,
        }
        return action

    def action_link_existing_article(self):
        for rec in self:
            if rec.linked_article_id:
                rec.status = "done"


class MowgliKnowledgeSyncWizard(models.TransientModel):
    _name = "mowgli.knowledge.sync.wizard"
    _description = "Synchronisation datasets MOWGLI"

    zip_file = fields.Binary(string="ZIP de datasets")
    zip_filename = fields.Char(string="Nom du fichier ZIP")
    create_new_articles = fields.Boolean(
        string="Créer les nouveaux articles",
        default=True,
    )
    update_existing_articles = fields.Boolean(
        string="Mettre à jour les articles existants",
        default=True,
    )
    delete_missing_articles = fields.Boolean(
        string="Supprimer les articles absents du dataset",
        default=False,
    )
    reimport_media = fields.Boolean(
        string="Réimporter les médias",
        default=False,
    )

    def action_sync_datasets(self):
        self.ensure_one()
        result = self.env["mowgli.knowledge.dataset.sync"].sync_datasets(
            options=self._get_sync_options()
        )
        dev_stats = self.env["mowgli.dev.status.item"].sudo().sync_from_docs_dev()
        message = result.get("message")
        if dev_stats.get("files_read"):
            message = (message or "") + _(
                "\n\n✓ Statuts dev synchronisés (docs_dev) : %(files_read)s fichier(s) lu(s), "
                "%(items_created)s créé(s), %(items_updated)s mis à jour, %(errors)s erreur(s)."
            ) % dev_stats
        if result.get("missing_configuration"):
            notification_type = "warning"
        elif not result.get("datasets"):
            notification_type = "info"
        else:
            notification_type = "warning" if result.get("errors") else "success"
        return self._display_sync_notification(message, notification_type)

    def action_import_zip(self):
        self.ensure_one()
        result = self.env["mowgli.knowledge.dataset.sync"].import_zip_and_sync(
            self.zip_file,
            filename=self.zip_filename,
            options=self._get_sync_options(),
        )
        notification_type = "warning" if result.get("errors") else "success"
        return self._display_sync_notification(result.get("message"), notification_type)

    def _get_sync_options(self):
        self.ensure_one()
        return {
            "create_new_articles": self.create_new_articles,
            "update_existing_articles": self.update_existing_articles,
            "delete_missing_articles": self.delete_missing_articles,
            "reimport_media": self.reimport_media,
        }

    def _display_sync_notification(self, message, notification_type):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("MOWGLI"),
                "message": message,
                "type": notification_type,
                "sticky": False,
            },
        }


class MowgliKnowledgeDatasetSync(models.AbstractModel):
    _name = "mowgli.knowledge.dataset.sync"
    _description = "Import datasets MOWGLI"

    WORKFLOW_LABELS = {
        "creation_produit_credit": "Création produit de crédit",
        "creation_produit_epargne": "Création produit d'épargne",
        "garanties_scoring": "Garanties et scoring",
        "reechelonnement": "Rééchelonnement",
        "dossier_precredit": "Dossier précrédit",
        "comptabilite": "Comptabilité",
        "par_reporting": "PAR et reporting",
        "administration": "Administration",
    }

    # MOWGLI n'a aucune dépendance dure sur les modules microfinance : les groupes de rôles
    # référencés ici sont ceux créés par ce module lui-même (voir MowgliBotAssistant._ensure_groups),
    # jamais un xmlid d'un module microfinance_* externe.
    ROLE_GROUP_XMLIDS = {
        "agent_credit": ["microfinance_mowgli_assistant.group_mowgli_agent_credit"],
        "agent_epargne": ["microfinance_mowgli_assistant.group_mowgli_agent_epargne"],
        "caissier": ["microfinance_mowgli_assistant.group_mowgli_caissier"],
        "comptable": ["microfinance_mowgli_assistant.group_mowgli_comptable"],
        "credit_committee": ["microfinance_mowgli_assistant.group_mowgli_credit_committee"],
        "gestionnaire": ["microfinance_mowgli_assistant.group_mowgli_gestionnaire"],
        "admin": ["microfinance_mowgli_assistant.group_mowgli_admin"],
    }

    def sync_datasets(self, options=None):
        options = self._normalize_sync_options(options)
        root = self._get_knowledge_root()
        stats = self._empty_stats()
        related_queue = []
        seen_articles = self.env["mowgli.knowledge.article"].sudo().browse()
        if not root:
            stats["missing_configuration"] = True
            stats["message"] = _("Veuillez configurer le chemin des datasets MOWGLI dans les paramètres.")
            return stats
        if not os.path.isdir(root):
            stats["message"] = _("Aucun dataset trouvé.")
            return stats

        for dataset_path in self._iter_dataset_paths(root):
            try:
                dataset = self._load_dataset_bundle(dataset_path, stats, root)
                stats["datasets"] += 1
                seen_articles |= self._import_dataset(
                    dataset,
                    stats,
                    related_queue,
                    options=options,
                    source_path=dataset_path,
                )
            except Exception as exc:
                stats["errors"] += 1
                stats["error_details"].append("%s: %s" % (dataset_path, exc))
                _logger.exception("Unable to import MOWGLI dataset %s", dataset_path)
        self._sync_related_questions(related_queue)
        self._sync_missing_articles(seen_articles, stats, options)
        self._update_preserved_counters(stats, options)
        stats["message"] = self._format_sync_report(stats)
        return stats

    def _empty_stats(self):
        return {
            "datasets": 0,
            "workflows_created": 0,
            "workflows_updated": 0,
            "categories_created": 0,
            "categories_updated": 0,
            "articles_created": 0,
            "articles_updated": 0,
            "articles_ignored": 0,
            "articles_deleted": 0,
            "media_preserved": 0,
            "media_imported": 0,
            "faq_created": 0,
            "faq_updated": 0,
            "yaml_files_read": 0,
            "yaml_files_missing": 0,
            "links_created": 0,
            "links_updated": 0,
            "unanswered_preserved": 0,
            "links": 0,
            "faq": 0,
            "keywords": 0,
            "errors": 0,
            "error_details": [],
            "missing_configuration": False,
            "zip_files_extracted": 0,
            "message": "",
        }

    def _normalize_sync_options(self, options=None):
        defaults = {
            "create_new_articles": True,
            "update_existing_articles": True,
            "delete_missing_articles": False,
            "reimport_media": False,
        }
        if options:
            defaults.update(options)
        return defaults

    def _get_knowledge_root(self):
        path = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("microfinance_mowgli_assistant.mowgli_dataset_path", "")
        )
        path = normalize_text(path)
        if path:
            return os.path.expandvars(os.path.expanduser(path))
        # Aucun chemin externe configuré (personne n'a encore ouvert/enregistré
        # Paramètres > MOWGLI) : repli sur le dossier datasets/ embarqué dans le
        # module lui-même, portable sans configuration sur n'importe quel OS.
        return odoo.modules.get_module_resource(MODULE_NAME, "datasets") or ""

    def _iter_dataset_paths(self, root):
        dataset_paths = []
        for current_root, _dirnames, filenames in os.walk(root):
            if "dataset.yaml" in filenames:
                dataset_paths.append(os.path.join(current_root, "dataset.yaml"))
            if "dataset.yml" in filenames:
                dataset_paths.append(os.path.join(current_root, "dataset.yml"))
        return sorted(dataset_paths)

    def _load_dataset_bundle(self, dataset_path, stats, root):
        dataset = self._read_yaml_dataset_file(dataset_path, stats)
        imports = dataset.get("imports") or []
        if not imports:
            return dataset

        workflow_data = dataset.get("workflow") or {}
        merged = {
            "workflow": workflow_data,
            "name": dataset.get("name"),
            "version": dataset.get("version"),
            "description": dataset.get("description"),
            "sequence": dataset.get("sequence"),
            "roles": dataset.get("roles") or dataset.get("groups") or [],
            "categories": list(dataset.get("categories") or []),
            "articles": list(dataset.get("articles") or []),
            "faq": list(dataset.get("faq") or []),
            "links": list(dataset.get("links") or dataset.get("liens") or []),
        }
        workflow_dir = os.path.dirname(dataset_path)
        if isinstance(imports, (str, dict)):
            imports = [imports]
        for import_name in imports:
            import_name = normalize_text(import_name)
            if not import_name:
                continue
            import_path = self._validate_import_path(import_name, workflow_dir, root)
            if not import_path:
                stats["yaml_files_missing"] += 1
                stats["errors"] += 1
                relative = os.path.relpath(os.path.join(workflow_dir, import_name), root)
                stats["error_details"].append(_("Fichier import introuvable : %s") % relative)
                continue
            imported = self._read_yaml_dataset_file(import_path, stats)
            for key in ("categories", "articles", "faq"):
                merged[key].extend(imported.get(key) or [])
            merged["links"].extend(imported.get("links") or imported.get("liens") or [])
        return merged

    def _read_yaml_dataset_file(self, path, stats):
        with open(path, "r", encoding="utf-8") as stream:
            stats["yaml_files_read"] += 1
            return yaml.safe_load(stream) or {}

    def _validate_import_path(self, import_name, workflow_dir, root):
        normalized = os.path.normpath(import_name)
        if (
            "\\" in import_name
            or re.match(r"^[A-Za-z]:", import_name)
            or os.path.isabs(import_name)
            or any(part == os.pardir for part in import_name.split("/"))
            or normalized == os.pardir
            or normalized.startswith(os.pardir + os.sep)
            or any(part == os.pardir for part in normalized.split(os.sep))
            or not normalized.lower().endswith((".yaml", ".yml"))
        ):
            raise UserError(_("Chemin import interdit : %s") % import_name)
        target_path = os.path.abspath(os.path.join(workflow_dir, normalized))
        workflow_dir = os.path.abspath(workflow_dir)
        root = os.path.abspath(root)
        if os.path.commonpath([workflow_dir, target_path]) != workflow_dir:
            raise UserError(_("Import hors du dossier workflow refusé : %s") % import_name)
        if os.path.commonpath([root, target_path]) != root:
            raise UserError(_("Import hors du dossier configuré refusé : %s") % import_name)
        return target_path if os.path.exists(target_path) else False

    def import_zip_and_sync(self, zip_content, filename=False, options=None):
        root = self._get_knowledge_root()
        if not root:
            raise UserError(_("Veuillez configurer le chemin des datasets MOWGLI dans les paramètres."))
        if not zip_content:
            raise UserError(_("Veuillez sélectionner un fichier ZIP de datasets."))
        if filename and not filename.lower().endswith(".zip"):
            raise UserError(_("Le fichier importé doit être un fichier .zip."))

        root = os.path.abspath(root)
        os.makedirs(root, exist_ok=True)
        extracted_count = self._extract_dataset_zip(zip_content, root)
        stats = self.sync_datasets(options=options)
        stats["zip_files_extracted"] = extracted_count
        prefix = _("ZIP importé : %(count)s fichier(s) extrait(s).\n\n") % {"count": extracted_count}
        stats["message"] = prefix + (stats.get("message") or "")
        return stats

    def _extract_dataset_zip(self, zip_content, root):
        try:
            payload = base64.b64decode(zip_content)
        except (TypeError, binascii.Error) as exc:
            raise UserError(_("Le fichier ZIP est invalide.")) from exc

        allowed_extensions = (".yaml", ".yml")
        extracted_count = 0
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        self._validate_zip_member_path(member.filename, root)
                        continue
                    target_path = self._validate_zip_member_path(member.filename, root)
                    basename = os.path.basename(member.filename)
                    lower_name = basename.lower()
                    if lower_name != "readme.md" and not lower_name.endswith(allowed_extensions):
                        raise UserError(
                            _("Le ZIP ne peut contenir que des fichiers .yaml, .yml ou README.md : %s")
                            % member.filename
                        )
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with archive.open(member, "r") as source, open(target_path, "wb") as target:
                        target.write(source.read())
                    extracted_count += 1
        except zipfile.BadZipFile as exc:
            raise UserError(_("Le fichier ZIP est invalide.")) from exc
        return extracted_count

    def _validate_zip_member_path(self, member_name, root):
        normalized = os.path.normpath(member_name)
        if (
            not member_name
            or "\\" in member_name
            or re.match(r"^[A-Za-z]:", member_name)
            or os.path.isabs(member_name)
            or any(part == os.pardir for part in member_name.split("/"))
            or normalized == os.pardir
            or normalized.startswith(os.pardir + os.sep)
            or any(part == os.pardir for part in normalized.split(os.sep))
        ):
            raise UserError(_("Chemin interdit dans le ZIP : %s") % member_name)
        target_path = os.path.abspath(os.path.join(root, normalized))
        if os.path.commonpath([root, target_path]) != root:
            raise UserError(_("Extraction hors du dossier configuré refusée : %s") % member_name)
        return target_path

    def _import_dataset(self, dataset, stats, related_queue, options=None, source_path=False):
        options = self._normalize_sync_options(options)
        seen_articles = self.env["mowgli.knowledge.article"].sudo().browse()
        workflow_values = self._workflow_values_from_dataset(dataset)
        workflow_code = normalize_text(workflow_values.get("code")).lower()
        if not workflow_code:
            raise UserError(_("Dataset sans workflow : %s") % (source_path or ""))

        workflow, created = self._upsert_workflow(
            workflow_code,
            workflow_values.get("name"),
            workflow_values.get("description"),
            workflow_values.get("sequence"),
            workflow_values.get("roles") or workflow_values.get("groups") or [],
        )
        stats["workflows_created" if created else "workflows_updated"] += 1
        version = normalize_text(workflow_values.get("version")) or "17.0"

        categories_by_name = {}
        categories_by_code = {}
        for category_values in dataset.get("categories", []) or []:
            category, created = self._upsert_category(workflow, category_values)
            categories_by_name[category.name] = category
            if isinstance(category_values, dict):
                code = normalize_text(category_values.get("code"))
                if code:
                    categories_by_code[code] = category
            stats["categories_created" if created else "categories_updated"] += 1

        for article_values in self._iter_article_values(dataset):
            is_faq = bool(article_values.pop("_mowgli_is_faq", False))
            category_name = normalize_text(article_values.get("category"))
            if category_name and category_name in categories_by_code:
                categories_by_name[category_name] = categories_by_code[category_name]
            if category_name and category_name not in categories_by_name:
                category, created = self._upsert_category(workflow, {"name": category_name})
                categories_by_name[category.name] = category
                stats["categories_created" if created else "categories_updated"] += 1
            article, created, skipped = self._upsert_article(
                workflow,
                version,
                article_values,
                categories_by_name,
                options=options,
            )
            if skipped:
                if article:
                    seen_articles |= article
                stats["articles_ignored"] += 1
                continue
            seen_articles |= article
            stats["articles_created" if created else "articles_updated"] += 1
            if is_faq:
                stats["faq"] += 1
                stats["faq_created" if created else "faq_updated"] += 1
            stats["media_preserved"] += len(article.image_ids) + len(article.video_ids) + len(article.document_ids)
            stats["media_imported"] += self._sync_media(article, article_values, options)
            self._sync_questions(article, self._question_values_from_article_values(article_values))
            stats["keywords"] += self._sync_keywords(article, article_values.get("keywords") or [])
            stats["links"] += self._sync_links(article, article_values.get("links") or article_values.get("liens") or [], stats=stats)
            related_queue.append((article, article_values.get("see_also") or article_values.get("related_questions") or []))
        stats["links"] += self._sync_dataset_links(workflow, dataset.get("links") or dataset.get("liens") or [], stats=stats)
        return seen_articles

    def _workflow_values_from_dataset(self, dataset):
        workflow = dataset.get("workflow")
        if isinstance(workflow, dict):
            return {
                "code": workflow.get("code") or workflow.get("text"),
                "name": workflow.get("name") or dataset.get("name"),
                "version": workflow.get("version") or dataset.get("version"),
                "description": workflow.get("description") or dataset.get("description"),
                "sequence": workflow.get("sequence") or dataset.get("sequence"),
                "roles": workflow.get("roles") or workflow.get("groups") or dataset.get("roles") or dataset.get("groups") or [],
            }
        return {
            "code": workflow,
            "name": dataset.get("name"),
            "version": dataset.get("version"),
            "description": dataset.get("description"),
            "sequence": dataset.get("sequence"),
            "roles": dataset.get("roles") or dataset.get("groups") or [],
        }

    def _iter_article_values(self, dataset):
        for article_values in dataset.get("articles", []) or []:
            yield dict(article_values or {})
        for index, faq_values in enumerate(dataset.get("faq", []) or [], start=1):
            values = dict(faq_values or {})
            values["_mowgli_is_faq"] = True
            values.setdefault("id", normalize_text(values.get("external_id")) or "faq-%03d" % index)
            values.setdefault("title", normalize_text(values.get("question") or values.get("questions")) or values["id"])
            yield values

    def _upsert_workflow(self, code, name=False, description=False, sequence=False, roles=None):
        Workflow = self.env["mowgli.knowledge.workflow"].sudo()
        workflow = Workflow.search([("code", "=", code)], limit=1)
        created = not bool(workflow)
        workflow_name = normalize_text(name) or self.WORKFLOW_LABELS.get(code, code.title())
        vals = {
            "name": workflow_name,
            "code": code,
            "description": normalize_text(description),
            "active": True,
            "sequence": sequence or self._default_workflow_sequence(code),
            "group_ids": [(6, 0, self._groups_from_roles(roles or []).ids)],
        }
        if workflow:
            workflow.write(vals)
        else:
            workflow = Workflow.create(vals)
        return workflow, created

    def _default_workflow_sequence(self, code):
        keys = list(self.WORKFLOW_LABELS)
        return (keys.index(code) + 1) * 10 if code in keys else 999

    def _upsert_category(self, workflow, values):
        Category = self.env["mowgli.knowledge.category"].sudo()
        if isinstance(values, str):
            values = {"name": values}
        name = normalize_text(values.get("name"))
        if not name:
            raise UserError(_("Catégorie sans nom dans %s.") % workflow.name)
        category = Category.search([
            ("workflow_id", "=", workflow.id),
            ("name", "=", name),
        ], limit=1)
        created = not bool(category)
        vals = {
            "workflow_id": workflow.id,
            "name": name,
            "sequence": values.get("sequence") or 10,
            "active": values.get("active", True),
        }
        if category:
            category.write(vals)
        else:
            category = Category.create(vals)
        return category, created

    def _upsert_article(self, workflow, version, values, categories_by_name, options=None):
        options = self._normalize_sync_options(options)
        Article = self.env["mowgli.knowledge.article"].sudo()
        external_id = normalize_text(values.get("external_id") or values.get("id"))
        if not external_id:
            raise UserError(_("Article sans id dans %s.") % workflow.name)
        category = False
        category_name = normalize_text(values.get("category"))
        if category_name:
            category = categories_by_name.get(category_name)
            if not category:
                category, _created = self._upsert_category(workflow, {"name": category_name})
                categories_by_name[category_name] = category
        article = Article.search([
            ("workflow_id", "=", workflow.id),
            ("external_id", "=", external_id),
        ], limit=1)
        created = not bool(article)
        if created and not options["create_new_articles"]:
            return Article.browse(), False, True
        if article and not options["update_existing_articles"]:
            return article, False, True
        questions = self._question_values_from_article_values(values)
        title = normalize_text(values.get("title")) or (questions[0] if questions else external_id)
        question = questions[0] if questions else title
        vals = {
            "workflow_id": workflow.id,
            "external_id": external_id,
            "title": title,
            "question": question,
            "answer": normalize_text(values.get("answer")) or "<p></p>",
            "category_id": category.id if category else False,
            "difficulty": self._normalize_difficulty(values.get("difficulty")),
            "priority": values.get("priority", 10),
            "sequence": values.get("sequence") or 10,
            "suggested": bool(values.get("suggested", False)),
            "active": values.get("active", True),
            "version": normalize_text(values.get("version")) or version,
            "guide_anchor": normalize_text(values.get("guide_anchor")) or False,
            "source_reference": normalize_text(values.get("source_reference")) or False,
            "menu_path": normalize_text(values.get("menu")) or False,
            "target_model": normalize_text(values.get("model")) or False,
            "prerequisites": normalize_text(values.get("prerequisites")) or False,
            "steps": normalize_text(values.get("steps")) or False,
            "tips": normalize_text(values.get("tips")) or False,
            "errors": normalize_text(values.get("errors")) or False,
            "group_ids": [(6, 0, self._groups_from_roles(values.get("roles") or []).ids)],
        }
        if article:
            article.write(vals)
        else:
            article = Article.create(vals)
        return article, created, False

    def _sync_media(self, article, values, options):
        if not options.get("reimport_media"):
            return 0
        # Les datasets actuels ne transportent pas de binaires exploitables.
        # L'option est prête pour une évolution future sans toucher aux médias manuels.
        return 0

    def _question_values_from_article_values(self, values):
        raw_questions = values.get("questions")
        if raw_questions:
            if isinstance(raw_questions, (str, dict)):
                raw_questions = [raw_questions]
            questions = [normalize_text(question) for question in raw_questions]
        else:
            questions = [normalize_text(values.get("question"))]
        clean_questions = []
        for question in questions:
            if question and question not in clean_questions:
                clean_questions.append(question)
        return clean_questions

    def _sync_questions(self, article, questions):
        Question = self.env["mowgli.knowledge.question"].sudo()
        clean_questions = []
        for question in questions:
            question = normalize_text(question)
            if question and question not in clean_questions:
                clean_questions.append(question)
        if article.question and article.question not in clean_questions:
            clean_questions.insert(0, article.question)
        existing = Question.search([("article_id", "=", article.id)])
        for index, question in enumerate(clean_questions, start=1):
            vals = {
                "article_id": article.id,
                "name": question,
                "sequence": index * 10,
            }
            record = existing.filtered(lambda item: item.name == question)[:1]
            if record:
                record.write(vals)
            else:
                Question.create(vals)

    def _normalize_difficulty(self, difficulty):
        difficulty = normalize_text(difficulty) or "beginner"
        valid_values = dict(self.env["mowgli.knowledge.article"].DIFFICULTY_SELECTION)
        return difficulty if difficulty in valid_values else "beginner"

    def _sync_keywords(self, article, keywords):
        Keyword = self.env["mowgli.knowledge.keyword"].sudo()
        clean_keywords = []
        if isinstance(keywords, (str, dict)):
            keywords = [keywords]
        for keyword in keywords:
            keyword = normalize_text(keyword)
            if keyword and keyword not in clean_keywords:
                clean_keywords.append(keyword)
        existing = Keyword.search([("article_id", "=", article.id)])
        count = 0
        for keyword in clean_keywords:
            record = existing.filtered(lambda kw: kw.name == keyword)[:1]
            if not record:
                Keyword.create({"article_id": article.id, "name": keyword})
            count += 1
        return count

    def _sync_links(self, article, links, stats=None):
        Link = self.env["mowgli.knowledge.link"].sudo()
        normalized = []
        if isinstance(links, (str, dict)):
            links = [links]
        for link in links:
            if isinstance(link, str):
                link = {"url": link, "title": link}
            url = normalize_text(link.get("url"))
            if not url:
                continue
            normalized.append({
                "title": normalize_text(link.get("title")) or url,
                "url": url,
                "description": normalize_text(link.get("description")) or False,
                "sequence": link.get("sequence") or 10,
                "active": link.get("active", True),
            })
        existing = Link.search([("article_id", "=", article.id)])
        count = 0
        for vals in normalized:
            record = existing.filtered(lambda link: link.url == vals["url"])[:1]
            vals["article_id"] = article.id
            if record:
                record.write(vals)
                if stats is not None:
                    stats["links_updated"] += 1
            else:
                Link.create(vals)
                if stats is not None:
                    stats["links_created"] += 1
            count += 1
        return count

    def _sync_dataset_links(self, workflow, links, stats=None):
        Article = self.env["mowgli.knowledge.article"].sudo()
        total = 0
        if isinstance(links, (str, dict)):
            links = [links]
        links_by_article = {}
        for link in links or []:
            if not isinstance(link, dict):
                continue
            article_ref = normalize_text(link.get("article") or link.get("article_id"))
            if not article_ref:
                continue
            links_by_article.setdefault(article_ref, []).append(link)
        for article_ref, article_links in links_by_article.items():
            article = Article.search([
                ("workflow_id", "=", workflow.id),
                ("external_id", "=", article_ref),
            ], limit=1)
            if article:
                total += self._sync_links(article, article_links, stats=stats)
        return total

    def _sync_related_questions(self, related_queue):
        Article = self.env["mowgli.knowledge.article"].sudo()
        for article, related_external_ids in related_queue:
            related = Article.browse()
            if isinstance(related_external_ids, (str, dict)):
                related_external_ids = [related_external_ids]
            for external_id in related_external_ids:
                external_id = normalize_text(external_id)
                if not external_id:
                    continue
                related |= Article.search([
                    ("workflow_id", "=", article.workflow_id.id),
                    ("external_id", "=", external_id),
                ], limit=1)
            if related:
                article.write({"related_question_ids": [(4, related_id) for related_id in related.ids]})

    def _sync_missing_articles(self, seen_articles, stats, options):
        if not options.get("delete_missing_articles"):
            return
        if not stats.get("datasets") or stats.get("errors"):
            return
        Article = self.env["mowgli.knowledge.article"].sudo()
        domain = [("active", "=", True)]
        if seen_articles:
            domain.append(("id", "not in", seen_articles.ids))
        missing_articles = Article.search(domain)
        stats["articles_deleted"] = len(missing_articles)
        if missing_articles:
            missing_articles.unlink()

    def _update_preserved_counters(self, stats, options):
        stats["unanswered_preserved"] = self.env[
            "mowgli.knowledge.unanswered.question"
        ].sudo().search_count([])
        if options.get("reimport_media"):
            return
        Article = self.env["mowgli.knowledge.article"].sudo()
        articles = Article.search([])
        stats["media_preserved"] = (
            len(articles.image_ids)
            + len(articles.video_ids)
            + len(articles.document_ids)
            + len(articles.link_ids)
        )

    def _groups_from_roles(self, roles):
        groups = self.env["res.groups"].sudo().browse()
        if isinstance(roles, (str, dict)):
            roles = [roles]
        for role in roles:
            role = normalize_text(role)
            if not role:
                continue
            role_key = role.lower()
            for xmlid in self.ROLE_GROUP_XMLIDS.get(role_key, self.ROLE_GROUP_XMLIDS.get(role, [])):
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group:
                    groups |= group
            if not groups.filtered(lambda group: group.name == role):
                groups |= self.env["res.groups"].sudo().search([("name", "=", role)], limit=1)
        return groups

    def _format_sync_report(self, stats):
        details = "\n".join(stats.get("error_details") or [])
        message = _(
            "Import terminé\n\n"
            "✓ Workflows créés : %(workflows_created)s\n"
            "✓ Workflows mis à jour : %(workflows_updated)s\n\n"
            "✓ Fichiers YAML lus : %(yaml_files_read)s\n"
            "✓ Fichiers YAML absents : %(yaml_files_missing)s\n\n"
            "✓ Catégories créées : %(categories_created)s\n"
            "✓ Catégories mises à jour : %(categories_updated)s\n\n"
            "✓ Articles créés : %(articles_created)s\n"
            "✓ Articles mis à jour : %(articles_updated)s\n\n"
            "✓ Articles ignorés : %(articles_ignored)s\n"
            "✓ Articles supprimés : %(articles_deleted)s\n\n"
            "✓ Médias conservés : %(media_preserved)s\n"
            "✓ Médias importés : %(media_imported)s\n\n"
            "✓ FAQ créées : %(faq_created)s\n"
            "✓ FAQ mises à jour : %(faq_updated)s\n"
            "✓ Questions sans réponse conservées : %(unanswered_preserved)s\n\n"
            "✓ Liens créés : %(links_created)s\n"
            "✓ Liens mis à jour : %(links_updated)s\n"
            "✓ Liens total traités : %(links)s\n"
            "✓ FAQ : %(faq)s\n"
            "✓ Mots-clés : %(keywords)s\n"
            "✓ Erreurs : %(errors)s"
        ) % stats
        if details:
            message += "\n\n" + details
        return message
