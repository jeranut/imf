# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tools import mute_logger

from .common import MicrofinanceCommon


class TestAgencyCode(MicrofinanceCommon):
    """agency_code est obligatoire sans condition (pas de gate microfinance_context) : dans
    cette instance, la base contenant les modules microfinance (MOWGLI) ne contient que des
    agences CEFOR — EAT/immobilier tournent sur des bases Postgres totalement séparées, donc
    aucun res.company n'y est partagé avec un usage non-microfinance. Voir décision actée avec
    l'utilisateur au moment de l'implémentation du numéro de compte/dossier agence."""

    def test_agency_code_required(self):
        with self.assertRaises(ValidationError):
            self.env['res.company'].create({'name': 'Agence sans code (test)'})

    def test_agency_code_accepted_when_provided(self):
        company = self.env['res.company'].create({'name': 'Agence avec code (test)', 'agency_code': 'ZZ'})
        self.assertEqual(company.agency_code, 'ZZ')

    @mute_logger('odoo.sql_db')
    def test_agency_code_unique(self):
        self.env['res.company'].create({'name': 'Première agence ZY (test)', 'agency_code': 'ZY'})
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['res.company'].create({'name': 'Deuxième agence ZY (test)', 'agency_code': 'ZY'})
