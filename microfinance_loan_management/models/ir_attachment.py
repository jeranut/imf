# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def unlink(self):
        """Protège la pièce jointe de champ du contrat signé
        (microfinance.loan.signed_contract) contre toute suppression : ni depuis le
        chatter, ni via le bouton « x » du widget binaire (qui écrit
        {'signed_contract': False} et déclenche cet unlink()). Un remplacement du
        fichier passe par write({'datas': ...}) sur la pièce jointe existante (pas
        par unlink), il reste donc possible.

        Les PDF générés automatiquement (contrat généré, calendrier de
        remboursement, copie chatter du contrat signé) ont res_field vide → non
        protégés, supprimables comme avant. La suppression du dossier de crédit
        lui-même lève la protection via le contexte bypass_signed_contract_protection
        (cf. microfinance.loan.unlink())."""
        if not self.env.context.get('bypass_signed_contract_protection'):
            protected = self.filtered(
                lambda att: att.res_model == 'microfinance.loan' and att.res_field == 'signed_contract'
            )
            if protected:
                raise UserError(_(
                    "Le contrat signé ne peut pas être supprimé. Pour le corriger, "
                    "téléversez une nouvelle version à sa place."
                ))
        return super().unlink()
