# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..lib import regzec_xml

# Číselník CIS Druhů činností: pořadí souběžné dohody o provedení práce u téhož zaměstnavatele.
ACTIVITY_CODES = [
    ("T", "T – první DPP"),
    ("U", "U – druhá DPP"),
    ("V", "V – třetí DPP"),
    ("W", "W – čtvrtá DPP"),
    ("X", "X – pátá DPP"),
    ("Y", "Y – šestá DPP"),
    ("Z", "Z – sedmá DPP"),
    ("ZA", "ZA – osmá DPP"),
    ("ZB", "ZB – devátá DPP"),
    ("ZC", "ZC – desátá DPP"),
]

REGISTRATION_STATES = [
    ("draft", "Nepřihlášeno"),
    ("sent", "Přihláška podána"),
    ("registered", "Přihlášeno"),
    ("deregistration_sent", "Odhláška podána"),
    ("deregistered", "Odhlášeno"),
    ("cancelled", "Stornováno"),
]

ACTION_NAMES = {
    regzec_xml.ACTION_START: "přihláška",
    regzec_xml.ACTION_END: "odhláška",
    regzec_xml.ACTION_CHANGE: "změna údajů",
    regzec_xml.ACTION_STORNO: "storno",
}


class CzJmhzEmployment(models.Model):
    _name = "cz.jmhz.employment"
    _description = "Dohoda o provedení práce (JMHZ)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"

    name = fields.Char("Dohoda", compute="_compute_name", store=True)
    active = fields.Boolean(default=True)
    employee_id = fields.Many2one("hr.employee", "Brigádník", required=True, index=True, tracking=True)
    company_id = fields.Many2one("res.company", "Firma", required=True, default=lambda self: self.env.company)
    date_contract = fields.Date("Uzavřena", required=True, default=fields.Date.context_today)
    date_start = fields.Date(
        "Nástup", required=True, tracking=True,
        help="Den skutečného nástupu k výkonu práce. Přihláška musí odejít nejpozději před nástupem.")
    date_end = fields.Date(
        "Sjednána do", tracking=True,
        help="Den, do kterého je dohoda sjednána. Prázdné = na dobu neurčitou. Konec doporučuji dát na konec "
             "měsíce po sezóně, aby se do dohody vešlo zúčtování posledního měsíce.")
    activity_code = fields.Selection(
        ACTIVITY_CODES, "Druh činnosti", required=True, default="T",
        help="T pro první dohodu o provedení práce u zaměstnavatele; U, V… jen pro další souběžné dohody téhož brigádníka.")
    isco_code = fields.Char(
        "Kód zaměstnání CZ-ISCO",
        help="Pětimístný kód profese, např. 52230 prodavači v prodejnách, 92110 pomocní pracovníci v rostlinné "
             "výrobě, 92120 pomocní pracovníci v živočišné výrobě, 94120 pomocníci v kuchyni.")
    position_name = fields.Char("Název pozice")
    planned_hours_month = fields.Float(
        "Předpokládaný rozsah (h/měsíc)", digits=(7, 2),
        help="Uvádí se v měsíčním hlášení jako sjednaný fond pracovní doby.")
    work_city = fields.Char(
        "Místo výkonu práce", default=lambda self: self.env.company.jmhz_work_city,
        help="U dohod sídlo zaměstnavatele: název obce.")
    work_city_code = fields.Char("Kód obce", default=lambda self: self.env.company.jmhz_work_city_code)
    id_ppv = fields.Char(
        "Identifikátor zaměstnání (ID PPV)", copy=False, tracking=True,
        help="Číslo, které ČSSZ přidělí dohodě po přihlášce.")
    employee_ik_mpsv = fields.Char(
        related="employee_id.jmhz_ik_mpsv", readonly=False, string="OIČ brigádníka",
        help="Osobní identifikační číslo, které ČSSZ přidělí po první přihlášce.")
    registration_state = fields.Selection(
        REGISTRATION_STATES, "Stav u ČSSZ", required=True, default="draft", tracking=True, copy=False)
    submission_ids = fields.One2many("cz.jmhz.submission", "employment_id", "Podání")
    submission_count = fields.Integer(compute="_compute_submission_count")
    signed_document = fields.Binary("Podepsaná dohoda", attachment=True)
    signed_document_name = fields.Char("Název souboru")
    note = fields.Text("Poznámka")

    @api.depends("employee_id.name", "date_start")
    def _compute_name(self):
        for employment in self:
            start = employment.date_start.strftime("%d. %m. %Y") if employment.date_start else ""
            employment.name = f"DPP {employment.employee_id.name or ''} od {start}".strip()

    @api.depends("submission_ids")
    def _compute_submission_count(self):
        for employment in self:
            employment.submission_count = len(employment.submission_ids)

    @api.constrains("date_contract", "date_start", "date_end", "isco_code", "id_ppv", "work_city_code")
    def _check_values(self):
        for employment in self:
            if employment.date_end and employment.date_end < employment.date_start:
                raise ValidationError("Dohoda nemůže skončit dřív, než začala.")
            if employment.date_contract and employment.date_contract > employment.date_start:
                raise ValidationError("Dohoda musí být uzavřená nejpozději v den nástupu.")
            if employment.isco_code and not re.fullmatch(r"\d{5}", employment.isco_code):
                raise ValidationError("Kód CZ-ISCO má pět číslic.")
            if employment.id_ppv and not re.fullmatch(r"\d{1,22}", employment.id_ppv):
                raise ValidationError("Identifikátor zaměstnání se skládá jen z číslic.")
            if employment.work_city_code and not re.fullmatch(r"\d{6}", employment.work_city_code):
                raise ValidationError("Kód obce má šest číslic.")

    @api.model
    def _overlap_domain(self, first_day, last_day) -> list:
        return [
            ("date_start", "<=", last_day),
            "|", ("date_end", "=", False), ("date_end", ">=", first_day),
            ("registration_state", "!=", "cancelled"),
        ]

    def _jmhz_job(self) -> regzec_xml.Job:
        self.ensure_one()
        return regzec_xml.Job(
            id_ppv=self.id_ppv or "",
            contract_date=self.date_contract or None,
            start_date=self.date_start or None,
            end_date=self.date_end or None,
            activity_code=self.activity_code,
            isco=self.isco_code or "",
            position_name=self.position_name or "",
            work_city=self.work_city or "",
            work_city_code=self.work_city_code or "",
        )

    def _registration_errors(self) -> list[str]:
        self.ensure_one()
        errors = self.employee_id.sudo()._jmhz_registration_errors()
        checks = [
            (self.isco_code, "kód zaměstnání CZ-ISCO"),
            (self.position_name, "název pozice"),
            (self.work_city, "místo výkonu práce"),
            (self.work_city_code, "kód obce místa výkonu práce"),
        ]
        return errors + [label for value, label in checks if not value]

    def _create_registration(self, action: int, valid_from=None, not_started: bool = True):
        self.ensure_one()
        company = self.company_id
        company._jmhz_check_settings(registration=True)
        if action != regzec_xml.ACTION_START and not (self.employee_id.sudo().jmhz_ik_mpsv and self.id_ppv):
            raise UserError("Doplňte osobní identifikační číslo brigádníka a identifikátor zaměstnání od ČSSZ.")
        if action == regzec_xml.ACTION_START:
            errors = self._registration_errors()
            if errors:
                raise UserError("Pro přihlášku chybí: " + ", ".join(errors) + ".")
        today = fields.Date.context_today(self)
        registration = regzec_xml.Registration(
            action=action,
            ossz_code=company.jmhz_ossz_code,
            filled_on=today,
            employer_vs=company.jmhz_variable_symbol,
            employer_name=company._jmhz_employer_name(),
            person=self.employee_id.sudo()._jmhz_person(),
            job=self._jmhz_job(),
            valid_from=valid_from or today,
            not_started=not_started,
        )
        root = regzec_xml.build_regzec(
            [registration], self.env["cz.jmhz.submission"]._product_version(), company.jmhz_notification_email or "")
        return self.env["cz.jmhz.submission"]._create_from_xml(
            {
                "name": f"REGZEC {ACTION_NAMES[action]} – {self.employee_id.name}",
                "kind": "regzec",
                "regzec_action": str(action),
                "employment_id": self.id,
                "company_id": company.id,
                "xml_filename": f"REGZEC_{action}_{self.employee_id.name}_{today:%Y%m%d}.xml".replace(" ", "_"),
            },
            regzec_xml.to_bytes(root),
        )

    def _open_submission(self, submission):
        return {
            "type": "ir.actions.act_window",
            "res_model": "cz.jmhz.submission",
            "res_id": submission.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_registration(self):
        """Přihláška do evidence zaměstnanců (akce 1), nejpozději před nástupem."""
        self.ensure_one()
        if self.registration_state not in ("draft", "sent"):
            raise UserError("Dohoda už je přihlášená.")
        return self._open_submission(self._create_registration(regzec_xml.ACTION_START))

    def action_mark_registered(self):
        self.ensure_one()
        if not (self.employee_id.sudo().jmhz_ik_mpsv and self.id_ppv):
            raise UserError("Nejdřív doplňte osobní identifikační číslo brigádníka (karta brigádníka, záložka JMHZ) "
                            "a identifikátor zaměstnání z protokolu ČSSZ.")
        self.registration_state = "registered"

    def action_deregistration(self):
        """Odhláška (akce 2) do 8 dnů po uplynutí doby, na kterou byla dohoda sjednána."""
        self.ensure_one()
        if not self.date_end:
            raise UserError("Vyplňte, do kdy byla dohoda sjednána (pole Sjednána do).")
        return self._open_submission(self._create_registration(regzec_xml.ACTION_END))

    def action_change(self):
        """Změna údajů brigádníka (akce 3), např. adresa nebo zdravotní pojišťovna, do 8 dnů od změny."""
        self.ensure_one()
        return self._open_submission(self._create_registration(regzec_xml.ACTION_CHANGE))

    def action_storno(self):
        """Storno zaměstnání (akce 8): brigádník nenastoupil."""
        self.ensure_one()
        return self._open_submission(self._create_registration(regzec_xml.ACTION_STORNO))

    def action_mark_deregistered(self):
        self.write({"registration_state": "deregistered"})

    def action_view_submissions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cz_jmhz.cz_jmhz_submission_action")
        action["domain"] = [("employment_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    def _on_submission_sent(self, action: str):
        transitions = {"1": "sent", "2": "deregistration_sent", "8": "cancelled"}
        if action in transitions:
            self.registration_state = transitions[action]

    def _on_submission_accepted(self, action: str):
        if action == "2":
            self.registration_state = "deregistered"
