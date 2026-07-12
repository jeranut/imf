# -*- coding: utf-8 -*-
"""guarantee_type loses the generic 'asset' value in favor of specific types
(land/vehicle/house/furniture/salary) plus 'other'. Existing 'asset' records are not dropped
or blocked: they are moved to 'other', the closest non-destructive equivalent."""


def migrate(cr, version):
    cr.execute("""
        UPDATE microfinance_loan_guarantee
        SET guarantee_type = 'other'
        WHERE guarantee_type = 'asset'
    """)
