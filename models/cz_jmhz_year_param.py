# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class CzJmhzYearParam(models.Model):
    _name = "cz.jmhz.year.param"
    _description = "JMHZ – parametry roku"
    _order = "year desc"
    _rec_name = "year"

    year = fields.Integer("Rok", required=True)
    legal_limit = fields.Integer(
        "Rozhodný příjem DPP", required=True,
        help="Od této zúčtované částky za měsíc je dohoda o provedení práce účastna pojištění (2026: 12 000 Kč).")
    taxpayer_credit = fields.Integer("Sleva na poplatníka za měsíc", required=True)
    tax_rate = fields.Float("Sazba daně (%)", required=True, default=15.0)
    withholding_tax = fields.Boolean(
        "Srážková daň u DPP pod limitem",
        help="Bez prohlášení poplatníka se z DPP pod limitem sráží srážková daň (do roku 2026). Od 2027 se "
             "místo ní strhává záloha bez slevy.")
    min_hourly_wage = fields.Float("Minimální hodinová mzda", digits=(6, 2), required=True)
    social_employer_rate = fields.Float("Sociální pojištění zaměstnavatel (%)", default=24.8)
    social_employee_rate = fields.Float("Sociální pojištění zaměstnanec (%)", default=7.1)
    health_employer_rate = fields.Float("Zdravotní pojištění zaměstnavatel (%)", default=9.0)
    health_employee_rate = fields.Float("Zdravotní pojištění zaměstnanec (%)", default=4.5)
    verified = fields.Boolean(
        "Ověřeno", help="Parametry jsou ověřené proti vyhlášeným hodnotám. Neověřené parametry hlášení jen upozorní.")
    note = fields.Text("Poznámka")

    _year_uniq = models.Constraint("unique(year)", "Parametry pro každý rok mohou být jen jednou.")

    @api.model
    def _find(self, year: int):
        return self.search([("year", "=", year)], limit=1)

    @api.model
    def _get(self, year: int):
        param = self._find(year)
        if not param:
            raise UserError(f"Chybí parametry JMHZ pro rok {year} (JMHZ → Konfigurace → Parametry roku).")
        return param
