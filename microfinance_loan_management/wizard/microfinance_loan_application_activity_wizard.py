# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Champs non copiés depuis/vers microfinance.loan.application lors de la synchronisation
# générique du wizard (métadonnées ORM + le lien vers le dossier lui-même).
_EXCLUDED_FIELDS = ('id', 'application_id', 'display_name', 'create_date', 'create_uid', 'write_date', 'write_uid')


class MicrofinanceLoanApplicationActivityWizard(models.TransientModel):
    """Wizard popup — Section IV : Analyse de l'activité à financer et sa viabilité.

    Copie les champs scalaires de microfinance.loan.application à l'ouverture
    (default_get), les réécrit sur le dossier réel à la validation."""
    _name = 'microfinance.loan.application.activity.wizard'
    _description = "Modifier l'analyse de l'activité à financer"

    application_id = fields.Many2one('microfinance.loan.application', required=True)

    activity_description = fields.Text(string="Description de l'activité")
    activity_code = fields.Char(string="Code activité")
    activity_sector = fields.Selection([
        ('commerce', 'Commerce'),
        ('manufacturing', 'Fabrication'),
        ('service', 'Service'),
        ('other', 'Autres'),
    ], string="Secteur d'activité")
    sale_location_status = fields.Selection([
        ('owner', 'Propriétaire'),
        ('tenant', 'Locataire'),
    ], string='Lieu de vente : statut')
    sale_location_type = fields.Selection([
        ('fixed', 'Fixe'),
        ('mobile', 'Mobile'),
        ('ambulant', 'Ambulant'),
        ('delivery', 'Livraison'),
    ], string='Lieu de vente : type')
    sale_location_enclosed = fields.Selection([
        ('closed', 'Fermé'),
        ('open', 'Ouvert'),
    ], string='Lieu de vente : fermé/ouvert')
    formalization_level = fields.Selection([
        ('informal', 'Informel'),
        ('fokontany_authorization', 'Autorisation fokontany'),
        ('patente', 'Patente'),
        ('statistical_card', 'Carte statistique'),
        ('trade_register', 'Registre du commerce'),
    ], string='Niveau de formalisation')
    activity_start_date = fields.Date(string="Début de l'activité")
    activity_interruption = fields.Text(string="Interruptions de l'activité")
    is_cyclical = fields.Boolean(string='Activité cyclique')
    cyclical_period = fields.Char(string='Période du cycle')
    supply_frequency = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string="Fréquence d'approvisionnement")
    supplier_payment_mode = fields.Selection([
        ('cash', 'Comptant'),
        ('credit', 'Crédit'),
    ], string='Paiement fournisseurs')
    supplier_credit_delay_days = fields.Integer(string='Délai crédit fournisseur (jours)')
    sale_frequency = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string='Fréquence des ventes')
    customer_type = fields.Selection([
        ('passersby', 'Passants'),
        ('neighbors', 'Voisins'),
        ('on_order', 'Sur commande'),
        ('other', 'Autres'),
    ], string='Type de clientèle')
    customer_payment_mode = fields.Selection([
        ('cash', 'Comptant'),
        ('credit', 'Crédit'),
    ], string='Paiement clients')
    customer_credit_delay_days = fields.Integer(string='Délai crédit clients (jours)')
    other_income_activities = fields.Text(string='Autres activités génératrices de revenus')
    loan_request_reason = fields.Text(
        string='Pourquoi demander le prêt maintenant ?',
        help='À renseigner uniquement pour un premier prêt (PP uniquement sur la fiche papier).',
    )
    has_existing_debt = fields.Boolean(string='Dette en cours')
    debt_purpose = fields.Char(string='Objet de la dette')
    currency_id = fields.Many2one(related='application_id.currency_id', readonly=True)
    debt_amount = fields.Monetary(string='Montant de la dette')
    debt_creditor_type = fields.Selection([
        ('family', 'Famille'),
        ('friend', 'Ami'),
        ('neighbor', 'Voisin'),
        ('imf', 'IMF'),
        ('bank', 'Banque'),
        ('other', 'Autre'),
    ], string='Créancier')
    debt_repayment_mode = fields.Selection([
        ('daily', 'Journalier'),
        ('weekly', 'Hebdomadaire'),
        ('bimonthly', 'Bimensuel'),
        ('monthly', 'Mensuel'),
        ('other', 'Autre'),
    ], string='Mode de remboursement de la dette')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        application = self.env['microfinance.loan.application'].browse(
            self.env.context.get('default_application_id')
        )
        if application:
            for field_name in fields_list:
                if field_name in application._fields and field_name not in _EXCLUDED_FIELDS:
                    res[field_name] = application[field_name]
        return res

    def action_validate(self):
        self.ensure_one()
        vals = {f: self[f] for f in self._fields if f not in _EXCLUDED_FIELDS and f != 'currency_id'}
        self.application_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}
