# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceCaisseComptageBrouillon(models.Model):
    """Brouillon persistant du comptage de billetage en cours de clôture (wizard en 3 temps,
    microfinance_caisse_close_session_wizard.py). Un seul brouillon actif par session
    (contrainte SQL) : réécrit à chaque transition d'étape du wizard (temps 1 -> 2, retour du
    temps 3 -> 1), supprimé dès que la clôture aboutit (le comptage devient alors définitif,
    microfinance.caisse.comptage). Volontairement un modèle à part de microfinance.caisse.
    comptage : ce dernier porte des contraintes serveur pensées pour un enregistrement définitif
    (motif obligatoire si écart, variance_state, écriture comptable) qui ne doivent pas
    bloquer un billetage encore en cours de saisie.

    Objectif : si l'utilisateur ferme la fenêtre du wizard avant le clic final "Confirmer la
    clôture" (erreur serveur, distraction, onglet fermé), rouvrir "Fermer la caisse" sur la même
    session retrouve les quantités déjà saisies et le motif d'écart déjà tapé, au lieu de tout
    perdre. Limite connue : rien n'est capturé si la fenêtre est fermée sans qu'aucun bouton du
    wizard n'ait été cliqué depuis la dernière transition (pas d'autosave au clavier)."""
    _name = 'microfinance.caisse.comptage.brouillon'
    _description = 'Brouillon de comptage de billetage (clôture de session en cours)'

    session_id = fields.Many2one(
        'microfinance.caisse.session', string='Session de caisse', required=True,
        ondelete='cascade', index=True,
    )
    line_ids = fields.One2many(
        'microfinance.caisse.comptage.brouillon.line', 'brouillon_id', string='Comptage',
    )
    variance_comment = fields.Text(string="Motif de l'écart")

    _sql_constraints = [
        ('session_uniq', 'unique(session_id)',
         'Un brouillon de comptage existe déjà pour cette session.'),
    ]

    @api.model
    def _save_draft(self, session, line_values, variance_comment):
        """Crée ou met à jour le brouillon de `session` avec les quantités de `line_values`
        (liste de dicts {denomination_id, quantity}) et le motif d'écart courant. Un seul
        brouillon par session (cf. contrainte SQL) : on réutilise l'existant plutôt que d'en
        recréer un, pour ne jamais violer session_uniq."""
        brouillon = self.search([('session_id', '=', session.id)], limit=1)
        line_commands = [(0, 0, values) for values in line_values]
        if brouillon:
            brouillon.write({
                'line_ids': [(5, 0, 0)] + line_commands,
                'variance_comment': variance_comment,
            })
        else:
            brouillon = self.create({
                'session_id': session.id,
                'line_ids': line_commands,
                'variance_comment': variance_comment,
            })
        return brouillon


class MicrofinanceCaisseComptageBrouillonLine(models.Model):
    _name = 'microfinance.caisse.comptage.brouillon.line'
    _description = 'Ligne de brouillon de comptage de billetage'

    brouillon_id = fields.Many2one(
        'microfinance.caisse.comptage.brouillon', string='Brouillon', required=True,
        ondelete='cascade', index=True,
    )
    denomination_id = fields.Many2one(
        'microfinance.caisse.denomination', string='Coupure / pièce', required=True,
    )
    quantity = fields.Integer(string='Quantité', default=0)

    _sql_constraints = [
        ('denom_uniq', 'unique(brouillon_id, denomination_id)',
         'Cette coupure est déjà présente dans ce brouillon.'),
    ]
