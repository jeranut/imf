# -*- coding: utf-8 -*-


def post_init_hook(env):
    env["mowgli.bot.assistant"]._ensure_mowgli_setup()
    ICP = env["ir.config_parameter"].sudo()
    ICP.set_param("microfinance_mowgli_assistant.mowgli_auto_clear_history", "True")
    ICP.set_param("microfinance_mowgli_assistant.mowgli_clear_on_chat_close", "True")
    ICP.set_param("microfinance_mowgli_assistant.mowgli_history_retention_days", "0")
    ICP.set_param("microfinance_mowgli_assistant.mowgli_min_score", "0.45")
    env["mowgli.knowledge.dataset.sync"].sync_datasets()
