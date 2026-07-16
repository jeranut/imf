# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    agency_code = fields.Char(
        string='Code agence', size=3, required=True,
        help="Code court identifiant l'agence CEFOR (ex. IS pour Isotry). Sert de préfixe "
             "automatique pour la numérotation des dossiers de crédit et des comptes "
             "d'épargne (format AGENCE/TYPE/SÉRIE, ou AGENCE/SÉRIE pour le crédit). "
             "Obligatoire pour toute société de cette instance.",
    )

    _sql_constraints = [
        ('agency_code_unique', 'unique(agency_code)', "Le code agence doit être unique par société."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # required=True sur le champ suffit à empêcher l'enregistrement en base (NOT NULL),
        # mais laisse remonter une erreur SQL brute jusqu'à l'utilisateur ; ce contrôle
        # explicite intercepte le cas le plus courant (champ jamais renseigné) avec un message
        # métier clair avant même d'atteindre la contrainte SQL.
        for vals in vals_list:
            if not vals.get('agency_code'):
                raise ValidationError(_('Le code agence est obligatoire pour créer une agence CEFOR.'))
        companies = super().create(vals_list)
        companies.mapped('partner_id').write({'microfinance_partner_type': 'agence'})
        return companies

    def _get_or_create_numbering_sequence(self, code, padding=6):
        """Renvoie le prochain numéro (chaîne, déjà complétée par des zéros à `padding`
        chiffres) d'une séquence dédiée à cette société pour `code` — jamais partagée avec une
        autre société. Créée à la demande plutôt que pré-déclarée par agence en XML : de
        nouvelles agences sont ajoutées manuellement au fil de l'eau (jusqu'à 25 à terme), donc
        aucune liste figée de sociétés ne peut être connue à l'avance."""
        self.ensure_one()
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([('code', '=', code), ('company_id', '=', self.id)], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': '%s (%s)' % (code, self.name),
                'code': code,
                'company_id': self.id,
                'padding': padding,
                'number_next': 1,
                'number_increment': 1,
            })
        return sequence.next_by_id()

    loan_product_code_prefix = fields.Char(
        string='Préfixe code produit crédit', default='CR',
        help="Préfixe utilisé pour générer automatiquement le code des nouveaux produits de "
             "crédit de cette société (ex. CR00001). Modifiable uniquement tant qu'aucun "
             "produit de crédit n'a encore été créé pour cette société — dès le premier "
             "produit, le préfixe est verrouillé pour ne jamais mélanger deux styles de code "
             "dans l'historique.",
    )
    loan_product_code_locked = fields.Boolean(
        string='Préfixe crédit verrouillé', compute='_compute_loan_product_code_locked',
        help="Vrai dès qu'au moins un produit de crédit existe pour cette société.",
    )
    microfinance_fond_credit_default_id = fields.Many2one(
        'microfinance.fond.credit', string='Fonds de crédit par défaut',
        domain="[('active', '=', True), "
               "'|', ('date_cloture', '=', False), ('date_cloture', '>=', context_today().strftime('%Y-%m-%d')), "
               "'|', '&', ('scope', '=', 'single_company'), ('company_id', '=', id), ('scope', '=', 'multi_company')]",
        help="Fonds bailleur rotatif proposé par défaut à la création d'un nouveau crédit dans "
             "cette société (pré-remplissage de microfinance.loan.fond_credit_id, simple aide à "
             "la saisie - reste librement modifiable par l'utilisateur avant décaissement, sans "
             "rapport avec le verrouillage de fond_credit_id après décaissement). Modifiable à "
             "tout moment sans restriction ni effet rétroactif : seuls les crédits créés après un "
             "changement de ce champ se voient proposer le nouveau fonds, les crédits déjà créés "
             "gardent leur fond_credit_id tel quel. Pas de groups= au niveau champ (bloquerait la "
             "lecture depuis l'onchange de microfinance.loan pour tout utilisateur non manager, "
             "cassant le pré-remplissage pour un simple agent) : la restriction à "
             "group_microfinance_manager est portée uniquement par la vue "
             "(microfinance_res_company_views.xml).",
    )

    def _compute_loan_product_code_locked(self):
        Product = self.env['microfinance.loan.product']
        for company in self:
            company.loan_product_code_locked = bool(Product.search_count([('company_id', '=', company.id)]))

    def _get_microfinance_dashboard_subtitle(self):
        """Nom de la société + adresse (rue, complément, ville) pour le sous-titre de l'en-tête
        du tableau de bord microfinance. Omet proprement les segments d'adresse vides plutôt que
        de laisser des virgules ou un tiret orphelins."""
        self.ensure_one()
        address_parts = [part for part in (self.street, self.street2, self.city) if part]
        if not address_parts:
            return self.name
        return '%s — %s' % (self.name, ', '.join(address_parts))

    def write(self, vals):
        if 'agency_code' in vals and not vals['agency_code']:
            raise ValidationError(_('Le code agence est obligatoire pour créer une agence CEFOR.'))
        if 'loan_product_code_prefix' in vals:
            Product = self.env['microfinance.loan.product']
            locked = self.filtered(lambda c: Product.search_count([('company_id', '=', c.id)]))
            if locked:
                raise UserError(_(
                    "Le préfixe de code produit crédit ne peut plus être modifié : des produits "
                    "de crédit existent déjà pour %s (numérotation déjà initiée)."
                ) % ', '.join(locked.mapped('name')))
        res = super().write(vals)
        if 'partner_id' in vals:
            self.mapped('partner_id').write({'microfinance_partner_type': 'agence'})
        return res
