# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError

from .common import MicrofinanceCommon


class TestFieldVisit(MicrofinanceCommon):
    """Section VI — Fiche de catégorisation sociale : visites terrain VAD/VAV."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent1 = cls.env.user
        cls.agent2 = cls.env['res.users'].create({
            'name': 'Second enquêteur test',
            'login': 'test_field_visit_agent2',
        })
        cls.application = cls.env['microfinance.loan.application'].create({
            'partner_id': cls.partner.id,
            'loan_product_id': cls.product.id,
        })

    def _create_visit(self, **kwargs):
        vals = {
            'application_id': self.application.id,
            'agent_id': self.agent1.id,
            'visit_date': '2026-07-01',
        }
        vals.update(kwargs)
        return self.env['microfinance.loan.application.field.visit'].create(vals)

    def test_counter_visit_by_different_agent_ok(self):
        vad = self._create_visit(visit_type='home')
        counter_vad = self._create_visit(
            visit_type='home', agent_id=self.agent2.id,
            is_counter_visit=True, counter_visit_of_id=vad.id,
        )
        self.assertEqual(counter_vad.counter_visit_of_id, vad)

    def test_counter_visit_by_same_agent_raises(self):
        vad = self._create_visit(visit_type='home')
        with self.assertRaises(ValidationError):
            self._create_visit(
                visit_type='home', agent_id=self.agent1.id,
                is_counter_visit=True, counter_visit_of_id=vad.id,
            )

    def test_counter_visit_without_reference_raises(self):
        with self.assertRaises(ValidationError):
            self._create_visit(visit_type='home', agent_id=self.agent2.id, is_counter_visit=True)

    def test_counter_visit_with_different_visit_type_raises(self):
        vav = self._create_visit(visit_type='sales_point')
        with self.assertRaises(ValidationError):
            self._create_visit(
                visit_type='home', agent_id=self.agent2.id,
                is_counter_visit=True, counter_visit_of_id=vav.id,
            )
