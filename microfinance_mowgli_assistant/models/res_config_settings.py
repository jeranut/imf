# -*- coding: utf-8 -*-
import os

import odoo.modules
from odoo import fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def _default_mowgli_dataset_path(self):
        return odoo.modules.get_module_resource('microfinance_mowgli_assistant', 'datasets') or ''

    mowgli_auto_clear_history = fields.Boolean(
        string="Effacer l'historique MOWGLI à la connexion",
        config_parameter="microfinance_mowgli_assistant.mowgli_auto_clear_history",
        default=True,
    )
    mowgli_history_retention_days = fields.Integer(
        string="Rétention historique MOWGLI (jours)",
        config_parameter="microfinance_mowgli_assistant.mowgli_history_retention_days",
        default=0,
    )
    mowgli_clear_on_chat_close = fields.Boolean(
        string="Session MOWGLI temporaire à l'ouverture du chat",
        config_parameter="microfinance_mowgli_assistant.mowgli_clear_on_chat_close",
        default=True,
    )
    mowgli_min_score = fields.Float(
        string="Score minimum MOWGLI",
        config_parameter="microfinance_mowgli_assistant.mowgli_min_score",
        default=0.45,
    )
    mowgli_dataset_path = fields.Char(
        string="Chemin des datasets MOWGLI",
        config_parameter="microfinance_mowgli_assistant.mowgli_dataset_path",
        default=lambda self: self._default_mowgli_dataset_path(),
        help="Dossier externe contenant les sous-dossiers de workflows MOWGLI et leurs fichiers dataset.yaml.",
    )

    def action_open_mowgli_sync(self):
        return self.env.ref(
            "microfinance_mowgli_assistant.action_mowgli_knowledge_sync"
        ).read()[0]

    def action_create_mowgli_dataset_tree(self):
        workflows = [
            "creation_produit_credit",
            "creation_produit_epargne",
            "garanties_scoring",
            "reechelonnement",
            "dossier_precredit",
            "comptabilite",
            "par_reporting",
            "administration",
        ]
        path = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("microfinance_mowgli_assistant.mowgli_dataset_path", "")
            .strip()
        )
        if not path:
            raise UserError("Veuillez renseigner le chemin des datasets MOWGLI.")
        root = os.path.expandvars(os.path.expanduser(path))
        for workflow in workflows:
            workflow_dir = os.path.join(root, workflow)
            os.makedirs(workflow_dir, exist_ok=True)
            dataset_path = os.path.join(workflow_dir, "dataset.yaml")
            if not os.path.exists(dataset_path):
                with open(dataset_path, "w", encoding="utf-8") as stream:
                    stream.write("workflow: %s\nversion: \"17.0\"\narticles: []\n" % workflow)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "MOWGLI",
                "message": "Arborescence datasets créée avec succès.",
                "type": "success",
                "sticky": False,
            },
        }
