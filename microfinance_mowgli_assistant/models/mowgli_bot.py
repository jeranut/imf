# -*- coding: utf-8 -*-
import html
import uuid

from markupsafe import Markup

from odoo import api, models

MODULE_NAME = "microfinance_mowgli_assistant"
BOT_NAME = "MOWGLI — Microfinance Operations With Generative Learning Intelligence"
BOT_EMAIL = "mowgli@cefor.local"
BOT_LOGIN = "mowgli_bot@cefor.local"


def _html_text(value):
    return Markup(html.escape(html.unescape(str(value or "")), quote=False))


class MowgliBotAssistant(models.AbstractModel):
    _name = "mowgli.bot.assistant"
    _description = "Assistant Discuss MOWGLI"

    GROUP_SPECS = {
        "user": ("group_mowgli_user", "Utilisateur MOWGLI"),
        "admin": ("group_mowgli_admin", "Administrateur MOWGLI"),
        "agent_credit": ("group_mowgli_agent_credit", "Agent crédit"),
        "agent_epargne": ("group_mowgli_agent_epargne", "Agent épargne"),
        "caissier": ("group_mowgli_caissier", "Caissier"),
        "comptable": ("group_mowgli_comptable", "Comptable"),
        "credit_committee": ("group_mowgli_credit_committee", "Comité de crédit"),
        "gestionnaire": ("group_mowgli_gestionnaire", "Gestionnaire"),
    }

    @api.model
    def _ensure_mowgli_setup(self):
        self = self.sudo()
        category = self._ensure_module_category()
        groups = self._ensure_groups(category)
        bot_user = self._ensure_bot_user(groups["user"])
        self._ensure_discuss_chats(bot_user)
        return True

    @api.model
    def _ensure_module_category(self):
        return self._ensure_xml_record(
            MODULE_NAME,
            "module_category_mowgli_assistant",
            "ir.module.category",
            {"name": "MOWGLI", "sequence": 30},
        )

    @api.model
    def _ensure_groups(self, category):
        groups = {}
        for key, (xmlid, name) in self.GROUP_SPECS.items():
            groups[key] = self._ensure_xml_record(
                MODULE_NAME,
                xmlid,
                "res.groups",
                {"name": name, "category_id": category.id},
            )
        user_group = groups["user"]
        for key, group in groups.items():
            if key != "user" and user_group not in group.implied_ids:
                group.write({"implied_ids": [(4, user_group.id)]})
        return groups

    @api.model
    def _ensure_bot_user(self, user_group):
        partner = self.env.ref(
            "%s.partner_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        if not partner:
            partner = self.env["res.partner"].sudo().search(
                ["|", ("email", "=", BOT_EMAIL), ("name", "=", BOT_NAME)],
                limit=1,
            )
        partner_values = {
            "name": BOT_NAME,
            "email": BOT_EMAIL,
            "active": True,
            "is_company": False,
        }
        if partner:
            partner.write(partner_values)
            self._ensure_xml_id(partner, MODULE_NAME, "partner_mowgli_bot")
        else:
            partner = self._ensure_xml_record(
                MODULE_NAME,
                "partner_mowgli_bot",
                "res.partner",
                partner_values,
            )

        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        bot_user = self.env.ref(
            "%s.user_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        if not bot_user:
            bot_user = self.env["res.users"].sudo().search(
                ["|", ("login", "=", BOT_LOGIN), ("partner_id", "=", partner.id)],
                limit=1,
            )
        user_values = {
            "name": BOT_NAME,
            "login": BOT_LOGIN,
            "partner_id": partner.id,
            "email": BOT_EMAIL,
            "active": True,
            "share": False,
            "notification_type": "inbox",
            "signature": False,
        }
        user_fields = self.env["res.users"]._fields
        if "apps_menu_search_type" in user_fields:
            user_values["apps_menu_search_type"] = "canonical"
        if "apps_menu_theme" in user_fields:
            user_values["apps_menu_theme"] = "milk"
        group_ids = [group.id for group in [group_user, user_group] if group]
        if group_ids:
            user_values["groups_id"] = [(6, 0, group_ids)]
        if bot_user:
            bot_user.with_context(no_reset_password=True).write(user_values)
            self._ensure_xml_id(bot_user, MODULE_NAME, "user_mowgli_bot")
        else:
            user_values["password"] = uuid.uuid4().hex
            bot_user = self.env["res.users"].sudo().with_context(
                no_reset_password=True
            ).create(user_values)
            self._ensure_xml_id(bot_user, MODULE_NAME, "user_mowgli_bot")
        self._ensure_bot_user_login_log(bot_user)
        return bot_user

    @api.model
    def _ensure_bot_user_login_log(self, bot_user):
        self.env.cr.execute(
            """
            INSERT INTO res_users_log (create_uid, write_uid, create_date, write_date)
            SELECT %s, %s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC'
            WHERE NOT EXISTS (
                SELECT 1
                  FROM res_users_log
                 WHERE create_uid = %s
            )
            """,
            (bot_user.id, bot_user.id, bot_user.id),
        )

    @api.model
    def _ensure_discuss_chats(self, bot_user=None, users=None):
        bot_user = bot_user or self.env.ref(
            "%s.user_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        if not bot_user or not bot_user.partner_id:
            return False

        domain = [
            ("active", "=", True),
            ("share", "=", False),
            ("id", "!=", bot_user.id),
        ]
        if users is not None:
            domain.append(("id", "in", users.ids))
        users = self.env["res.users"].sudo().search(domain)
        bot_partner = bot_user.partner_id
        Channel = self.env["discuss.channel"]
        for user in users:
            if not user.partner_id:
                continue
            Channel.with_user(user).with_context(
                allowed_company_ids=user.company_ids.ids,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                mowgli_no_reply=True,
            ).channel_get([bot_partner.id], pin=True)
        return True

    @api.model
    def _ensure_xml_record(self, module, name, model_name, values):
        existing = self.env.ref("%s.%s" % (module, name), raise_if_not_found=False)
        if existing:
            existing.sudo().write(values)
            self._ensure_xml_id(existing, module, name)
            return existing
        record = self.env[model_name].sudo().create(values)
        self._ensure_xml_id(record, module, name)
        return record

    @api.model
    def _ensure_xml_id(self, record, module, name):
        existing = self.env["ir.model.data"].sudo().search(
            [
                ("module", "=", module),
                ("name", "=", name),
            ],
            limit=1,
        )
        values = {
            "module": module,
            "name": name,
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        }
        if existing:
            existing.write(values)
            return existing
        self.env["ir.model.data"].sudo().create(values)

    @api.model
    def _get_mowgli_bot_user(self):
        bot_user = self.env.ref(
            "%s.user_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        if not bot_user or not bot_user.partner_id:
            self._ensure_mowgli_setup()
            bot_user = self.env.ref(
                "%s.user_mowgli_bot" % MODULE_NAME,
                raise_if_not_found=False,
            )
        return bot_user

    @api.model
    def _get_user_mowgli_channels(self, user):
        bot_user = self._get_mowgli_bot_user()
        if not bot_user or not bot_user.partner_id or not user or not user.partner_id:
            return self.env["discuss.channel"].sudo().browse()
        return self.env["discuss.channel"].sudo().search([
            ("channel_type", "=", "chat"),
            ("channel_member_ids.partner_id", "=", bot_user.partner_id.id),
            ("channel_member_ids.partner_id", "=", user.partner_id.id),
        ])

    @api.model
    def _clear_user_mowgli_conversation(self, user):
        channels = self._get_user_mowgli_channels(user)
        if not channels:
            return False
        messages = self.env["mail.message"].sudo().search([
            ("model", "=", "discuss.channel"),
            ("res_id", "in", channels.ids),
        ])
        if messages:
            messages.unlink()
        return True

    @api.model
    def _render_suggested_questions_message(self, user, limit=15):
        articles = self.env["mowgli.knowledge.article"].sudo()._get_suggested_questions_for_user(
            user,
            limit=limit,
        )
        if not articles:
            return Markup("")
        content = Markup("<p><strong>💡 Questions suggérées</strong></p><ul>")
        for article in articles:
            question = article.question or article.title
            content += Markup("<li>%s</li>") % _html_text(question)
        content += Markup("</ul>")
        return content

    @api.model
    def _post_mowgli_suggestions(self, user, channel=None, limit=15):
        bot_user = self._get_mowgli_bot_user()
        if not bot_user or not bot_user.partner_id:
            return False
        channel = channel or self._get_user_mowgli_channels(user)[:1]
        if not channel:
            return False
        body = self._render_suggested_questions_message(user, limit=limit)
        if not body:
            return False
        channel.with_context(mowgli_no_reply=True).message_post(
            body=body,
            author_id=bot_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        return True

    @api.model
    def _post_mowgli_welcome(self, user, channel=None):
        bot_user = self._get_mowgli_bot_user()
        if not bot_user or not bot_user.partner_id:
            return False
        channel = channel or self._get_user_mowgli_channels(user)[:1]
        if not channel:
            return False
        body = Markup(
            "<p>Bonjour %s</p>"
            "<p>Je suis MOWGLI.</p>"
            "<p>Je peux vous accompagner dans votre workflow CEFOR.</p>"
        ) % _html_text(user.name or "")
        channel.with_context(mowgli_no_reply=True).message_post(
            body=body,
            author_id=bot_user.partner_id.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        return True

    @api.model
    def render_reply(self, question, user=None):
        return self.env["mowgli.knowledge.article"].sudo().render_knowledge_reply(question, user=user)
