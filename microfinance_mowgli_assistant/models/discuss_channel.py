# -*- coding: utf-8 -*-

from odoo import models

from .mowgli_bot import MODULE_NAME


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _mowgli_is_user_channel(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        bot_user = self.env.ref(
            "%s.user_mowgli_bot" % MODULE_NAME,
            raise_if_not_found=False,
        )
        if (
            not bot_user
            or not bot_user.partner_id
            or not user
            or not user.partner_id
            or self.channel_type != "chat"
        ):
            return False
        partners = self.sudo().channel_member_ids.mapped("partner_id")
        return bot_user.partner_id in partners and user.partner_id in partners

    def mowgli_prepare_session(self):
        self.ensure_one()
        if self.env.context.get("mowgli_no_reply"):
            return False
        if not self._mowgli_is_user_channel(self.env.user):
            return False
        ICP = self.env["ir.config_parameter"].sudo()
        clear_on_open = ICP.get_param(
            "microfinance_mowgli_assistant.mowgli_clear_on_chat_close",
            "True",
        )
        if str(clear_on_open).lower() not in ("1", "true", "yes"):
            return False
        user = self.env.user
        assistant = self.env["mowgli.bot.assistant"].sudo()
        assistant._clear_user_mowgli_conversation(user)
        assistant._post_mowgli_welcome(user, channel=self.sudo())
        assistant._post_mowgli_suggestions(user, channel=self.sudo())
        return True
