# -*- coding: utf-8 -*-
import random
import time
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceLoadTestWizard(models.TransientModel):
    _name = 'microfinance.load.test.wizard'
    _description = 'Générateur de client/crédit factice pour tests manuels (dev/staging uniquement)'

    product_id = fields.Many2one(
        'microfinance.loan.product', string='Produit de prêt', required=True,
        domain="[('active', '=', True)]",
    )
    count = fields.Integer(string='Nombre de jeux de test', default=1)

    def _generate_unique_cin(self):
        # 12 chiffres exacts (contrainte _check_cin_format), construits à partir de l'horloge
        # + un aléa pour éviter toute collision entre jeux générés dans la même exécution
        # (contrainte d'unicité globale _check_cin_unique).
        digits = f'{int(time.time() * 1000) % 10**9:09d}{random.randint(0, 999):03d}'
        return digits[-12:]

    def _create_fake_partner(self):
        self.ensure_one()
        timestamp = fields.Datetime.now().strftime('%Y%m%d%H%M%S%f')
        partner = self.env['res.partner'].with_context(microfinance_context=True).create({
            'name': f'TEST Rakoto {timestamp}',
            'is_company': False,
            'company_id': self.env.company.id,
            'microfinance_partner_type': 'client',
            'microfinance_client_type': 'individual',
            'microfinance_id_type': 'cin',
            'microfinance_id_number': self._generate_unique_cin(),
            'microfinance_marital_status': 'single',
        })
        if self.product_id.min_membership_days > 0:
            # create_date n'est pas éditable via le champ (magic field ORM) : seul un UPDATE SQL
            # direct permet de simuler une ancienneté suffisante pour _check_eligibility().
            fake_create_date = fields.Datetime.now() - timedelta(
                days=self.product_id.min_membership_days + 1)
            self.env.cr.execute(
                'UPDATE res_partner SET create_date = %s WHERE id = %s',
                (fake_create_date, partner.id),
            )
            partner.invalidate_recordset(['create_date'])
        return partner

    def _create_fake_guarantee(self, loan):
        self.ensure_one()
        product = self.product_id
        if not (product.guarantee_required or product.min_guarantee_ratio > 0):
            return
        required_guarantee = loan.loan_amount * product.min_guarantee_ratio / 100.0
        rule = self.env['microfinance.guarantee.valuation.rule'].search([
            ('company_id', '=', loan.company_id.id),
            ('guarantee_type', '=', 'other'),
        ], limit=1)
        ratio = rule.valuation_ratio if rule else 100.0
        # Valeur estimée large (marge de sécurité x1.5) pour que la valeur reconnue
        # (estimated_value * ratio / 100) couvre le montant requis même si un ratio de
        # valorisation réduit s'applique.
        estimated_value = max(required_guarantee, loan.loan_amount) * 1.5
        if ratio:
            estimated_value = max(estimated_value, required_guarantee * 100.0 / ratio * 1.2)
        self.env['microfinance.loan.guarantee'].create({
            'loan_id': loan.id,
            'guarantee_type': 'other',
            'description': _('Garantie factice générée par Load Test'),
            'estimated_value': estimated_value,
            'state': 'validated',
        })

    def _generate_one(self):
        self.ensure_one()
        product = self.product_id
        amount = (product.min_amount + product.max_amount) / 2.0
        term = (product.min_term + product.max_term) // 2
        partner = self._create_fake_partner()
        loan = self.env['microfinance.loan'].create({
            'partner_id': partner.id,
            'product_id': product.id,
            'company_id': self.env.company.id,
            'loan_amount': amount,
            'term': term,
        })
        self._create_fake_guarantee(loan)
        try:
            loan.action_start_enquete()
            loan.action_ca_review()
        except UserError as exc:
            raise UserError(_(
                "Échec de la génération du crédit de test #%(loan)s pour le produit "
                "'%(product)s' : %(error)s"
            ) % {'loan': loan.name or loan.id, 'product': product.display_name, 'error': exc.args[0]})
        return loan

    def action_generate(self):
        self.ensure_one()
        loans = self.env['microfinance.loan']
        for _index in range(max(self.count, 1)):
            loans |= self._generate_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crédits de test générés'),
            'res_model': 'microfinance.loan',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', loans.ids)],
        }
