# -*- coding: utf-8 -*-
from datetime import date

from freezegun import freeze_time
from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.cz_jmhz.lib import jmh_xml, xsd

F = {"f": jmh_xml.NS_FORM, "n1": jmh_xml.NS_PODANI}
SEPTEMBER = date(2026, 9, 1)


@tagged("post_install", "-at_install")
class TestJmhzReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Vlastní firma, aby testy nezávisely na datech v databázi (hlášení je jedno za firmu a měsíc).
        cls.company = cls.env["res.company"].create({"name": "Ranč test JMHZ", "country_id": cls.env.ref("base.cz").id})
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.company.write({
            "jmhz_variable_symbol": "1234567890",
            "jmhz_ossz_code": "317",
            "jmhz_work_city": "Planá nad Lužnicí",
            "jmhz_work_city_code": "552917",
            "jmhz_notification_email": "jmhz@example.com",
        })
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "Brigádníci (flexibilní)",
            # Odoo 20: flexibilní rozvrh je calendar_type "undefined", časové pásmo už kalendář nemá.
            "calendar_type": "undefined",
            "hours_per_day": 8,
            "full_time_required_hours": 40,
        })
        czech = cls.env.ref("base.cz")
        cls.employee = cls.env["hr.employee"].create({
            "name": "Jana Nováková",
            "jmhz_first_name": "Jana",
            "jmhz_last_name": "Nováková",
            "jmhz_birth_surname": "Nováková",
            "birthday": date(2005, 3, 1),
            "place_of_birth": "Tábor",
            "country_of_birth": czech.id,
            "country_id": czech.id,
            "sex": "female",
            "identification_id": "055301/5555",
            "private_street": "Lhota",
            "jmhz_house_number": "12",
            "private_zip": "391 11",
            "private_city": "Planá nad Lužnicí",
            "private_country_id": czech.id,
            "jmhz_health_insurer": "111",
            "jmhz_education": "K",
            "hourly_cost": 150.0,
            "tz": "Europe/Prague",
            "resource_calendar_id": cls.calendar.id,
        })
        cls.env["cz.jmhz.tax.declaration"].create({"employee_id": cls.employee.id, "date_from": date(2026, 1, 1)})
        cls.employment = cls.env["cz.jmhz.employment"].create({
            "employee_id": cls.employee.id,
            "date_contract": date(2026, 6, 10),
            "date_start": date(2026, 6, 15),
            "position_name": "Prodavačka",
            "isco_code": "52230",
            "planned_hours_month": 60,
            "id_ppv": "4002831028862",
            "registration_state": "registered",
        })
        cls.employee.jmhz_ik_mpsv = "1294704500"
        # Dvě odpolední směny po 4 h (čas v UTC, v Praze je CEST +2 h).
        cls.env["hr.attendance"].create([
            {"employee_id": cls.employee.id, "check_in": "2026-09-14 11:00:00", "check_out": "2026-09-14 15:00:00"},
            {"employee_id": cls.employee.id, "check_in": "2026-09-19 11:00:00", "check_out": "2026-09-19 15:30:00"},
        ])

    def _report(self):
        report = self.env["cz.jmhz.report"].create({"period": "2026-09-17"})
        report.action_fill_lines()
        return report

    def _xml(self, submission):
        return submission.xml_file.content

    def test_period_is_first_day(self):
        self.assertEqual(self._report().period, SEPTEMBER)

    def test_fill_loads_actual_hours_from_attendance(self):
        report = self._report()
        line = report.line_ids
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.hours, 8.5)
        self.assertEqual(line.days_worked, 2)
        self.assertTrue(line.has_attendance)
        self.assertEqual(line.hourly_rate, 150.0)

    def test_hours_are_not_derived_from_amount(self):
        line = self._report().line_ids
        line.amount = 11999
        self.assertAlmostEqual(line.hours, 8.5)
        line.amount = 1275
        self.assertAlmostEqual(line.hours, 8.5)

    def test_prepare_builds_valid_xml(self):
        report = self._report()
        report.line_ids.amount = 1275
        report.action_prepare()
        self.assertEqual(report.state, "ready")
        submission = report.submission_ids.filtered(lambda s: s.state == "ready")
        self.assertEqual(len(submission), 1)
        xml = self._xml(submission)
        self.assertEqual(xsd.validate("jmhz", xml), [])
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//n1:typPodani", namespaces=F), "R")
        self.assertEqual(tree.findtext(".//f:zuctovanoCelkem", namespaces=F), "1275")
        self.assertEqual(tree.findtext(".//f:odpracovaneHodiny/f:pocet", namespaces=F), "8.5")
        self.assertEqual(tree.findtext(".//f:idPpv", namespaces=F), "4002831028862")
        self.assertEqual(tree.findtext(".//f:danZalohaPoSleve", namespaces=F), "0")
        self.assertEqual(report.line_ids.net_amount, 1275)

    def test_without_declaration_withholding_tax(self):
        self.employee.jmhz_tax_declaration_ids.unlink()
        report = self._report()
        report.line_ids.amount = 3200
        self.assertEqual(report.line_ids.tax_mode, "withholding")
        self.assertEqual(report.line_ids.tax_amount, 480)
        self.assertEqual(report.line_ids.net_amount, 2720)
        report.action_prepare()
        tree = etree.fromstring(self._xml(report.submission_ids[:1]))
        self.assertEqual(tree.findtext(".//f:zvlastniSazbaDane/f:srazenaDan", namespaces=F), "480")
        self.assertEqual(report.withholding_total, 480)

    def test_amount_at_legal_limit_blocks(self):
        report = self._report()
        report.line_ids.amount = 12000
        self.assertTrue(report.line_ids.insured)
        self.assertEqual(report.line_ids.check_level, "error")
        with self.assertRaises(UserError):
            report.action_prepare()

    def test_unregistered_employment_blocks(self):
        self.employment.registration_state = "draft"
        report = self._report()
        report.line_ids.amount = 1000
        with self.assertRaises(UserError):
            report.action_prepare()

    def test_sent_report_is_locked_and_correction_keeps_guid(self):
        report = self._report()
        report.line_ids.amount = 1275
        report.action_prepare()
        report.action_mark_sent()
        self.assertEqual(report.state, "sent")
        self.assertTrue(report.line_ids.form_sent)
        with self.assertRaises(UserError):
            report.line_ids.amount = 2000
        guid, form_guid = report.guid, report.line_ids.form_guid

        report.action_start_correction()
        report.line_ids.amount = 1500
        report.action_prepare()
        correction = report.submission_ids.filtered(lambda s: s.state == "ready")
        self.assertEqual(correction.submission_type, "O")
        tree = etree.fromstring(self._xml(correction))
        self.assertEqual(tree.findtext(".//n1:idPodani", namespaces=F), guid)
        self.assertEqual(tree.findtext(".//n1:typPodani", namespaces=F), "O")
        self.assertEqual(tree.findtext(".//n1:idFormulare", namespaces=F), form_guid)
        self.assertEqual(tree.findtext(".//n1:typFormulare", namespaces=F), "O")

    def test_rejected_regular_submission_gets_new_guid(self):
        report = self._report()
        report.line_ids.amount = 1275
        report.action_prepare()
        report.action_mark_sent()
        guid = report.guid
        report.action_mark_rejected()
        self.assertEqual(report.state, "draft")
        report.action_prepare()
        self.assertNotEqual(report.guid, guid)
        submission = report.submission_ids.filtered(lambda s: s.state == "ready")
        self.assertEqual(submission.submission_type, "R")

    def test_edit_after_prepare_discards_xml(self):
        report = self._report()
        report.line_ids.amount = 1275
        report.action_prepare()
        report.line_ids.amount = 1300
        self.assertEqual(report.state, "draft")
        self.assertFalse(report.submission_ids.filtered(lambda s: s.state == "ready"))

    def test_print_payslip_and_payroll_record(self):
        """QWeb šablony výplatní pásky a mzdového listu se v Odoo 20 vykreslí (t-call, rodné číslo)."""
        report = self._report()
        report.line_ids.amount = 1275
        Report = self.env["ir.actions.report"]
        payslip, _kind = Report._render_qweb_html("cz_jmhz.action_report_payslip", report.line_ids.ids)
        payslip = payslip.decode()
        self.assertIn("Výplatní páska za 09/2026", payslip)
        self.assertIn("Jana Nováková", payslip)
        record, _kind = Report._render_qweb_html(
            "cz_jmhz.action_report_payroll_record", self.employee.ids, data={"year": 2026})
        record = record.decode()
        self.assertIn("Mzdový list za rok 2026", record)
        self.assertIn("055301/5555", record)
        self.assertIn("09/2026", record)
        wizard = self.env["cz.jmhz.payroll.record.wizard"].with_context(
            active_model="hr.employee", active_ids=self.employee.ids).create({"year": 2026})
        self.assertEqual(wizard.employee_ids, self.employee)
        action = wizard.with_context(discard_logo_check=True).action_print()
        self.assertEqual((action["report_name"], action["data"]), ("cz_jmhz.report_payroll_record", {"year": 2026}))

    def test_registration_submission(self):
        employment = self.env["cz.jmhz.employment"].create({
            "employee_id": self.employee.id,
            "date_contract": date(2026, 10, 1),
            "date_start": date(2026, 10, 5),
            "date_end": date(2026, 10, 31),
            "activity_code": "U",
            "position_name": "Pomocník ve stáji",
            "isco_code": "92120",
        })
        employment.action_registration()
        submission = employment.submission_ids
        self.assertEqual(submission.state, "ready")
        self.assertEqual(xsd.validate("regzec", self._xml(submission)), [])
        submission.action_mark_sent()
        self.assertEqual(employment.registration_state, "sent")
        with self.assertRaises(UserError):
            employment.action_mark_registered()
        employment.id_ppv = "4002831028999"
        employment.action_mark_registered()
        self.assertEqual(employment.registration_state, "registered")
        employment.action_deregistration()
        deregistration = employment.submission_ids.filtered(lambda s: s.regzec_action == "2")
        self.assertEqual(xsd.validate("regzec", self._xml(deregistration)), [])

    def test_registration_requires_personal_data(self):
        employee = self.env["hr.employee"].create({"name": "Petr Neúplný"})
        employment = self.env["cz.jmhz.employment"].create({
            "employee_id": employee.id, "date_start": date(2026, 10, 5), "date_contract": date(2026, 10, 1),
            "position_name": "Pomocník", "isco_code": "92120",
        })
        with self.assertRaisesRegex(UserError, "rodné příjmení"):
            employment.action_registration()

    @freeze_time("2026-10-16")
    def test_cron_creates_report_in_live_mode_only(self):
        Report = self.env["cz.jmhz.report"]
        domain = [("period", "=", SEPTEMBER), ("company_id", "=", self.company.id)]
        Report._cron_jmhz()
        self.assertFalse(Report.search(domain))
        self.company.jmhz_live_mode = True
        Report._cron_jmhz()
        report = Report.search(domain)
        self.assertEqual(len(report), 1)
        self.assertEqual(len(report.line_ids), 1)
        self.assertEqual(len(report.activity_ids), 2)  # doplnit částky + po 15. dni upozornění
        Report._cron_jmhz()
        self.assertEqual(len(report.activity_ids), 2)
