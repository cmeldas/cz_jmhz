# -*- coding: utf-8 -*-
"""Sestavení XML měsíčního hlášení (MH) pro dohody o provedení práce podle XSD JMHZ 1.4.3.6.

Čisté funkce bez Odoo ORM. Generuje jen formulář ``bezPriznaku`` pro DPP pod rozhodným příjmem
(vzor ``ShopNow_v1_2026-04-09.xml``, PPV3, a FAQ ČSSZ „Vyplnění ELDP v případě DPP do limitu“):

* trvání (``pojisteniOd``/``Do``) = část měsíce, kdy dohoda trvala, ``pocetDnu`` 0, bez kódu ELDP,
* příjem se uvádí jako příjem z nepojištěné činnosti, pojistné nulové,
* ``dnyEvidencniStav`` 0, stanovená týdenní doba 99, sjednaný fond = předpokládaný rozsah hodin,
* daňové části se vyplňují výlučně: s prohlášením záloha a sleva, bez prohlášení srážková daň
  (2026) nebo záloha bez slevy (od 2027). Nevyplněné části se vynechávají úplně, ani nula
  (chyby 242, 244, 245, 325 z FAQ ČSSZ).

GUID: řádné podání má nový GUID, opravné podání má GUID řádného podání a typ ``O``; opravený
formulář má GUID původního formuláře a typ ``O``, formulář, který v řádném podání nebyl, nový
GUID a typ ``R`` (FAQ ČSSZ, chyba 238).
"""
from datetime import date, datetime, timezone
from typing import NamedTuple

from lxml import etree

from .calc import TAX_DECLARATION, TAX_WITHHOLDING, WEEKLY_HOURS_NOT_APPLICABLE, TaxResult

NS_PODANI = "http://schemas.cssz.cz/JMHZ/podani/1.0"
NS_SOUHRN = "http://schemas.cssz.cz/JMHZ/souhrn/1.0"
NS_PVPOJ = "http://schemas.cssz.cz/JMHZ/PVPOJ/1.0"
NS_FORM = "http://schemas.cssz.cz/JMHZ/form/1.0"
NSMAP = {"n1": NS_PODANI, "so": NS_SOUHRN, "pvpoj": NS_PVPOJ, "form": NS_FORM}

PRODUCT_NAME = "Odoo cz_jmhz"
MAX_FORMS = 1500


class Header(NamedTuple):
    guid: str
    submission_type: str  # R řádné, O opravné
    variable_symbol: str
    year: int
    month: int
    filled_at: datetime
    product_version: str = ""
    email: str = ""


class PersonForm(NamedTuple):
    guid: str
    form_type: str  # R řádný, O opravný
    ik_mpsv: str
    id_ppv: str
    last_name: str
    first_name: str
    birth_date: date | None
    start_date: date
    activity_code: str  # druh činnosti, u DPP T, U, V…
    amount: int  # zúčtovaný příjem celkem
    bonus_amount: int  # z toho prémie a odměny nepravidelné (bonus, spropitné přes zaměstnavatele)
    vacation_amount: int  # z toho náhrada mzdy za dovolenou
    tax: TaxResult
    monthly_credit: int  # sleva na poplatníka (10299), jen s prohlášením
    net: int
    span_from: date
    span_to: date
    work_city: str
    work_city_code: str
    standard_fund: float
    planned_fund: float
    hours: float
    hourly_earnings: float
    country_code: str = "CZ"


def _sub(parent: etree._Element, namespace: str, name: str, text=None) -> etree._Element:
    element = etree.SubElement(parent, f"{{{namespace}}}{name}")
    if text is not None:
        element.text = _text(text)
    return element


def _text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return _decimal(value)
    return str(value)


def _decimal(value: float, places: int = 3) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def _form(parent: etree._Element, form: PersonForm) -> None:
    """Jeden ``formularOsoby`` s formulářem ``bezPriznaku`` pro DPP."""
    person = _sub(parent, NS_PODANI, "formularOsoby")
    header = _sub(person, NS_PODANI, "hlavicka")
    _sub(header, NS_PODANI, "idFormulare", form.guid)
    _sub(header, NS_PODANI, "typFormulare", form.form_type)
    _sub(header, NS_PODANI, "primarniPpv", True)

    body = _sub(person, NS_FORM, "bezPriznaku")
    ident = _sub(body, NS_FORM, "identifikace")
    if form.ik_mpsv and form.id_ppv:
        _sub(ident, NS_FORM, "ikMpsv", form.ik_mpsv)
        _sub(ident, NS_FORM, "idPpv", form.id_ppv)
    else:
        # Zaměstnanec ještě nemá OIČ nebo ID zaměstnání (přihláška se zpracovává).
        _sub(ident, NS_FORM, "prijmeni", form.last_name)
        _sub(ident, NS_FORM, "jmeno", form.first_name)
        _sub(ident, NS_FORM, "datumNarozeni", form.birth_date)
        _sub(ident, NS_FORM, "datumNastupu", form.start_date)
        _sub(ident, NS_FORM, "druhCinnosti", form.activity_code)

    _summary_data(body, form)

    insurance = _sub(body, NS_FORM, "pojisteni")
    duration = _sub(insurance, NS_FORM, "trvani")
    _sub(duration, NS_FORM, "pojisteniOd", form.span_from)
    _sub(duration, NS_FORM, "pojisteniDo", form.span_to)
    base = _sub(insurance, NS_FORM, "vymerovaciZaklad")
    _sub(base, NS_FORM, "prijemNepojistenaCinnost", form.amount)
    eldp = _sub(_sub(insurance, NS_FORM, "eldpSeznam"), NS_FORM, "eldp")
    _sub(eldp, NS_FORM, "pocetDnu", 0)
    employee_discount = _sub(insurance, NS_FORM, "slevaZamestnance")
    _sub(employee_discount, NS_FORM, "slevaZamestnanceEvidovana", False)
    _sub(employee_discount, NS_FORM, "slevaZamestnanceOvoZelEvidovana", False)
    employer_discount = _sub(insurance, NS_FORM, "slevaZamestnavatele")
    _sub(employer_discount, NS_FORM, "slevaZamestnavateleEvidovana", False)

    position = _sub(body, NS_FORM, "vykonavanaPozice")
    place = _sub(position, NS_FORM, "mistoVykonuPrace")
    _sub(place, NS_FORM, "obec", form.work_city)
    _sub(place, NS_FORM, "kodObce", form.work_city_code)
    _sub(place, NS_FORM, "kodStatu", form.country_code)
    _sub(position, NS_FORM, "uplatnujiPrispevekApz", False)
    _sub(position, NS_FORM, "funkcniPozitky", False)
    _sub(position, NS_FORM, "docasnePrideleniEvidovano", False)
    fund = _sub(position, NS_FORM, "fondPracovniDoby")
    _sub(fund, NS_FORM, "stanovenyFond", float(form.standard_fund))
    _sub(fund, NS_FORM, "sjednanyFond", float(form.planned_fund))
    _sub(fund, NS_FORM, "stanovenaTydenniDoba", WEEKLY_HOURS_NOT_APPLICABLE)

    progress = _sub(body, NS_FORM, "prubehZamestnani")
    _sub(_sub(progress, NS_FORM, "odpracovaneDny"), NS_FORM, "dnyEvidencniStav", 0)
    _sub(_sub(progress, NS_FORM, "odpracovaneHodiny"), NS_FORM, "pocet", float(form.hours))

    income = _sub(body, NS_FORM, "prijem")
    if form.amount > 0:
        _sub(_sub(income, NS_FORM, "dan"), NS_FORM, "zakladDane", form.tax.base)

    wage = _sub(body, NS_FORM, "mzda")
    work_wage = form.amount - form.vacation_amount
    _sub(wage, NS_FORM, "mzdaZuctovana", work_wage)
    breakdown = _sub(wage, NS_FORM, "mzdaRozpad")
    _sub(breakdown, NS_FORM, "tarif", work_wage - form.bonus_amount)
    _sub(breakdown, NS_FORM, "odmenyPravidelne", 0)
    _sub(breakdown, NS_FORM, "odmenyNepravidelne", form.bonus_amount)
    if form.vacation_amount:
        compensation = _sub(wage, NS_FORM, "nahrady")
        _sub(compensation, NS_FORM, "mzdyZuctovane", form.vacation_amount)
        _sub(compensation, NS_FORM, "dovolena", form.vacation_amount)
    _sub(_sub(wage, NS_FORM, "vydelek"), NS_FORM, "vydelekPrumernyHod", _decimal(form.hourly_earnings, 2))


def _summary_data(body: etree._Element, form: PersonForm) -> None:
    """Souhrnná data zaměstnance; dohoda je jeho jediný (primární) vztah u zaměstnavatele."""
    summary = _sub(body, NS_FORM, "souhrnDataZec")
    _sub(_sub(summary, NS_FORM, "prijmy"), NS_FORM, "zuctovanoCelkem", form.amount)
    declaration = form.tax.mode == TAX_DECLARATION
    if form.amount > 0:
        if form.tax.mode == TAX_WITHHOLDING:
            special = _sub(summary, NS_FORM, "zvlastniSazbaDane")
            _sub(special, NS_FORM, "zakladDane", form.tax.base)
            _sub(special, NS_FORM, "srazenaDan", form.tax.tax)
        else:
            advance = _sub(summary, NS_FORM, "zalohaNaDan")
            _sub(advance, NS_FORM, "zakladDane", form.tax.base)
            _sub(advance, NS_FORM, "vypoctenaZaloha", form.tax.computed)
            _sub(advance, NS_FORM, "danZalohaPoSleve", form.tax.tax)
    _sub(summary, NS_FORM, "prohlaseniPoplatnika", declaration)
    if declaration and form.amount > 0:
        _sub(_sub(summary, NS_FORM, "prohlaseniPoplatnikaDane"), NS_FORM, "zakladniSleva", form.monthly_credit)
    net = _sub(summary, NS_FORM, "mzdaCista")
    _sub(net, NS_FORM, "mzdaCista", form.net)
    _sub(net, NS_FORM, "srazkyZeMzdyEvidovany", False)
    _sub(_sub(summary, NS_FORM, "zdravPojZamestnavatel"), NS_FORM, "zdravotniPojisteni", 0)
    _sub(_sub(summary, NS_FORM, "zdravPojZamestnanec"), NS_FORM, "zdravotniPojisteni", 0)


def _pvpoj(root: etree._Element) -> None:
    """Pojistná část: dohody pod rozhodným příjmem pojistné nemají, všechno nula."""
    overview = _sub(root, NS_PVPOJ, "PVPOJ")
    premium = _sub(overview, NS_PVPOJ, "pojistne")
    for name in ("zakladZamestnavateleA", "pojistneZamestnavateleA", "zakladZamestnavateleB",
                 "zakladZamestnavateleC", "pojistneZamestnavateleCelkem", "pojistneZamestnance",
                 "pojistneCelkem"):
        _sub(premium, NS_PVPOJ, name, 0)
    _sub(overview, NS_PVPOJ, "pojistneUhrada", 0)


def build_mh(header: Header, forms: list[PersonForm]) -> etree._Element:
    """Celé měsíční hlášení: hlavička, souhrnná část, pojistná část a formuláře osob."""
    if len(forms) > MAX_FORMS:
        raise ValueError(f"Víc než {MAX_FORMS} formulářů v jednom balíku")
    root = etree.Element(f"{{{NS_PODANI}}}jmhz", nsmap=NSMAP)
    vendor = _sub(root, NS_PODANI, "VENDOR")
    vendor.set("productName", PRODUCT_NAME)
    vendor.set("productVersion", header.product_version)
    if header.email:
        _sub(root, NS_PODANI, "SENDER").set("EmailNotifikace", header.email)

    head = _sub(root, NS_PODANI, "hlavicka")
    _sub(head, NS_PODANI, "idPodani", header.guid)
    _sub(head, NS_PODANI, "typPodani", header.submission_type)
    _sub(head, NS_PODANI, "variabilniSymbol", header.variable_symbol)
    _sub(head, NS_PODANI, "mesic", header.month)
    _sub(head, NS_PODANI, "rok", header.year)
    _sub(head, NS_PODANI, "datumVyplneni", header.filled_at)
    _sub(head, NS_PODANI, "balikPoradi", 1)
    _sub(head, NS_PODANI, "balikyPocet", 1)
    # Počet formulářů včetně souhrnu a PVPOJ.
    _sub(head, NS_PODANI, "formularePocetVBaliku", len(forms) + 2)
    _sub(head, NS_PODANI, "formularePocetCelkem", len(forms) + 2)

    summary = _sub(root, NS_SOUHRN, "souhrn")
    monthly = _sub(summary, NS_SOUHRN, "danUdajeMesic")
    advances = sum(form.tax.tax for form in forms if form.tax.mode != TAX_WITHHOLDING and form.amount > 0)
    _sub(monthly, NS_SOUHRN, "danZalohaPoSleve", advances)

    _pvpoj(root)

    if forms:
        container = _sub(root, NS_PODANI, "formulareOsob")
        for form in forms:
            _form(container, form)
    return root


def to_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
