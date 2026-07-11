# -*- coding: utf-8 -*-
import re

from odoo import api, models

from .mowgli_bot import BOT_NAME, MODULE_NAME


class MailMessage(models.Model):
    _inherit = "mail.message"

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        for message in messages:
            try:
                # L'interception Discuss se fait ici juste après la création du message.
                message._mowgli_maybe_reply()
            except Exception:
                continue
        return messages

    def _mowgli_maybe_reply(self):
        self.ensure_one()
        if self.env.context.get("mowgli_no_reply"):
            return False
        if self.message_type != "comment":
            return False
        if self.model != "discuss.channel" or not self.res_id:
            return False

        channel = self.env["discuss.channel"].sudo().browse(self.res_id).exists()
        if not channel or channel.channel_type != "chat":
            return False

        bot_user = self.env.ref(
            "%s.user_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        bot_partner = bot_user.partner_id if bot_user else self.env["res.partner"]
        if not bot_partner:
            self.env["mowgli.bot.assistant"].sudo()._ensure_mowgli_setup()
            bot_user = self.env.ref(
                "%s.user_mowgli_bot" % MODULE_NAME,
                raise_if_not_found=False,
            )
            bot_partner = bot_user.partner_id if bot_user else self.env["res.partner"]
        if not bot_partner or self.author_id == bot_partner:
            return False
        if bot_partner not in channel.channel_member_ids.mapped("partner_id"):
            return False

        body_text = self._mowgli_html_to_text(self.body or "")
        if not body_text:
            return False

        sending_user = self._mowgli_get_sending_user()
        reply = self.env["mowgli.bot.assistant"].sudo().render_reply(
            body_text,
            user=sending_user,
        )
        channel.with_context(mowgli_no_reply=True).message_post(
            body=reply,
            author_id=bot_partner.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        return True

    def _mowgli_get_sending_user(self):
        self.ensure_one()
        if self.author_id and self.author_id.user_ids:
            active_users = self.author_id.user_ids.filtered("active")
            if active_users:
                return active_users[0]
            return self.author_id.user_ids[0]
        return self.env.user

    def _mowgli_html_to_text(self, html):
        text = re.sub(r"<br\s*/?>", " ", html or "", flags=re.I)
        text = re.sub(r"</p\s*>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.replace(BOT_NAME, "").strip(" ,:;-")
