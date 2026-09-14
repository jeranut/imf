# -*- coding: utf-8 -*-
from odoo import fields, models

# --- Numérotation du code de transfert inter-agences (Sous-lot A) ---------------
#
# Deux séquences ir.sequence DÉDIÉES PAR SOCIÉTÉ (jamais partagées entre agences),
# créées à la demande via res.company._get_or_create_numbering_sequence
# (microfinance_loan_management) — exactement le même patron que la numérotation
# des dossiers de crédit (microfinance.loan.agency), des comptes clients
# (microfinance.partner.account), etc. Voir docs_dev/guichet_caisse/
# AUDIT_transfert_inter_agence.md §1.
#
#  - SOURCE : numéro d'ordre côté agence qui ENCAISSE le remboursement (« sortant »).
#  - DEST   : numéro d'ordre côté agence PROPRIÉTAIRE du crédit (« entrant »).
#
# Décision actée : les DEUX numéros sont tirés dès la création du transfert
# (à l'encaissement), pas seulement à la validation destination.
TRANSFER_SEQ_SOURCE = 'microfinance.transfert.sortant'
TRANSFER_SEQ_DEST = 'microfinance.transfert.entrant'

# L'exemple de code validé (T/IS00000/IS/000/01/05/27/DB/000) montre un numéro
# d'ordre sur 3 chiffres : padding explicite à 3 (le défaut du helper de
# numérotation est 6). Odoo démarre une séquence à 1 → le premier code d'une
# agence porte l'ordre « 001 » (le « 000 » de l'exemple est un simple gabarit).
TRANSFER_SEQ_PADDING = 3


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _build_microfinance_transfer_code(self, destination_company, partner_account_number, date=None):
        """Assemble le code d'un transfert de remboursement inter-agences.

        Format ::

            T/<n° compte client sans '/'>/<préfixe source>/<ordre source>/
              <jj>/<mm>/<aa>/<préfixe destination>/<ordre destination>

        Exemple : ``T/IS00042/IS/001/01/05/27/DB/001``.

        - ``self``                   = agence **source** (celle qui encaisse) ;
        - ``destination_company``    = agence **propriétaire du crédit** ;
        - ``partner_account_number`` = ``res.partner.microfinance_account_number``
          du client (format ``AGENCE/NNNNNN``) ; tous les ``/`` en sont retirés ;
        - ``date``                   = date de l'encaissement (défaut : aujourd'hui),
          formatée ``jj/mm/aa`` sur 2 chiffres chacun.

        Les deux numéros d'ordre sont **tirés ici, à l'appel** (= à la création du
        transfert) : ``TRANSFER_SEQ_SOURCE`` sur ``self`` et ``TRANSFER_SEQ_DEST``
        sur ``destination_company``, ``padding=3``, chacune propre à sa société.
        Chaque appel consomme donc un numéro sur chacune des deux séquences. Le
        code obtenu n'est jamais régénéré ensuite (le champ porteur, Sous-lot B,
        est ``readonly`` / ``copy=False``, comme tous les numéros du projet).
        """
        self.ensure_one()
        destination_company.ensure_one()
        date = date or fields.Date.context_today(self)
        compte = (partner_account_number or '').replace('/', '')
        ordre_source = self._get_or_create_numbering_sequence(
            TRANSFER_SEQ_SOURCE, padding=TRANSFER_SEQ_PADDING)
        ordre_dest = destination_company._get_or_create_numbering_sequence(
            TRANSFER_SEQ_DEST, padding=TRANSFER_SEQ_PADDING)
        return 'T/%s/%s/%s/%s/%s/%s/%s/%s' % (
            compte,
            self.agency_code, ordre_source,
            date.strftime('%d'), date.strftime('%m'), date.strftime('%y'),
            destination_company.agency_code, ordre_dest,
        )
