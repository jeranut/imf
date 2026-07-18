# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MicrofinanceLoanProgressiveProgram(models.Model):
    """Programme progressif : suite ordonnée de produits de crédit formant un parcours
    client par paliers (ex. Prêt initial → Prêt successif 1 → Prêt successif 2). Ce
    chaînage produit-à-produit est distinct du rang de prêt global
    (microfinance.loan.application.tier / loan_sequence_number), qui ne fait que
    libeller le rang numérique du crédit sans référence à un produit précis.

    Le passage d'un palier au suivant n'est jamais bloqué par le système : seule
    l'éligibilité informative affichée sur le dossier (microfinance.loan.application)
    s'appuie sur ce modèle. La décision d'octroi reste toujours à la commission de
    crédit / au valideur."""
    _name = 'microfinance.loan.progressive.program'
    _description = 'Programme progressif de produits de crédit'
    _order = 'name'

    name = fields.Char(string='Nom', required=True, translate=True)
    code = fields.Char(string='Code')
    company_id = fields.Many2one(
        'res.company', string='Société',
        help='Laisser vide pour un programme commun à toutes les sociétés : le '
             'parcours client est évalué tous établissements confondus (le client peut '
             "avoir pris son premier prêt dans une agence et demander le suivant dans "
             'une autre) — même convention que microfinance.loan.application.tier.',
    )
    active = fields.Boolean(string='Actif', default=True)
    description = fields.Text(string='Description')
    step_ids = fields.One2many(
        'microfinance.loan.progressive.program.step', 'program_id', string='Étapes')
    step_count = fields.Integer(string="Nombre d'étapes", compute='_compute_step_count')

    @api.depends('step_ids')
    def _compute_step_count(self):
        for program in self:
            program.step_count = len(program.step_ids)


class MicrofinanceLoanProgressiveProgramStep(models.Model):
    """Étape d'un programme progressif : rattache un produit de crédit précis à un rang
    dans le parcours, avec la tolérance de retard qui définit une sortie "sans défaut"
    de cette étape (condition d'éligibilité informative à l'étape suivante).

    Un produit ne peut être rattaché qu'à une seule étape, tous programmes confondus
    (contrainte SQL ci-dessous) : cas d'usage validé avec Micka (chaîne linéaire simple
    par produit, pas de réutilisation d'un même produit dans plusieurs programmes)."""
    _name = 'microfinance.loan.progressive.program.step'
    _description = "Étape d'un programme progressif"
    _order = 'program_id, sequence_number, id'

    program_id = fields.Many2one(
        'microfinance.loan.progressive.program', string='Programme', required=True, ondelete='cascade')
    sequence_number = fields.Integer(
        string='Rang', required=True, default=1,
        help="Rang de l'étape dans le programme. 1 = premier palier : aucun prêt "
             'précédent à vérifier pour ce palier.',
    )
    product_id = fields.Many2one(
        'microfinance.loan.product', string='Produit', required=True,
        help='Un produit ne peut être rattaché qu\'à une seule étape, tous programmes '
             'progressifs confondus (cf. contrainte SQL ci-dessous).',
    )
    late_tolerance_days = fields.Integer(
        string='Tolérance de retard (jours)', default=0,
        help='Nombre de jours de retard maximum toléré sur le prêt de cette étape pour '
             'que le client soit considéré "sans défaut" en sortie de cette étape. 0 = '
             'aucune tolérance, tout retard déclenche un statut "avertissement".',
    )
    late_tolerance_amount_percent = fields.Float(
        string='Tolérance de retard (% montant)', default=0.0,
        help='Tolérance sur le montant maximum resté en retard, en % du montant du '
             'crédit, en complément du critère jours : les deux critères doivent être '
             'respectés pour un statut "éligible" propre.',
    )
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('product_unique', 'unique(product_id)',
         "Ce produit est déjà rattaché à une étape d'un programme progressif (un "
         'produit ne peut appartenir qu\'à une seule étape).'),
    ]
