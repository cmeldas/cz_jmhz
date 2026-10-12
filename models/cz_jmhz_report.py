# -*- coding: utf-8 -*-
import uuid
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..lib import calc, jmh_xml

REPORT_STATES = [
    ("draft", "Rozpracováno"),
    ("ready", "Připraveno k podání"),
    ("sent", "Podáno"),
    ("accepted", "Přijato"),
    ("correction", "Opravuje se"),
]
LOCKED_STATES = ("sent", "accepted")
LINE_DATA_FIELDS = {
    "amount", "bonus_amount", "vacation_amount", "hours", "days_worked", "planned_hours", "hourly_rate",
    "employment_id",
}
TAX_FIELDS = (
    "has_declaration", "tax_mode", "tax_base", "tax_computed", "tax_credit", "tax_amount", "net_amount", "insured",
)
TAX_MODES = [
    (calc.TAX_DECLARATION, "Záloha se slevou (prohlášení)"),
    (calc.TAX_WITHHOLDING, "Srážková daň"),
    (calc.TAX_ADVANCE, "Záloha bez slevy"),
]
CHECK_LEVELS = [("ok", "V pořádku"), ("info", "Informace"), ("warning", "Upozornění"), ("error", "Chyba")]
_LEVEL_ORDER = {"ok": 0, "info": 1, "warning": 2, "error": 3}


def _schedule_once(record, summary: str, deadline, user) -> None:
    """Naplánuje aktivitu jen jednou (cron běží denně)."""
    if not record.activity_ids.filtered(lambda activity: activity.summary == summary):
        record.activity_schedule("mail.mail_activity_data_todo", date_deadline=deadline, summary=summary,
                                 user_id=user.id)


def _notification(title: str, message: str, kind: str):
    return {
        "type": "ir.actions.client",
        "tag": "display_notification",
        "params": {
            "title": title,
            "message": message,
            "type": kind,
            "sticky": kind != "success",
            "next": {"type": "ir.actions.client", "tag": "soft_reload"},
        },
    }


class CzJmhzReport(models.Model):
    _name = "cz.jmhz.report"
    _description = "Měsíční hlášení JMHZ"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period desc"

    name = fields.Char("Hlášení", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Firma", required=True, default=lambda self: self.env.company)
    period = fields.Date(
        "Měsíc", required=True,
        default=lambda self: (fields.Date.context_today(self) - relativedelta(months=1)).replace(day=1),
        help="Měsíc, za který se hlásí (ukládá se první den měsíce).")
    state = fields.Selection(REPORT_STATES, "Stav", required=True, default="draft", tracking=True, copy=False)
    guid = fields.Char("GUID podání", readonly=True, copy=False,
                       help="Přidělí se při první přípravě; opravná hlášení mají GUID řádného podání.")
    deadline = fields.Date("Podat do", compute="_compute_deadline", store=True)
    line_ids = fields.One2many("cz.jmhz.report.line", "report_id", "Brigádníci", copy=False)
    submission_ids = fields.One2many("cz.jmhz.submission", "report_id", "Podání", copy=False)
    submission_count = fields.Integer(compute="_compute_submission_count")
    amount_total = fields.Integer("Zúčtováno celkem", compute="_compute_totals")
    tax_total = fields.Integer("Zálohy na daň", compute="_compute_totals")
    withholding_total = fields.Integer("Srážková daň", compute="_compute_totals")
    net_total = fields.Integer("Čistá odměna celkem", compute="_compute_totals")
    hours_total = fields.Float("Hodin celkem", compute="_compute_totals")
    error_count = fields.Integer("Chyby", compute="_compute_check_counts")
    warning_count = fields.Integer("Upozornění", compute="_compute_check_counts")
    check_overview = fields.Text("Kontroly", compute="_compute_check_counts")

    _period_uniq = models.Constraint("unique(company_id, period)", "Za každý měsíc může mít firma jen jedno hlášení.")

    @api.depends("period")
    def _compute_name(self):
        for report in self:
            report.name = f"JMH {report.period:%m/%Y}" if report.period else "JMH"

    @api.depends("period")
    def _compute_deadline(self):
        for report in self:
            report.deadline = report.period + relativedelta(months=1, day=20) if report.period else False

    @api.depends("submission_ids")
    def _compute_submission_count(self):
        for report in self:
            report.submission_count = len(report.submission_ids)

    @api.depends("line_ids.amount", "line_ids.tax_amount", "line_ids.tax_mode", "line_ids.net_amount", "line_ids.hours")
    def _compute_totals(self):
        for report in self:
            lines = report.line_ids
            withholding = lines.filtered(lambda line: line.tax_mode == calc.TAX_WITHHOLDING)
            report.amount_total = sum(lines.mapped("amount"))
            report.withholding_total = sum(withholding.mapped("tax_amount"))
            report.tax_total = sum((lines - withholding).mapped("tax_amount"))
            report.net_total = sum(lines.mapped("net_amount"))
            report.hours_total = sum(lines.mapped("hours"))

    def _compute_check_counts(self):
        for report in self:
            levels = report.line_ids.mapped("check_level")
            report.error_count = levels.count("error")
            report.warning_count = levels.count("warning")
            report.check_overview = "\n\n".join(
                f"{line.employee_id.name}:\n{line.check_message}"
                for line in report.line_ids if line.check_message) or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("period"):
                vals["period"] = fields.Date.to_date(vals["period"]).replace(day=1)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("period"):
            if any(report.guid for report in self):
                raise UserError("Měsíc připraveného nebo podaného hlášení nejde změnit.")
            vals["period"] = fields.Date.to_date(vals["period"]).replace(day=1)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_sent(self):
        if self.submission_ids.filtered(lambda submission: submission.state in ("sent", "accepted")):
            raise UserError("Podané hlášení nejde smazat.")

    # --- pomocné -----------------------------------------------------------------------------

    def _month(self):
        self.ensure_one()
        return calc.month_bounds(self.period)

    def _check_editable(self):
        for report in self:
            if report.state in LOCKED_STATES:
                raise UserError("Hlášení je podané. Změny jdou jen přes Opravné hlášení.")

    def _is_correction(self) -> bool:
        self.ensure_one()
        return bool(self.submission_ids.filtered(
            lambda submission: submission.kind == "mh" and submission.state in ("sent", "accepted")))

    def _back_to_editing(self):
        """Po změně připraveného hlášení zahodí připravené XML."""
        for report in self.filtered(lambda r: r.state == "ready"):
            report.submission_ids.filtered(lambda s: s.state in ("ready", "invalid")).write({"state": "superseded"})
            report.state = "correction" if report._is_correction() else "draft"

    # --- akce ------------------------------------------------------------------------------------

    def action_fill_lines(self):
        """Doplní řádek za každou dohodu, která v měsíci trvala (i bez práce = nulový formulář)."""
        self.ensure_one()
        self._check_editable()
        first, last = self._month()
        Employment = self.env["cz.jmhz.employment"]
        employments = Employment.search([("company_id", "=", self.company_id.id)] + Employment._overlap_domain(first, last))
        new = employments - self.line_ids.employment_id
        lines = self.env["cz.jmhz.report.line"].create([{
            "report_id": self.id,
            "employment_id": employment.id,
            "planned_hours": employment.planned_hours_month,
            "hourly_rate": employment.employee_id.hourly_cost,
        } for employment in new])
        lines._load_attendance()
        return True

    def action_load_hours(self):
        """Načte skutečně odpracované hodiny a dny z docházky (přepíše ručně zapsané)."""
        self.ensure_one()
        self._check_editable()
        self.line_ids._load_attendance()
        return True

    def action_prepare(self):
        """Spočítá daň, sestaví XML a zkontroluje ho proti XSD."""
        self.ensure_one()
        if self.state in LOCKED_STATES:
            raise UserError("Hlášení je podané. Pro změnu použijte Opravné hlášení.")
        company = self.company_id
        company._jmhz_check_settings()
        if not self.line_ids:
            raise UserError("Hlášení nemá žádné řádky. Načtěte dohody.")
        param = self.env["cz.jmhz.year.param"]._get(self.period.year)
        self.line_ids._refresh_tax()
        errors = [
            f"{line.employee_id.name}: {check.message}"
            for line in self.line_ids for check in line._checks() if check.level == calc.LEVEL_ERROR
        ]
        if errors:
            raise UserError("Hlášení nejde sestavit:\n\n" + "\n".join(errors))

        correction = self._is_correction()
        submission_type = "O" if correction else "R"
        if not self.guid:
            self.guid = str(uuid.uuid4())
        lines = self.line_ids.sorted(lambda line: line.employee_id.name or "")
        forms = [line._jmh_form(correction, param) for line in lines]
        Submission = self.env["cz.jmhz.submission"]
        header = jmh_xml.Header(
            guid=self.guid,
            submission_type=submission_type,
            variable_symbol=company.jmhz_variable_symbol,
            year=self.period.year,
            month=self.period.month,
            filled_at=datetime.now(pytz.utc),
            product_version=Submission._product_version(),
            email=company.jmhz_notification_email or "",
        )
        xml = jmh_xml.to_bytes(jmh_xml.build_mh(header, forms))
        self.submission_ids.filtered(lambda s: s.state in ("ready", "invalid")).write({"state": "superseded"})
        label = "Opravné" if correction else "Řádné"
        submission = Submission._create_from_xml({
            "name": f"{label} hlášení {self.name}",
            "kind": "mh",
            "report_id": self.id,
            "company_id": company.id,
            "submission_type": submission_type,
            "guid": self.guid,
            "xml_filename": f"JMH_{self.period:%Y_%m}_{submission_type}_{fields.Date.context_today(self):%Y%m%d}.xml",
        }, xml)
        if submission.state != "ready":
            return _notification("XML neprošlo kontrolou XSD", submission.xsd_errors, "danger")
        self.state = "ready"
        return _notification(
            f"{label} hlášení je připravené",
            "Stáhněte XML a nahrajte ho na ePortál ČSSZ ve službě „Podání nahráním dat z účetního systému“. "
            "Po odeslání označte hlášení jako podané.",
            "success")

    def _ready_submission(self):
        self.ensure_one()
        submission = self.submission_ids.filtered(lambda s: s.kind == "mh" and s.state == "ready")[:1]
        if not submission:
            raise UserError("Hlášení nemá připravené XML. Nejdřív ho připravte.")
        return submission

    def action_download(self):
        return self._ready_submission().action_download()

    def action_mark_sent(self):
        self._ready_submission().action_mark_sent()

    def action_mark_accepted(self):
        submission = self.submission_ids.filtered(lambda s: s.kind == "mh" and s.state == "sent")[:1]
        if not submission:
            raise UserError("Hlášení nemá podané XML.")
        submission.action_mark_accepted()

    def action_mark_rejected(self):
        submission = self.submission_ids.filtered(lambda s: s.kind == "mh" and s.state == "sent")[:1]
        if not submission:
            raise UserError("Hlášení nemá podané XML.")
        submission.action_mark_rejected()

    def action_start_correction(self):
        """Otevře podané hlášení pro opravu; opravné podání má GUID řádného podání."""
        for report in self:
            if report.state not in LOCKED_STATES:
                raise UserError("Opravovat lze jen podané hlášení.")
            report.state = "correction"

    def action_print_payslips(self):
        self.ensure_one()
        return self.env.ref("cz_jmhz.action_report_payslip").report_action(self.line_ids)

    def action_view_submissions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cz_jmhz.cz_jmhz_submission_action")
        action["domain"] = [("report_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    # --- reakce na stav podání ---------------------------------------------------------------------

    def _on_submission_sent(self, submission):
        self.state = "sent"
        self.line_ids.write({"form_sent": True})

    def _on_submission_accepted(self, submission):
        self.state = "accepted"

    def _on_submission_rejected(self, submission):
        if submission.submission_type == "R":
            # Zamítnuté řádné podání: podává se znovu jako nové řádné s novým GUID.
            self.guid = False
            self.line_ids.write({"form_guid": False, "form_sent": False, "form_rejected": False})
            self.state = "draft"
        else:
            # Zamítnuté opravné podání: nové opravné s GUID řádného podání.
            self.state = "correction"

    # --- cron ----------------------------------------------------------------------------------------

    @api.model
    def _cron_jmhz(self):
        """Denně: založí hlášení za minulý měsíc a připomene lhůty (jen firmy v ostrém režimu)."""
        today = fields.Date.context_today(self)
        previous = (today - relativedelta(months=1)).replace(day=1)
        first, last = calc.month_bounds(previous)
        deadline = previous + relativedelta(months=1, day=20)
        Employment = self.env["cz.jmhz.employment"]
        for company in self.env["res.company"].search([("jmhz_live_mode", "=", True)]):
            user = company.jmhz_responsible_user_id or self.env.ref("base.user_admin")
            company_domain = [("company_id", "=", company.id)]
            report = self.search(company_domain + [("period", "=", previous)], limit=1)
            if not report and Employment.search_count(company_domain + Employment._overlap_domain(first, last)):
                report = self.create({"company_id": company.id, "period": previous})
                report.action_fill_lines()
            if report and report.state not in LOCKED_STATES:
                _schedule_once(report, f"Doplnit částky a podat hlášení do {deadline:%d. %m. %Y}", deadline, user)
                if today.day >= 15:
                    _schedule_once(report, "Hlášení ještě není podané, lhůta je 20. dne", deadline, user)
            for employment in Employment.search(company_domain + [
                    ("registration_state", "=", "draft"), ("date_start", "<=", today + timedelta(days=8))]):
                _schedule_once(employment, "Podat přihlášku na ČSSZ nejpozději před nástupem", employment.date_start, user)
            for employment in Employment.search(company_domain + [
                    ("registration_state", "=", "registered"), ("date_end", "<", today)]):
                _schedule_once(employment, "Podat odhlášku na ČSSZ (do 8 dnů od konce dohody)",
                               employment.date_end + timedelta(days=8), user)


class CzJmhzReportLine(models.Model):
    _name = "cz.jmhz.report.line"
    _description = "Řádek měsíčního hlášení JMHZ"
    _order = "report_id, id"

    report_id = fields.Many2one("cz.jmhz.report", "Hlášení", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="report_id.company_id", store=True)
    period = fields.Date(related="report_id.period", store=True)
    report_state = fields.Selection(related="report_id.state")
    employment_id = fields.Many2one("cz.jmhz.employment", "Dohoda", required=True, ondelete="restrict")
    employee_id = fields.Many2one(related="employment_id.employee_id", store=True, string="Brigádník")
    amount = fields.Integer(
        "Zúčtováno (Kč)",
        help="Odměna zúčtovaná za tento měsíc, zapisuje se ručně. Odměnu za práci v měsíci je nutné zúčtovat "
             "nejpozději v měsíci následujícím.")
    bonus_amount = fields.Integer(
        "Z toho bonusy (Kč)", help="Prémie a odměny nepravidelné, např. bonus nebo spropitné rozdělované zaměstnavatelem.")
    vacation_amount = fields.Integer(
        "Z toho dovolená (Kč)", help="Náhrada odměny za dovolenou (čerpanou nebo proplacenou při skončení dohody).")
    hours = fields.Float(
        "Odpracováno (h)", digits=(8, 2),
        help="Skutečně odpracované hodiny v měsíci, bez dovolené. Načtou se z docházky, nebo se zapíšou ručně. "
             "Z částky se nedopočítávají.")
    days_worked = fields.Integer("Odpracované dny")
    has_attendance = fields.Boolean("Hodiny z docházky", readonly=True)
    planned_hours = fields.Float(
        "Předpokládaný rozsah (h)", digits=(7, 2), help="Sjednaný fond pracovní doby: předpokládaný rozsah práce v měsíci.")
    hourly_rate = fields.Float("Hodinová sazba", digits=(8, 2), help="Uvádí se jako průměrný hodinový výdělek.")
    date_from = fields.Date("Od", compute="_compute_span", store=True)
    date_to = fields.Date("Do", compute="_compute_span", store=True)
    standard_fund = fields.Float("Stanovený fond (h)", compute="_compute_span", store=True)
    has_declaration = fields.Boolean("Prohlášení", compute="_compute_tax_fields", store=True)
    tax_mode = fields.Selection(TAX_MODES, "Daň", compute="_compute_tax_fields", store=True)
    tax_base = fields.Integer("Základ daně", compute="_compute_tax_fields", store=True)
    tax_computed = fields.Integer("Vypočtená daň", compute="_compute_tax_fields", store=True)
    tax_credit = fields.Integer("Sleva", compute="_compute_tax_fields", store=True)
    tax_amount = fields.Integer("Daň (Kč)", compute="_compute_tax_fields", store=True)
    net_amount = fields.Integer("Čistá odměna (Kč)", compute="_compute_tax_fields", store=True)
    insured = fields.Boolean("Nad limitem", compute="_compute_tax_fields", store=True)
    form_guid = fields.Char("GUID formuláře", readonly=True, copy=False)
    form_sent = fields.Boolean("Formulář podán", readonly=True, copy=False)
    form_rejected = fields.Boolean(
        "Formulář zamítnut", copy=False,
        help="Zaškrtněte, když ČSSZ v protokolu zamítla formulář tohoto brigádníka. V opravném hlášení dostane "
             "nový GUID a typ řádný.")
    check_level = fields.Selection(CHECK_LEVELS, "Kontrola", compute="_compute_checks")
    check_message = fields.Text("Kontroly", compute="_compute_checks")

    _employment_uniq = models.Constraint("unique(report_id, employment_id)", "Dohoda je v hlášení už jednou.")

    @api.depends("report_id.period", "employment_id.date_start", "employment_id.date_end")
    def _compute_span(self):
        for line in self:
            span = None
            if line.report_id.period and line.employment_id.date_start:
                span = calc.employment_span(line.report_id.period, line.employment_id.date_start,
                                            line.employment_id.date_end)
            line.date_from, line.date_to = span or (False, False)
            line.standard_fund = calc.weekday_fund(*span) if span else 0.0

    @api.depends("amount", "employee_id", "report_id.period",
                 "employee_id.jmhz_tax_declaration_ids.date_from", "employee_id.jmhz_tax_declaration_ids.date_to")
    def _compute_tax_fields(self):
        Param = self.env["cz.jmhz.year.param"].sudo()
        Declaration = self.env["cz.jmhz.tax.declaration"].sudo()
        for line in self:
            period = line.report_id.period
            param = Param._find(period.year) if period else Param
            if not (period and line.employee_id and param):
                line.update({name: False for name in TAX_FIELDS})
                continue
            first, last = calc.month_bounds(period)
            declaration = Declaration._covers(line.employee_id, first, last)
            mode = calc.tax_mode(declaration, param.withholding_tax)
            tax = calc.compute_tax(line.amount, mode, param.tax_rate, param.taxpayer_credit)
            line.update({
                "has_declaration": declaration,
                "tax_mode": mode,
                "tax_base": tax.base,
                "tax_computed": tax.computed,
                "tax_credit": tax.credit,
                "tax_amount": tax.tax,
                "net_amount": line.amount - tax.tax,
                "insured": line.amount >= param.legal_limit,
            })

    def _refresh_tax(self):
        """Přepočítá daň (např. po změně ročních parametrů, na kterých výpočet nezávisí přes depends)."""
        for name in TAX_FIELDS:
            self.env.add_to_compute(self._fields[name], self)
        self._recompute_recordset(TAX_FIELDS)

    @api.depends("amount", "bonus_amount", "vacation_amount", "hours", "has_attendance", "tax_mode", "insured",
                 "date_from", "employment_id.registration_state", "employment_id.id_ppv")
    def _compute_checks(self):
        for line in self:
            checks = line._checks()
            level = max((check.level for check in checks), key=_LEVEL_ORDER.get, default="ok")
            line.check_level = level
            line.check_message = "\n".join(f"• {check.message}" for check in checks) or False

    def _attendance_summary(self) -> tuple[bool, float, int]:
        """Docházka brigádníka v části měsíce, kdy dohoda trvala: (je docházka, hodiny, dny)."""
        self.ensure_one()
        if not (self.date_from and self.date_to):
            return False, 0.0, 0
        tz = pytz.timezone(self.employee_id.tz or self.env.user.tz or "Europe/Prague")
        start = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = tz.localize(datetime.combine(self.date_to + timedelta(days=1), time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        attendances = self.env["hr.attendance"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("check_in", ">=", start),
            ("check_in", "<", end),
            ("check_out", "!=", False),
        ])
        hours = round(sum(attendances.mapped("worked_hours")), 2)
        days = len({pytz.utc.localize(attendance.check_in).astimezone(tz).date() for attendance in attendances})
        return bool(attendances), hours, days

    def _load_attendance(self):
        for line in self:
            found, hours, days = line._attendance_summary()
            if found:
                line.write({"hours": hours, "days_worked": days, "has_attendance": True})
            else:
                line.has_attendance = False

    def _checks(self) -> list[calc.Check]:
        self.ensure_one()
        period = self.report_id.period
        if not period:
            return []
        param = self.env["cz.jmhz.year.param"].sudo()._find(period.year)
        if not param:
            return [calc.Check(calc.LEVEL_ERROR, f"Chybí parametry JMHZ pro rok {period.year}.")]
        checks = []
        if not param.verified:
            checks.append(calc.Check(
                calc.LEVEL_WARNING, f"Parametry roku {period.year} nejsou ověřené (JMHZ → Konfigurace → Parametry roku)."))
        employment = self.employment_id
        employee = self.employee_id.sudo()
        if not self.date_from:
            checks.append(calc.Check(calc.LEVEL_ERROR, "Dohoda v tomto měsíci netrvala."))
        if employment.registration_state == "draft":
            checks.append(calc.Check(
                calc.LEVEL_ERROR,
                "Dohoda není přihlášená na ČSSZ. Přihláška musí odejít nejpozději před nástupem; podejte ji na dohodě."))
        elif not (employee.jmhz_ik_mpsv and employment.id_ppv):
            first, last = employee._jmhz_name_parts()
            if first and last and employee.birthday:
                checks.append(calc.Check(
                    calc.LEVEL_WARNING,
                    "Chybí OIČ nebo identifikátor zaměstnání od ČSSZ; formulář se pošle s identifikací jménem a "
                    "datem narození."))
            else:
                checks.append(calc.Check(
                    calc.LEVEL_ERROR, "Chybí OIČ a identifikátor zaměstnání a pro náhradní identifikaci i jméno nebo "
                                      "datum narození."))
        if not (employment.work_city and employment.work_city_code):
            checks.append(calc.Check(calc.LEVEL_ERROR, "Dohoda nemá místo výkonu práce a kód obce."))
        if self.bonus_amount < 0 or self.vacation_amount < 0 or self.amount < 0:
            checks.append(calc.Check(calc.LEVEL_ERROR, "Částky nesmí být záporné."))
        if self.bonus_amount + self.vacation_amount > self.amount:
            checks.append(calc.Check(calc.LEVEL_ERROR, "Bonusy a dovolená jsou dohromady víc než celková odměna."))
        year_lines = self.search([
            ("employee_id", "=", self.employee_id.id),
            ("period", ">=", period.replace(month=1, day=1)),
            ("period", "<=", period.replace(month=12, day=31)),
            ("id", "!=", self._origin.id or 0),
        ])
        year_hours = sum(year_lines.mapped("hours")) + self.hours
        attendance_hours = None
        if self.has_attendance:
            attendance_hours = self._attendance_summary()[1]
        checks += calc.line_warnings(
            amount=self.amount, hours=self.hours, legal_limit=param.legal_limit,
            min_hourly_wage=param.min_hourly_wage, year_hours=year_hours, has_declaration=self.has_declaration,
            mode=self.tax_mode, attendance_hours=attendance_hours)
        return checks

    def _jmh_form(self, correction: bool, param) -> jmh_xml.PersonForm:
        self.ensure_one()
        if not self.form_guid or self.form_rejected:
            self.write({"form_guid": str(uuid.uuid4()), "form_rejected": False, "form_sent": False})
        employee = self.employee_id.sudo()
        employment = self.employment_id
        first, last = employee._jmhz_name_parts()
        return jmh_xml.PersonForm(
            guid=self.form_guid,
            form_type="O" if correction and self.form_sent else "R",
            ik_mpsv=employee.jmhz_ik_mpsv or "",
            id_ppv=employment.id_ppv or "",
            last_name=last,
            first_name=first,
            birth_date=employee.birthday or None,
            start_date=employment.date_start,
            activity_code=employment.activity_code,
            amount=self.amount,
            bonus_amount=self.bonus_amount,
            vacation_amount=self.vacation_amount,
            tax=calc.TaxResult(self.tax_mode, self.tax_base, self.tax_computed, self.tax_credit, self.tax_amount),
            monthly_credit=param.taxpayer_credit,
            net=self.net_amount,
            span_from=self.date_from,
            span_to=self.date_to,
            work_city=employment.work_city,
            work_city_code=employment.work_city_code,
            standard_fund=self.standard_fund,
            planned_fund=self.planned_hours,
            hours=self.hours,
            hourly_earnings=calc.average_hourly_earnings(self.hourly_rate, param.min_hourly_wage),
        )

    # --- zámek podaných hlášení ------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        reports = self.env["cz.jmhz.report"].browse([vals["report_id"] for vals in vals_list if vals.get("report_id")])
        reports._check_editable()
        lines = super().create(vals_list)
        lines.report_id._back_to_editing()
        return lines

    def write(self, vals):
        touches_data = bool(LINE_DATA_FIELDS & set(vals))
        if touches_data:
            self.report_id._check_editable()
        result = super().write(vals)
        if touches_data:
            self.report_id._back_to_editing()
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_sent(self):
        self.report_id._check_editable()
        if self.filtered("form_sent"):
            raise UserError("Formulář brigádníka už byl podán. Místo smazání nastavte v opravném hlášení částku a hodiny na 0.")
