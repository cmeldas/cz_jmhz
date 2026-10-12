# -*- coding: utf-8 -*-
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from lxml import etree

from odoo.tests import BaseCase, tagged

from odoo.addons.cz_jmhz.lib import calc, jmh_xml, regzec_xml, xsd

MODULE_DIR = Path(xsd.__file__).resolve().parents[1]
SHOPNOW_EXAMPLE = MODULE_DIR / "tests" / "files" / "ShopNow_v1_2026-04-09.xml"
F = {"f": jmh_xml.NS_FORM, "n1": jmh_xml.NS_PODANI}


def person_form(amount, mode, ids=True, form_type="R", hours=40.0):
    tax = calc.compute_tax(amount, mode, 15.0, 2570)
    span = calc.employment_span(date(2026, 9, 1), date(2026, 6, 15), None)
    return jmh_xml.PersonForm(
        guid=str(uuid.uuid4()), form_type=form_type,
        ik_mpsv="1294704500" if ids else "", id_ppv="4002831028862" if ids else "",
        last_name="Nováková", first_name="Jana", birth_date=date(2005, 3, 1), start_date=date(2026, 6, 15),
        activity_code="T", amount=amount, bonus_amount=0, vacation_amount=0, tax=tax, monthly_credit=2570,
        net=amount - tax.tax, span_from=span[0], span_to=span[1], work_city="Planá nad Lužnicí",
        work_city_code="552917", standard_fund=calc.weekday_fund(*span), planned_fund=60.0, hours=hours,
        hourly_earnings=150.0)


def build(forms, submission_type="R"):
    header = jmh_xml.Header(
        guid=str(uuid.uuid4()), submission_type=submission_type, variable_symbol="1234567890", year=2026, month=9,
        filled_at=datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc), product_version="19.0.1.0.0", email="a@b.cz")
    return jmh_xml.to_bytes(jmh_xml.build_mh(header, forms))


@tagged("post_install", "-at_install")
class TestJmhXml(BaseCase):

    def assertValid(self, xml, kind="jmhz"):
        self.assertEqual(xsd.validate(kind, xml), [])

    def test_official_example_passes_bundled_xsd(self):
        self.assertValid(SHOPNOW_EXAMPLE.read_bytes())

    def test_declaration_fills_only_advance(self):
        xml = build([person_form(11999, calc.TAX_DECLARATION)])
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//f:zalohaNaDan/f:vypoctenaZaloha", namespaces=F), "1800")
        self.assertEqual(tree.findtext(".//f:zalohaNaDan/f:danZalohaPoSleve", namespaces=F), "0")
        self.assertEqual(tree.findtext(".//f:zakladniSleva", namespaces=F), "2570")
        self.assertIsNone(tree.find(".//f:zvlastniSazbaDane", namespaces=F))

    def test_withholding_fills_only_special_rate(self):
        xml = build([person_form(11999, calc.TAX_WITHHOLDING)])
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//f:zvlastniSazbaDane/f:srazenaDan", namespaces=F), "1799")
        self.assertIsNone(tree.find(".//f:zalohaNaDan", namespaces=F))
        self.assertIsNone(tree.find(".//f:prohlaseniPoplatnikaDane", namespaces=F))
        self.assertEqual(tree.findtext(".//f:prohlaseniPoplatnika", namespaces=F), "false")

    def test_advance_without_credit(self):
        xml = build([person_form(11999, calc.TAX_ADVANCE)])
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//f:danZalohaPoSleve", namespaces=F), "1800")
        self.assertIsNone(tree.find(".//f:prohlaseniPoplatnikaDane", namespaces=F))

    def test_dpp_under_limit_has_no_eldp_code(self):
        tree = etree.fromstring(build([person_form(6400, calc.TAX_DECLARATION, hours=16.0)]))
        self.assertIsNone(tree.find(".//f:eldp/f:kod", namespaces=F))
        self.assertEqual(tree.findtext(".//f:eldp/f:pocetDnu", namespaces=F), "0")
        self.assertEqual(tree.findtext(".//f:prijemNepojistenaCinnost", namespaces=F), "6400")
        self.assertEqual(tree.findtext(".//f:dnyEvidencniStav", namespaces=F), "0")
        self.assertEqual(tree.findtext(".//f:stanovenaTydenniDoba", namespaces=F), "99")
        self.assertEqual(tree.findtext(".//f:odpracovaneHodiny/f:pocet", namespaces=F), "16")

    def test_zero_month(self):
        xml = build([person_form(0, calc.TAX_DECLARATION, hours=0.0)])
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertIsNone(tree.find(".//f:zalohaNaDan", namespaces=F))
        self.assertIsNone(tree.find(".//f:prijem/f:dan", namespaces=F))

    def test_identification_without_ids(self):
        xml = build([person_form(6000, calc.TAX_DECLARATION, ids=False)])
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//f:identifikace/f:druhCinnosti", namespaces=F), "T")
        self.assertIsNone(tree.find(".//f:identifikace/f:ikMpsv", namespaces=F))

    def test_correction_and_counts(self):
        xml = build([person_form(5000, calc.TAX_DECLARATION, form_type="O"),
                     person_form(3000, calc.TAX_WITHHOLDING)], submission_type="O")
        self.assertValid(xml)
        tree = etree.fromstring(xml)
        self.assertEqual(tree.findtext(".//n1:hlavicka/n1:typPodani", namespaces=F), "O")
        self.assertEqual(tree.findtext(".//n1:formularePocetCelkem", namespaces=F), "4")
        self.assertEqual([el.text for el in tree.iterfind(".//n1:typFormulare", namespaces=F)], ["O", "R"])
        # Souhrn obsahuje jen zálohy, ne srážkovou daň.
        self.assertEqual(tree.findtext(".//{%s}danZalohaPoSleve" % jmh_xml.NS_SOUHRN), "0")


@tagged("post_install", "-at_install")
class TestRegzecXml(BaseCase):

    def registration(self, action):
        address = regzec_xml.Address("Lhota", "12", "", "391 11", "Planá nad Lužnicí", "CZ")
        person = regzec_xml.Person(
            "" if action == 1 else "1234567890", "0553015555", "Nováková", "Jana", "", date(2005, 3, 1),
            "Nováková", "Tábor", "CZ", "Ž", "CZ", address, "CZ", "111", "K")
        job = regzec_xml.Job(
            "" if action == 1 else "4002831028862", date(2026, 6, 10), date(2026, 6, 15), date(2026, 9, 30), "T",
            "52230", "Prodavačka", "Planá nad Lužnicí", "552917")
        return regzec_xml.Registration(action, "317", date(2026, 6, 12), "1234567890", "Zaměstnavatel", person, job,
                                       valid_from=date(2026, 7, 1))

    def test_all_actions_valid(self):
        for action in (regzec_xml.ACTION_START, regzec_xml.ACTION_END, regzec_xml.ACTION_CHANGE,
                       regzec_xml.ACTION_STORNO):
            with self.subTest(action=action):
                xml = regzec_xml.to_bytes(regzec_xml.build_regzec([self.registration(action)]))
                self.assertEqual(xsd.validate("regzec", xml), [])

    def test_start_codes_for_dpp(self):
        xml = regzec_xml.to_bytes(regzec_xml.build_regzec([self.registration(regzec_xml.ACTION_START)])).decode()
        self.assertRegex(xml, r'rel="T"')
        self.assertRegex(xml, r'relat="1222"')  # DPP na dobu určitou
        self.assertRegex(xml, r'workmode="4"')
        self.assertRegex(xml, r'pnu="39111"')
        self.assertIsNone(re.search(r"unemplcomp", xml))  # dohoda ještě neskončila

    def test_end_without_insurance_reason(self):
        xml = regzec_xml.to_bytes(regzec_xml.build_regzec([self.registration(regzec_xml.ACTION_END)])).decode()
        self.assertIn('rsn="2"', xml)
        self.assertNotIn("bno=", xml)

    def test_odoo_false_values_are_skipped(self):
        registration = self.registration(regzec_xml.ACTION_START)
        registration = registration._replace(person=registration.person._replace(pension_from=False, title=False))
        xml = regzec_xml.to_bytes(regzec_xml.build_regzec([registration])).decode()
        self.assertNotIn("False", xml)
        self.assertEqual(xsd.validate("regzec", xml.encode()), [])
