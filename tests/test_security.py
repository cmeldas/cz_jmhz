# -*- coding: utf-8 -*-
"""Práva po převodu na ir.access (Odoo 20): jen Správce JMHZ a jen záznamy povolených firem."""
from datetime import date

from odoo.exceptions import AccessError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestJmhzSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "JMHZ firma A"})
        cls.company_b = cls.env["res.company"].create({"name": "JMHZ firma B"})
        cls.manager = new_test_user(
            cls.env, login="jmhz_manager", groups="cz_jmhz.group_cz_jmhz_manager",
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)])
        cls.hr_officer = new_test_user(
            cls.env, login="jmhz_hr_officer", groups="hr.group_hr_user",
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)])
        cls.report_a = cls.env["cz.jmhz.report"].create({"company_id": cls.company_a.id, "period": date(2026, 9, 1)})
        cls.report_b = cls.env["cz.jmhz.report"].create({"company_id": cls.company_b.id, "period": date(2026, 9, 1)})

    def test_manager_sees_only_own_company(self):
        Report = self.env["cz.jmhz.report"].with_user(self.manager)
        self.assertEqual(Report.search([("id", "in", (self.report_a | self.report_b).ids)]), self.report_a)
        with self.assertRaises(AccessError):
            self.report_b.with_user(self.manager).read(["name"])

    def test_hr_officer_without_group_has_no_access(self):
        with self.assertRaises(AccessError):
            self.env["cz.jmhz.report"].with_user(self.hr_officer).search([])
        with self.assertRaises(AccessError):
            self.env["cz.jmhz.year.param"].with_user(self.hr_officer).search([])

    def test_manager_reads_personal_fields(self):
        employee = self.env["hr.employee"].create({"name": "Jana Nováková", "company_id": self.company_a.id,
                                                   "identification_id": "055301/5555"})
        employee = employee.with_user(self.manager)
        self.assertEqual(employee._jmhz_birth_number(), "0553015555")
        self.assertEqual(employee._jmhz_name_parts(), ("Jana", "Nováková"))

    def test_hr_officer_without_group_edits_employee(self):
        """HR úředník bez skupiny JMHZ smí psát jméno zaměstnance (onchange jména nesmí číst pole JMHZ)."""
        # Formulář zaměstnance v 20 vyžaduje pracoviště; nová testovací firma žádné nemá.
        self.env["hr.work.location"].create({
            "name": "Ranč", "company_id": self.company_a.id, "address_id": self.company_a.partner_id.id})
        form = Form(self.env["hr.employee"].with_user(self.hr_officer))
        form.name = "Petr Novák"
        employee = form.save()
        self.assertFalse(employee.sudo().jmhz_first_name)
        self.assertFalse(employee.sudo().jmhz_tax_residence_id)
        self.env["hr.employee"].with_user(self.hr_officer).create({"name": "Karel Dvořák"})
        form = Form(self.env["hr.employee"].with_user(self.manager))
        form.name = "Eva Malá"
        self.assertEqual((form.jmhz_first_name, form.jmhz_last_name), ("Eva", "Malá"))
        self.assertEqual(form.jmhz_tax_residence_id, self.env.ref("base.cz"))
