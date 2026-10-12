# -*- coding: utf-8 -*-
{
    "name": "JMHZ pro dohody o provedení práce (CZ)",
    "summary": "Jednotné měsíční hlášení zaměstnavatele pro brigádníky na DPP: přihlášky na ČSSZ, ruční částka za měsíc, XML podle XSD ČSSZ",
    "description": """
JMHZ pro dohody o provedení práce
=================================

Jednotné měsíční hlášení zaměstnavatele (zákon č. 323/2025 Sb.) jen pro brigádníky na dohodu
o provedení práce. Hlavní pracovní poměr ani DPČ modul nezná.

* Dohody a jejich přihlášky, odhlášky, změny a storna na ČSSZ (REGZEC 1.4.0.4).
* Měsíční hlášení (MH, XSD 1.4.3.6): částka za měsíc se zapisuje ručně, hodiny se načtou ze skutečné
  docházky nebo zapíšou ručně, nikdy se nedopočítávají z částky.
* Daň: s prohlášením poplatníka záloha se slevou, bez prohlášení srážková daň (2026) nebo záloha bez
  slevy (od 2027). Kontroly limitu, minimální mzdy, 300 hodin ročně a souladu s docházkou.
* XML se kontroluje proti XSD a stahuje k nahrání na ePortál ČSSZ. Opravná hlášení se stejným GUID.
* Výplatní páska a roční mzdový list.

Do docházky ani kiosku modul nezasahuje, docházku jen čte.
""",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "author": "Matouš Čmelík",
    "license": "LGPL-3",
    "depends": ["hr", "hr_attendance", "hr_hourly_cost", "mail"],
    "external_dependencies": {"python": ["lxml"]},
    "data": [
        "security/cz_jmhz_security.xml",
        "security/ir.model.access.csv",
        "data/cz_jmhz_year_param_data.xml",
        "data/ir_cron.xml",
        "views/cz_jmhz_report_views.xml",
        "views/cz_jmhz_employment_views.xml",
        "views/cz_jmhz_submission_views.xml",
        "views/cz_jmhz_config_views.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_views.xml",
        "views/cz_jmhz_menus.xml",
        "report/cz_jmhz_reports.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
