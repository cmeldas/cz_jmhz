# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests import BaseCase, tagged

from odoo.addons.cz_jmhz.lib import calc


@tagged("post_install", "-at_install")
class TestCalc(BaseCase):

    def test_round_advance_base(self):
        self.assertEqual(calc.round_advance_base(0), 0)
        self.assertEqual(calc.round_advance_base(50), 50)
        self.assertEqual(calc.round_advance_base(101), 200)
        self.assertEqual(calc.round_advance_base(11999), 12000)

    def test_tax_with_declaration(self):
        tax = calc.compute_tax(11999, calc.TAX_DECLARATION, 15.0, 2570)
        self.assertEqual((tax.base, tax.computed, tax.credit, tax.tax), (11999, 1800, 1800, 0))
        tax = calc.compute_tax(20000, calc.TAX_DECLARATION, 15.0, 2570)
        self.assertEqual((tax.computed, tax.credit, tax.tax), (3000, 2570, 430))

    def test_tax_withholding_rounds_down(self):
        self.assertEqual(calc.compute_tax(11999, calc.TAX_WITHHOLDING, 15.0, 2570).tax, 1799)
        self.assertEqual(calc.compute_tax(3200, calc.TAX_WITHHOLDING, 15.0, 2570).tax, 480)

    def test_tax_advance_without_credit(self):
        tax = calc.compute_tax(11999, calc.TAX_ADVANCE, 15.0, 2570)
        self.assertEqual((tax.computed, tax.credit, tax.tax), (1800, 0, 1800))

    def test_tax_mode(self):
        self.assertEqual(calc.tax_mode(True, True), calc.TAX_DECLARATION)
        self.assertEqual(calc.tax_mode(False, True), calc.TAX_WITHHOLDING)
        self.assertEqual(calc.tax_mode(False, False), calc.TAX_ADVANCE)

    def test_insurance_above_limit(self):
        insurance = calc.compute_insurance(12000, 24.8, 7.1, 9.0, 4.5)
        self.assertEqual(insurance, (2976, 852, 1080, 540))
        self.assertEqual(insurance.employer_total, 4056)
        self.assertEqual(insurance.employee_total, 1392)

    def test_span_and_fund(self):
        september = date(2026, 9, 1)
        self.assertEqual(calc.employment_span(september, date(2026, 6, 15), None), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(calc.employment_span(september, date(2026, 9, 15), date(2026, 10, 31)),
                         (date(2026, 9, 15), date(2026, 9, 30)))
        self.assertIsNone(calc.employment_span(september, date(2026, 10, 1), None))
        self.assertEqual(calc.weekday_fund(date(2026, 9, 1), date(2026, 9, 30)), 22 * 8)
        self.assertEqual(calc.weekday_fund(date(2026, 9, 15), date(2026, 9, 30)), 12 * 8)

    def test_average_earnings_not_below_minimum_wage(self):
        self.assertEqual(calc.average_hourly_earnings(150, 134.4), 150)
        self.assertEqual(calc.average_hourly_earnings(100, 134.4), 134.4)
        self.assertEqual(calc.average_hourly_earnings(0, 134.4), 134.4)

    def test_line_warnings(self):
        def levels(**kwargs):
            values = dict(amount=6000, hours=40, legal_limit=12000, min_hourly_wage=134.4, year_hours=40,
                          has_declaration=True, mode=calc.TAX_DECLARATION)
            values.update(kwargs)
            return [check.level for check in calc.line_warnings(**values)]

        self.assertEqual(levels(), [])
        self.assertIn(calc.LEVEL_ERROR, levels(amount=12000, hours=80))
        self.assertIn(calc.LEVEL_WARNING, levels(amount=11000, hours=120))  # 91,67 Kč/h
        self.assertIn(calc.LEVEL_WARNING, levels(year_hours=301))
        self.assertIn(calc.LEVEL_WARNING, levels(attendance_hours=38))
        self.assertIn(calc.LEVEL_INFO, levels(has_declaration=False, mode=calc.TAX_WITHHOLDING))
