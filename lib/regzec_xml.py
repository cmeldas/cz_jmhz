# -*- coding: utf-8 -*-
"""Sestavení XML registrace zaměstnance (REGZEC, XSD 1.4.0.4) pro dohody o provedení práce.

Čisté funkce bez Odoo ORM. Povinnost atributů podle „Definice externí datové věty EDV 1.4.0.6“
(list Slovník, sloupce A1-OST, A2-OST, A3-OST) a „REGZEC – Všeobecné zásady pro vyplňování“
platných od 1. 7. 2026:

* akce 1 (nástup): přihláška nejpozději před nástupem k výkonu práce, nejdřív 8 dní předem,
* akce 2 (skončení): do 8 dnů po uplynutí doby, na kterou byla DPP sjednána; u dohody, ze které
  nevznikla účast na pojištění, se uvede jen důvod neposkytnutí podkladů 2,
* akce 3 (změna údajů): údaje platné ke dni změny,
* akce 8 (storno): zaměstnanec nenastoupil nebo byla přihláška omylem.

Kódy pro DPP: druh činnosti T (první DPP u zaměstnavatele), U, V… pro souběžné další;
bližší určení PPV 1 „Žádné“; postavení v zaměstnání 1221/1222 (DPP na dobu neurčitou/určitou);
pracovní režim 4 „Neuvedeno“; zaměstnání malého rozsahu N; místo výkonu práce = sídlo zaměstnavatele.
"""
from datetime import date
from typing import NamedTuple

from lxml import etree

NS = "http://schemas.cssz.cz/REGZEC/2025"

ACTION_START = 1
ACTION_END = 2
ACTION_CHANGE = 3
ACTION_STORNO = 8

POSITION_DPP_INDEFINITE = 1221
POSITION_DPP_FIXED = 1222
WORKMODE_NOT_SPECIFIED = 4
REL_DETAIL_NONE = 1
REASON_WITHOUT_INSURANCE = 2

PRODUCT_NAME = "Odoo cz_jmhz"


class Address(NamedTuple):
    street: str
    number: str  # číslo popisné
    orientation: str  # číslo orientační
    zip_code: str
    city: str
    country: str
    ruian: str = ""


class Person(NamedTuple):
    ik_mpsv: str
    birth_number: str
    last_name: str
    first_name: str
    title: str
    birth_date: date | None
    birth_surname: str
    birth_city: str
    birth_country: str
    sex: str  # M / Ž
    citizenship: str
    address: Address | None
    tax_residence: str
    health_insurer: str
    education: str  # KKOV
    pension_type: str = ""  # 1 invalidní, 2 starobní, 3 starobní se sníženým věkem
    pension_from: date | None = None
    pension_early: bool = False


class Job(NamedTuple):
    id_ppv: str
    contract_date: date | None
    start_date: date | None
    end_date: date | None
    activity_code: str
    isco: str
    position_name: str
    work_city: str
    work_city_code: str


class Registration(NamedTuple):
    action: int
    ossz_code: str
    filled_on: date
    employer_vs: str
    employer_name: str
    person: Person
    job: Job
    valid_from: date | None = None  # akce 3: platnost změny od
    not_started: bool = True  # akce 8: zaměstnanec nenastoupil


def _yes_no(value: bool) -> str:
    return "A" if value else "N"


def _set(element: etree._Element, **attributes) -> etree._Element:
    for name, value in attributes.items():
        if value is None or value is False or value == "":
            continue  # Odoo vrací prázdné hodnoty jako False
        if isinstance(value, date):
            value = value.isoformat()
        element.set(name, str(value))
    return element


def _sub(parent: etree._Element, tag: str, **attributes) -> etree._Element:
    return _set(etree.SubElement(parent, f"{{{NS}}}{tag}"), **attributes)


def _address(client: etree._Element, address: Address) -> None:
    _sub(client, "adr", str=address.street, num=address.number, onum=address.orientation,
         pnu=address.zip_code.replace(" ", ""), cit=address.city, cnt=address.country,
         ruianpoint=address.ruian)


def _client(employee: etree._Element, registration: Registration) -> None:
    person = registration.person
    action = registration.action
    with_birth_number = action in (ACTION_START, ACTION_CHANGE)
    client = _sub(employee, "client", bno=person.birth_number if with_birth_number else None,
                  ikmpsv=person.ik_mpsv)
    if action == ACTION_START:
        _sub(client, "name", sur=person.last_name, fir=person.first_name, tit=person.title)
        _sub(client, "birth", dat=person.birth_date, nam=person.birth_surname, cit=person.birth_city,
             stat=person.birth_country)
        _sub(client, "stat", mal=person.sex, cnt=person.citizenship)
        _address(client, person.address)
        _sub(client, "taxidrezid", stat=person.tax_residence)
    elif action == ACTION_CHANGE:
        _sub(client, "name", sur=person.last_name, fir=person.first_name, tit=person.title)
        _sub(client, "stat", mal=person.sex, cnt=person.citizenship)
        if person.address:
            _address(client, person.address)
        _sub(client, "taxidrezid", stat=person.tax_residence)


def _job(employee: etree._Element, registration: Registration) -> None:
    job = registration.job
    action = registration.action
    if action == ACTION_START:
        ended = bool(job.end_date and job.end_date <= registration.filled_on)
        element = _sub(
            employee, "job", fro=job.start_date, to=job.end_date if ended else None,
            rel=job.activity_code, relDetail=REL_DETAIL_NONE, sme="N",
            endbydeath="N" if ended else None, contractfro=job.contract_date,
            relat=POSITION_DPP_FIXED if job.end_date else POSITION_DPP_INDEFINITE,
            workmode=WORKMODE_NOT_SPECIFIED, cont="N", contractplace=job.work_city,
            cit=job.work_city, municode=job.work_city_code)
        _sub(element, "prof", clas=job.isco)
        _sub(element, "position", name=job.position_name, lead="N")
    elif action == ACTION_END:
        _sub(employee, "job", oid=job.id_ppv, to=job.end_date, rel=job.activity_code,
             relDetail=REL_DETAIL_NONE, endbydeath="N")
    elif action == ACTION_CHANGE:
        _sub(employee, "job", oid=job.id_ppv, rel=job.activity_code, relDetail=REL_DETAIL_NONE)
    elif action == ACTION_STORNO:
        _sub(employee, "job", oid=job.id_ppv, notstart=_yes_no(registration.not_started))


def _employee(container: etree._Element, sequence: int, registration: Registration) -> None:
    person = registration.person
    action = registration.action
    employee = _sub(container, "employee", sqnr=sequence, dep=registration.ossz_code, act=action,
                    dat=registration.filled_on,
                    fro=registration.valid_from if action == ACTION_CHANGE else None)
    _client(employee, registration)
    _sub(employee, "comp", vs=registration.employer_vs, nam=registration.employer_name)
    _job(employee, registration)
    if action == ACTION_START:
        _sub(employee, "pens", typ=person.pension_type, tak=person.pension_from,
             early=_yes_no(person.pension_early))
        _sub(employee, "insh", cnr=person.health_insurer)
        ended = bool(registration.job.end_date and registration.job.end_date <= registration.filled_on)
        if ended:
            _sub(employee, "unemplcomp", rsn=REASON_WITHOUT_INSURANCE)
        _sub(employee, "fact", highedu=person.education)
        _sub(employee, "forinreg", juris="N")
    elif action == ACTION_END:
        _sub(employee, "unemplcomp", rsn=REASON_WITHOUT_INSURANCE)
    elif action == ACTION_CHANGE:
        _sub(employee, "insh", cnr=person.health_insurer)
        _sub(employee, "fact", highedu=person.education)


def build_regzec(registrations: list[Registration], product_version: str = "", email: str = "") -> etree._Element:
    root = etree.Element(f"{{{NS}}}REGZEC", nsmap={None: NS})
    _sub(root, "VENDOR", productName=PRODUCT_NAME, productVersion=product_version)
    if email:
        _sub(root, "SENDER", EmailNotifikace=email)
    container = _sub(root, "employees")
    for sequence, registration in enumerate(registrations, start=1):
        _employee(container, sequence, registration)
    return root


def to_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
