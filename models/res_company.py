# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    jmhz_variable_symbol = fields.Char(
        "Variabilní symbol zaměstnavatele",
        help="Desetimístný variabilní symbol, který ČSSZ přidělila zaměstnavateli. Je v každém podání JMHZ.")
    jmhz_ossz_code = fields.Char(
        "Kód OSSZ",
        help="Trojmístný kód okresní správy sociálního zabezpečení (číselník C_COKR), u které je zaměstnavatel "
             "veden. Uvádí se v registraci zaměstnance.")
    jmhz_employer_name = fields.Char(
        "Název zaměstnavatele pro ČSSZ", help="Jméno zaměstnavatele v registraci zaměstnance; prázdné = název firmy.")
    jmhz_work_city = fields.Char(
        "Místo výkonu práce (obec)",
        help="U dohod se jako místo výkonu práce uvádí sídlo zaměstnavatele. Výchozí hodnota pro nové dohody.")
    jmhz_work_city_code = fields.Char("Kód obce", help="Šestimístný kód obce z číselníku obcí (RÚIAN).")
    jmhz_notification_email = fields.Char(
        "E-mail pro protokoly ČSSZ", help="Uvede se v podání; ČSSZ na něj posílá protokol o zpracování.")
    jmhz_responsible_user_id = fields.Many2one(
        "res.users", "Odpovědná osoba (JMHZ)", help="Dostává připomínky: přihlášky před nástupem, hlášení do 20. dne.")
    jmhz_live_mode = fields.Boolean(
        "Ostrý režim JMHZ",
        help="Jen v ostrém režimu cron zakládá měsíční hlášení a plánuje připomínky. Na lokálních kopiích "
             "databáze nechat vypnuté.")

    @api.constrains("jmhz_variable_symbol", "jmhz_ossz_code", "jmhz_work_city_code")
    def _check_jmhz_codes(self):
        for company in self:
            if company.jmhz_variable_symbol and not re.fullmatch(r"\d{10}", company.jmhz_variable_symbol):
                raise ValidationError("Variabilní symbol zaměstnavatele má deset číslic.")
            if company.jmhz_ossz_code and not re.fullmatch(r"[1-9]\d{2}", company.jmhz_ossz_code):
                raise ValidationError("Kód OSSZ je trojmístné číslo (100–999).")
            if company.jmhz_work_city_code and not re.fullmatch(r"\d{6}", company.jmhz_work_city_code):
                raise ValidationError("Kód obce má šest číslic.")

    def _jmhz_employer_name(self) -> str:
        self.ensure_one()
        return self.jmhz_employer_name or self.name

    def _jmhz_check_settings(self, registration: bool = False) -> None:
        """Ověří, že je vyplněné všechno, co podání potřebuje."""
        self.ensure_one()
        required = [("jmhz_variable_symbol", "variabilní symbol zaměstnavatele")]
        if registration:
            required.append(("jmhz_ossz_code", "kód OSSZ"))
        missing = [label for field, label in required if not self[field]]
        if missing:
            raise UserError("V nastavení JMHZ (JMHZ → Konfigurace → Nastavení) chybí: " + ", ".join(missing) + ".")
