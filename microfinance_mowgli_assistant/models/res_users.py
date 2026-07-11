# -*- coding: utf-8 -*-

from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        self._mowgli_ensure_discuss_chats(users)
        return users

    def write(self, vals):
        result = super().write(vals)
        if {"active", "share", "groups_id"} & set(vals):
            self._mowgli_ensure_discuss_chats(self)
        return result

    def _mowgli_ensure_discuss_chats(self, users):
        if self.env.context.get("mowgli_skip_chat_sync"):
            return
        if "mowgli.bot.assistant" not in self.env:
            return
        self.env["mowgli.bot.assistant"].sudo().with_context(
            mowgli_skip_chat_sync=True
        )._ensure_discuss_chats(users=users.sudo())

    def _mowgli_clear_history(self):
        ICP = self.env["ir.config_parameter"].sudo()
        auto_clear = ICP.get_param(
            "microfinance_mowgli_assistant.mowgli_auto_clear_history",
            "True",
        )
        if str(auto_clear).lower() not in ("1", "true", "yes"):
            return False
        if "mowgli.bot.assistant" not in self.env:
            return False
        for user in self.sudo():
            self.env["mowgli.bot.assistant"].sudo()._clear_user_mowgli_conversation(user)
        return True


class ResUsersLog(models.Model):
    _inherit = "res.users.log"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        user_ids = [vals.get("create_uid") for vals in vals_list if vals.get("create_uid")]
        users = self.env["res.users"].sudo().browse(user_ids).exists()
        if users:
            users._mowgli_clear_history()
        return records
