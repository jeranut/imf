# -*- coding: utf-8 -*-
import datetime
import html
import logging
import os
import re

import odoo.modules
from markupsafe import Markup
from odoo import api, fields, models

from .mowgli_bot import MODULE_NAME

_logger = logging.getLogger(__name__)

STATUS_MD_FILENAME = "STATUS.md"

CHECKBOX_RE = re.compile(r"^-\s*\[( |x|X)\]\s*(.+)$")
BULLET_RE = re.compile(r"^-\s+(?!\[)(.+)$")
HEADER_RE = re.compile(r"^##\s+(.+)$")
IMPACT_RE = re.compile(r"[—-]\s*impact\s*:\s*(faible|moyen|bloquant)\s*$", re.I)
INSPECTED_RE = re.compile(r"Derni[eè]re inspection\s*:\s*(.+)$", re.I)
BACKTICK_RE = re.compile(r"`([^`]+)`")

SECTION_STATE = {
    "fait": "done",
    "à faire / incomplet": "todo",
    "a faire / incomplet": "todo",
    "incohérences relevées": "issue",
    "incoherences relevees": "issue",
}


def _html_text(value):
    return Markup(html.escape(html.unescape(str(value or "")), quote=False))


class MowgliDevStatusItem(models.Model):
    _name = "mowgli.dev.status.item"
    _description = "Statut dev MOWGLI (docs_dev/*/STATUS.md)"
    _order = "workflow, state, id"

    STATE_SELECTION = [
        ("done", "Fait"),
        ("todo", "À faire"),
        ("issue", "Incohérence"),
    ]
    IMPACT_SELECTION = [
        ("faible", "Faible"),
        ("moyen", "Moyen"),
        ("bloquant", "Bloquant"),
    ]
    IMPACT_ORDER = {"bloquant": 0, "moyen": 1, "faible": 2, False: 3}
    STATE_ICONS = {"done": "✅", "todo": "⬜", "issue": "⚠️"}

    workflow = fields.Char(required=True, index=True)
    title = fields.Char(required=True)
    state = fields.Selection(STATE_SELECTION, required=True, index=True)
    description = fields.Text()
    source_ref = fields.Char()
    impact = fields.Selection(IMPACT_SELECTION)
    last_inspected = fields.Date()

    _sql_constraints = [
        (
            "workflow_state_title_unique",
            "unique(workflow, state, title)",
            "Cet élément de statut dev existe déjà pour ce workflow.",
        ),
    ]

    # ------------------------------------------------------------------
    # Synchronisation depuis docs_dev/<workflow>/STATUS.md
    # ------------------------------------------------------------------

    @api.model
    def sync_from_docs_dev(self):
        stats = {
            "files_read": 0,
            "items_created": 0,
            "items_updated": 0,
            "errors": 0,
            "error_details": [],
        }
        root = self._get_docs_dev_root()
        if not root or not os.path.isdir(root):
            return stats
        for workflow in sorted(os.listdir(root)):
            status_path = os.path.join(root, workflow, STATUS_MD_FILENAME)
            if not os.path.isfile(status_path):
                continue
            try:
                items, last_inspected = self._parse_status_file(status_path)
                stats["files_read"] += 1
                for item_vals in items:
                    item_vals["workflow"] = workflow
                    item_vals["last_inspected"] = last_inspected
                    created = self._upsert_status_item(item_vals)
                    stats["items_created" if created else "items_updated"] += 1
            except Exception as exc:
                stats["errors"] += 1
                stats["error_details"].append("%s: %s" % (status_path, exc))
                _logger.exception("Unable to import MOWGLI dev status %s", status_path)
        return stats

    @api.model
    def _get_docs_dev_root(self):
        return odoo.modules.get_module_resource(MODULE_NAME, "docs_dev")

    @api.model
    def _parse_status_file(self, path):
        with open(path, "r", encoding="utf-8") as stream:
            content = stream.read()
        last_inspected = False
        inspected_match = INSPECTED_RE.search(content)
        if inspected_match:
            last_inspected = self._parse_date(inspected_match.group(1).strip())
        items = []
        current_state = False
        for line in content.splitlines():
            stripped = line.strip()
            header_match = HEADER_RE.match(stripped)
            if header_match:
                current_state = SECTION_STATE.get(header_match.group(1).strip().lower())
                continue
            if not current_state:
                continue
            if current_state in ("done", "todo"):
                checkbox_match = CHECKBOX_RE.match(stripped)
                if checkbox_match:
                    items.append(self._build_item_vals(current_state, checkbox_match.group(2)))
            elif current_state == "issue":
                bullet_match = BULLET_RE.match(stripped)
                if bullet_match:
                    items.append(self._build_item_vals(current_state, bullet_match.group(1)))
        return items, last_inspected

    @api.model
    def _parse_date(self, value):
        for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        return False

    @api.model
    def _build_item_vals(self, state, text):
        text = text.strip()
        impact = False
        impact_match = IMPACT_RE.search(text)
        if impact_match:
            impact = impact_match.group(1).lower()
            text = text[: impact_match.start()].rstrip(" —-")
        source_refs = BACKTICK_RE.findall(text)
        source_ref = "; ".join(source_refs) if source_refs else False
        title = text.split(" — ")[0].strip() or text[:120]
        if len(title) > 120:
            title = title[:117].rstrip() + "..."
        return {
            "title": title,
            "state": state,
            "description": text,
            "source_ref": source_ref,
            "impact": impact,
        }

    @api.model
    def _upsert_status_item(self, vals):
        record = self.sudo().search([
            ("workflow", "=", vals["workflow"]),
            ("state", "=", vals["state"]),
            ("title", "=", vals["title"]),
        ], limit=1)
        if record:
            record.write(vals)
            return False
        self.sudo().create(vals)
        return True

    # ------------------------------------------------------------------
    # Commandes /todo et /done (assistant dev, réservé group_mowgli_developer)
    # ------------------------------------------------------------------

    @api.model
    def render_command_reply(self, command, workflow_filter=False):
        if command == "todo":
            domain = [("state", "in", ("todo", "issue"))]
        else:
            domain = [("state", "=", "done")]
        if workflow_filter:
            domain.append(("workflow", "=", workflow_filter))
        items = self.sudo().search(domain, order="workflow, id")
        if command == "todo":
            items = items.sorted(key=lambda item: self.IMPACT_ORDER.get(item.impact, 3))

        if not items:
            label = "à faire" if command == "todo" else "fait"
            suffix = " pour %s" % workflow_filter if workflow_filter else ""
            return Markup("<p>Aucun élément %s%s.</p>") % (_html_text(label), _html_text(suffix))

        heading = "À faire / incohérences MOWGLI" if command == "todo" else "Fait — statut dev MOWGLI"
        content = Markup("<p><strong>%s</strong></p>") % _html_text(heading)
        current_workflow = None
        for item in items:
            if item.workflow != current_workflow:
                if current_workflow is not None:
                    content += Markup("</ul>")
                current_workflow = item.workflow
                content += Markup("<p><strong>%s</strong></p><ul>") % _html_text(current_workflow)
            line = "%s %s" % (self.STATE_ICONS.get(item.state, "•"), item.title)
            if item.impact:
                line += " (impact : %s)" % item.impact
            if item.source_ref:
                line += " — %s" % item.source_ref
            content += Markup("<li>%s</li>") % _html_text(line)
        content += Markup("</ul>")
        return content
