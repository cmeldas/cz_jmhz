# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models

from ..lib import regzec_xml

MANAGER = "cz_jmhz.group_cz_jmhz_manager"

HEALTH_INSURERS = [
    ("111", "111 – Všeobecná zdravotní pojišťovna ČR"),
    ("201", "201 – Vojenská zdravotní pojišťovna ČR"),
    ("205", "205 – Česká průmyslová zdravotní pojišťovna"),
    ("207", "207 – Oborová zdravotní pojišťovna"),
    ("209", "209 – Zaměstnanecká pojišťovna Škoda"),
    ("211", "211 – Zdravotní pojišťovna Ministerstva vnitra ČR"),
    ("213", "213 – Revírní bratrská pokladna"),
    ("999", "999 – Ostatní"),
]

# Číselník CIS Kategorie dosaženého vzdělání (KKOV), REGZEC atribut 10091.
EDUCATION_LEVELS = [
    ("A", "A – bez vzdělání"),
    ("B", "B – neúplné základní"),
    ("C", "C – základní"),
    ("D", "D – nižší střední"),
    ("E", "E – nižší střední odborné"),
    ("H", "H – střední odborné s výučním listem"),
    ("J", "J – střední bez maturity i výučního listu"),
    ("K", "K – úplné střední všeobecné (gymnázium)"),
    ("L", "L – úplné střední odborné s vyučením i maturitou"),
    ("M", "M – úplné střední odborné s maturitou"),
    ("N", "N – vyšší odborné"),
    ("P", "P – vyšší odborné v konzervatoři"),
    ("R", "R – vysokoškolské bakalářské"),
    ("T", "T – vysokoškolské magisterské"),
    ("V", "V – vysokoškolské doktorské"),
]

PENSION_TYPES = [
    ("1", "Invalidní"),
    ("2", "Řádný starobní"),
    ("3", "Starobní se sníženým důchodovým věkem"),
]

SEX_CODES = {"male": "M", "female": "Ž"}


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    jmhz_first_name = fields.Char("Jméno", groups=MANAGER)
    jmhz_last_name = fields.Char("Příjmení", groups=MANAGER)
    jmhz_title = fields.Char("Titul", groups=MANAGER)
    jmhz_birth_surname = fields.Char("Rodné příjmení", groups=MANAGER)
    jmhz_house_number = fields.Char("Číslo popisné", groups=MANAGER, help="Ulici zapište bez čísla do adresy zaměstnance.")
    jmhz_orientation_number = fields.Char("Číslo orientační", groups=MANAGER)
    jmhz_ruian_code = fields.Char("Kód adresního místa (RÚIAN)", groups=MANAGER)
    jmhz_health_insurer = fields.Selection(HEALTH_INSURERS, "Zdravotní pojišťovna", groups=MANAGER)
    jmhz_education = fields.Selection(
        EDUCATION_LEVELS, "Nejvyšší vzdělání (KKOV)", groups=MANAGER,
        help="Když ho brigádník nedoloží ani neuvede, vyplňuje se C – základní.")
    jmhz_pension_type = fields.Selection(PENSION_TYPES, "Pobíraný důchod", groups=MANAGER)
    jmhz_pension_from = fields.Date("Důchod od", groups=MANAGER)
    jmhz_pension_early = fields.Boolean("Předčasný starobní důchod", groups=MANAGER)
    jmhz_tax_residence_id = fields.Many2one(
        "res.country", "Daňová rezidence", groups=MANAGER, default=lambda self: self.env.ref("base.cz"))
    jmhz_ik_mpsv = fields.Char(
        "Osobní identifikační číslo (OIČ)", groups=MANAGER, copy=False, tracking=True,
        help="Desetimístné číslo (IK MPSV), které ČSSZ přidělí po přihlášce. Najdete ho v protokolu nebo na "
             "ePortálu ČSSZ ve službě Seznam zaměstnanců.")
    jmhz_employment_ids = fields.One2many("cz.jmhz.employment", "employee_id", "Dohody", groups=MANAGER)
    jmhz_tax_declaration_ids = fields.One2many(
        "cz.jmhz.tax.declaration", "employee_id", "Prohlášení poplatníka", groups=MANAGER)
    jmhz_employment_count = fields.Integer(compute="_compute_jmhz_employment_count", groups=MANAGER)

    @api.depends("jmhz_employment_ids")
    def _compute_jmhz_employment_count(self):
        for employee in self:
            employee.jmhz_employment_count = len(employee.jmhz_employment_ids)

    @api.onchange("name")
    def _onchange_name_jmhz(self):
        for employee in self:
            if employee.name and not (employee.jmhz_first_name or employee.jmhz_last_name):
                first, last = self._split_name(employee.name)
                employee.jmhz_first_name = first
                employee.jmhz_last_name = last

    @staticmethod
    def _split_name(name: str) -> tuple[str, str]:
        parts = (name or "").split()
        if len(parts) < 2:
            return name or "", ""
        return " ".join(parts[:-1]), parts[-1]

    def _jmhz_name_parts(self) -> tuple[str, str]:
        self.ensure_one()
        first, last = self._split_name(self.name)
        return self.jmhz_first_name or first, self.jmhz_last_name or last

    def _jmhz_birth_number(self) -> str:
        return re.sub(r"\D", "", self.ssnid or "")

    def _jmhz_registration_errors(self) -> list[str]:
        """Co chybí pro přihlášku (REGZEC akce 1) podle povinných atributů A1-OST."""
        self.ensure_one()
        first, last = self._jmhz_name_parts()
        citizenship = self.country_id.code
        checks = [
            (first, "jméno"),
            (last, "příjmení"),
            (self.jmhz_birth_surname, "rodné příjmení"),
            (self.birthday, "datum narození"),
            (self.place_of_birth, "místo narození"),
            (self.country_of_birth, "stát narození"),
            (self.sex in SEX_CODES, "pohlaví (muž/žena)"),
            (citizenship, "státní občanství"),
            (citizenship != "CZ" or self._jmhz_birth_number(), "rodné číslo"),
            (self.private_city, "obec trvalého pobytu"),
            (self.private_zip, "PSČ trvalého pobytu"),
            (self.jmhz_house_number, "číslo popisné"),
            (self.private_country_id, "stát trvalého pobytu"),
            (self.jmhz_health_insurer, "zdravotní pojišťovna"),
            (self.jmhz_education, "nejvyšší vzdělání"),
        ]
        return [label for value, label in checks if not value]

    def _jmhz_address(self) -> regzec_xml.Address:
        self.ensure_one()
        return regzec_xml.Address(
            street=self.private_street or "",
            number=self.jmhz_house_number or "",
            orientation=self.jmhz_orientation_number or "",
            zip_code=self.private_zip or "",
            city=self.private_city or "",
            country=self.private_country_id.code or "CZ",
            ruian=self.jmhz_ruian_code or "",
        )

    def _jmhz_person(self) -> regzec_xml.Person:
        self.ensure_one()
        first, last = self._jmhz_name_parts()
        return regzec_xml.Person(
            ik_mpsv=self.jmhz_ik_mpsv or "",
            birth_number=self._jmhz_birth_number(),
            last_name=last,
            first_name=first,
            title=self.jmhz_title or "",
            birth_date=self.birthday or None,
            birth_surname=self.jmhz_birth_surname or "",
            birth_city=self.place_of_birth or "",
            birth_country=self.country_of_birth.code or "",
            sex=SEX_CODES.get(self.sex, ""),
            citizenship=self.country_id.code or "",
            address=self._jmhz_address() if self.private_city else None,
            tax_residence=self.jmhz_tax_residence_id.code or "CZ",
            health_insurer=self.jmhz_health_insurer or "",
            education=self.jmhz_education or "",
            pension_type=self.jmhz_pension_type or "",
            pension_from=self.jmhz_pension_from or None,
            pension_early=self.jmhz_pension_early,
        )

    def action_jmhz_employments(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cz_jmhz.cz_jmhz_employment_action")
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {"default_employee_id": self.id}
        return action
