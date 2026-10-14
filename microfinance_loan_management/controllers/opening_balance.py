# -*- coding: utf-8 -*-
"""Téléchargement du modèle Excel d'une balance d'ouverture (droits et règle de société de l'utilisateur, sans sudo)."""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request


class OpeningBalanceController(http.Controller):

    @http.route('/microfinance/opening_balance/<int:balance_id>/template.xlsx', type='http', auth='user')
    def opening_balance_template(self, balance_id, **kw):
        balance = request.env['microfinance.opening.balance'].browse(balance_id)
        try:
            balance.check_access_rights('read')
            balance.check_access_rule('read')
        except AccessError:
            return request.not_found()
        if not balance.exists():
            return request.not_found()
        content = balance._template_workbook()
        filename = 'Modele_balance_ouverture_%s.xlsx' % (balance.company_id.agency_code or balance.company_id.id)
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="%s"' % filename)])

    @http.route('/microfinance/opening_reprise/template.xlsx', type='http', auth='user')
    def opening_reprise_template(self, **kw):
        content = request.env['microfinance.opening.reprise']._template_workbook()
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', 'attachment; filename="Modele_reprise_portefeuille.xlsx"')])
