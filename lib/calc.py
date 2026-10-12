# -*- coding: utf-8 -*-
"""Výpočty pro měsíční hlášení dohod o provedení práce: daň, pojistné, fond pracovní doby, kontroly.

Čisté funkce bez Odoo ORM, aby šly testovat samostatně. Částky jsou v celých korunách (``int``),
sazby v procentech. Pravidla podle MH – Pokyny k vyplnění měsíčního hlášení 1.4.14 a zákona o daních
z příjmů (§ 36 srážková daň, § 38h záloha na daň).
"""
import calendar
from datetime import date, timedelta
from typing import NamedTuple

TAX_DECLARATION = "declaration"  # prohlášení poplatníka: záloha se slevou na poplatníka
TAX_WITHHOLDING = "withholding"  # bez prohlášení, rok se srážkovou daní u DPP (do 2026)
TAX_ADVANCE = "advance"  # bez prohlášení od 2027: záloha bez slevy

WEEKLY_HOURS_NOT_APPLICABLE = 99  # 10261: u dohod se uvádí „missingová“ hodnota 99
HOURS_PER_WORKDAY = 8  # 10259: přepočet na 40 h týdně, 8 h za každý pracovní den včetně svátků

LEVEL_ERROR = "error"  # brání sestavení hlášení
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"


class TaxResult(NamedTuple):
    mode: str
    base: int  # základ: záloha = úhrn příjmů bez zaokrouhlení (10297), srážková = základ (10307)
    computed: int  # vypočtená záloha (10298), u srážkové daně sražená daň
    credit: int  # uplatněná část slevy na poplatníka
    tax: int  # skutečně sražená záloha po slevě (10305) nebo srážková daň (10309)


class Insurance(NamedTuple):
    social_employer: int
    social_employee: int
    health_employer: int
    health_employee: int

    @property
    def employer_total(self) -> int:
        return self.social_employer + self.health_employer

    @property
    def employee_total(self) -> int:
        return self.social_employee + self.health_employee


class Check(NamedTuple):
    level: str
    message: str


def _basis_points(rate_percent: float) -> int:
    return int(round(rate_percent * 100))


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def tax_mode(has_declaration: bool, withholding_tax: bool) -> str:
    """Režim daně podle prohlášení poplatníka a toho, zda se v roce u DPP pod limitem sráží daň."""
    if has_declaration:
        return TAX_DECLARATION
    return TAX_WITHHOLDING if withholding_tax else TAX_ADVANCE


def round_advance_base(amount: int) -> int:
    """§ 38h odst. 2 ZDP: do 100 Kč na celé koruny nahoru, nad 100 Kč na celé stokoruny nahoru."""
    if amount <= 0:
        return 0
    if amount <= 100:
        return amount
    return _ceil_div(amount, 100) * 100


def compute_tax(amount: int, mode: str, rate_percent: float, monthly_credit: int) -> TaxResult:
    """Daň z odměny za měsíc.

    Srážková daň: základ na celé koruny dolů, daň na celé koruny dolů (§ 36 odst. 3 ZDP).
    Záloha: ze zaokrouhleného základu, na celé koruny nahoru; s prohlášením se odečte sleva.
    """
    amount = max(int(amount), 0)
    bp = _basis_points(rate_percent)
    if mode == TAX_WITHHOLDING:
        tax = amount * bp // 10000
        return TaxResult(mode, amount, tax, 0, tax)
    computed = _ceil_div(round_advance_base(amount) * bp, 10000)
    credit = min(monthly_credit, computed) if mode == TAX_DECLARATION else 0
    return TaxResult(mode, amount, computed, credit, computed - credit)


def compute_insurance(amount: int, social_employer: float, social_employee: float,
                      health_employer: float, health_employee: float) -> Insurance:
    """Pojistné z celé odměny pro měsíc, kdy DPP dosáhla rozhodného příjmu.

    Sociální pojistné se zaokrouhluje na celé koruny nahoru zvlášť za zaměstnance i zaměstnavatele.
    Zdravotní pojistné se počítá z celkové sazby (zaokrouhlené nahoru), zaměstnanec platí třetinu
    celkové sazby; jeho podíl je třetina celku zaokrouhlená nahoru, zbytek platí zaměstnavatel.
    """
    amount = max(int(amount), 0)
    social_er = _ceil_div(amount * _basis_points(social_employer), 10000)
    social_ee = _ceil_div(amount * _basis_points(social_employee), 10000)
    health_total = _ceil_div(amount * _basis_points(health_employer + health_employee), 10000)
    health_ee = _ceil_div(health_total, 3)
    return Insurance(social_er, social_ee, health_total - health_ee, health_ee)


def month_bounds(period: date) -> tuple[date, date]:
    first = period.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def employment_span(period: date, date_start: date, date_end: date | None) -> tuple[date, date] | None:
    """Část měsíce, ve které dohoda trvala (10354 a 10355), nebo None, když v měsíci netrvala."""
    first, last = month_bounds(period)
    span_from = max(first, date_start)
    span_to = min(last, date_end) if date_end else last
    return (span_from, span_to) if span_from <= span_to else None


def weekday_fund(date_from: date, date_to: date, hours_per_day: int = HOURS_PER_WORKDAY) -> int:
    """Stanovený fond (10259): 8 h za každý pracovní den v období, svátky ve všední den se započítají."""
    days = (date_to - date_from).days + 1
    weekdays = sum(1 for offset in range(days) if (date_from + timedelta(days=offset)).weekday() < 5)
    return weekdays * hours_per_day


def average_hourly_earnings(hourly_rate: float, min_hourly_wage: float) -> float:
    """Průměrný hodinový výdělek (10345); pod minimální mzdou se zvyšuje na minimální mzdu."""
    return round(max(hourly_rate or 0.0, min_hourly_wage or 0.0), 2)


def line_warnings(amount: int, hours: float, legal_limit: int, min_hourly_wage: float,
                  year_hours: float, has_declaration: bool, mode: str,
                  attendance_hours: float | None = None, year_hours_limit: int = 300) -> list[Check]:
    """Kontroly jednoho řádku hlášení (jeden brigádník, jedna dohoda, jeden měsíc).

    ``year_hours`` je součet odpracovaných hodin brigádníka v roce včetně tohoto měsíce.
    ``attendance_hours`` je součet docházky za měsíc, pokud je k dispozici.
    """
    warnings = []
    if amount >= legal_limit:
        warnings.append(Check(
            LEVEL_ERROR,
            f"Odměna {amount} Kč dosáhla rozhodného příjmu {legal_limit} Kč: dohoda je v tomto měsíci účastna "
            "pojištění. Takový měsíc modul nesestaví, podejte ho ručně na ePortálu ČSSZ (pojistné, kód ELDP) "
            "a přihlaste brigádníka ke zdravotní pojišťovně."))
    if amount and hours and amount / hours < min_hourly_wage:
        warnings.append(Check(
            LEVEL_WARNING,
            f"Odměna vychází na {amount / hours:.2f} Kč/h, pod minimální mzdou {min_hourly_wage:.2f} Kč/h. "
            "V pořádku je to jen tehdy, když se část odměny za tento měsíc zúčtuje až v příštím měsíci "
            "(nejvýš o jeden měsíc)."))
    if amount and not hours:
        warnings.append(Check(LEVEL_INFO, "Odměna bez odpracovaných hodin (odměna za minulý měsíc, bonus?)."))
    if hours and not amount:
        warnings.append(Check(
            LEVEL_WARNING, "Odpracované hodiny bez odměny: odměnu je nutné zúčtovat nejpozději příští měsíc."))
    if year_hours > year_hours_limit:
        warnings.append(Check(
            LEVEL_WARNING,
            f"Letos odpracováno {year_hours:g} h, víc než {year_hours_limit} h povolených na dohodu o provedení práce."))
    if attendance_hours is not None and abs(attendance_hours - hours) > 0.01:
        warnings.append(Check(
            LEVEL_WARNING,
            f"Hodiny v hlášení ({hours:g} h) nesedí s docházkou za měsíc ({attendance_hours:g} h)."))
    if not has_declaration and amount and mode == TAX_WITHHOLDING:
        warnings.append(Check(
            LEVEL_INFO,
            "Bez prohlášení poplatníka: srážková daň 15 %, odvést finančnímu úřadu do konce příštího měsíce."))
    return warnings
