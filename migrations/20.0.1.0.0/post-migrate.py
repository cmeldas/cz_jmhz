# -*- coding: utf-8 -*-
"""Migrace cz_jmhz 19.0.1.0.0 → 20.0.1.0.0, po načtení modulu.

V Odoo 19 modul četl rodné číslo brigádníka ze standardního pole ``ssnid`` (hr.version). Odoo 20 pole
``ssnid`` zrušilo; rodné číslo je teď standardní identifikační číslo ``identification_id`` (také
na hr.version). Sloupec ``hr_version.ssnid`` při migraci zůstává (OpenUpgrade sloupce nemaže, standardní
Odoo ho smaže až v ``_process_end`` po všech post skriptech), takže se rodná čísla dají převést.

Převádí se jen u brigádníků s dohodou JMHZ a jen tam, kde ``identification_id`` je prázdné. Kde jsou
vyplněná obě pole a liší se, skript nic nepřepíše a jen to zaloguje (rozhodne člověk). Ostatním
zaměstnancům se ``ssnid`` nepřevádí, počet se jen zaloguje.

Idempotentní: druhý běh nic nezmění.
"""
import logging

from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    if not (column_exists(cr, "hr_version", "ssnid") and table_exists(cr, "cz_jmhz_employment")):
        return

    jmhz_versions = """
        SELECT v.id
          FROM hr_version v
         WHERE v.employee_id IN (SELECT employee_id FROM cz_jmhz_employment)
           AND NULLIF(TRIM(v.ssnid), '') IS NOT NULL
    """
    cr.execute(
        f"""
        UPDATE hr_version
           SET identification_id = TRIM(ssnid)
         WHERE id IN ({jmhz_versions})
           AND NULLIF(TRIM(identification_id), '') IS NULL
        RETURNING id
        """
    )
    copied = [row[0] for row in cr.fetchall()]
    if copied:
        _logger.info("cz_jmhz: rodné číslo převedeno ze ssnid do identification_id u %s verzí zaměstnanců: %s",
                     len(copied), copied)

    cr.execute(
        f"""
        SELECT id, employee_id
          FROM hr_version
         WHERE id IN ({jmhz_versions})
           AND regexp_replace(identification_id, '\\D', '', 'g') <> regexp_replace(ssnid, '\\D', '', 'g')
        """
    )
    conflicts = cr.fetchall()
    if conflicts:
        _logger.warning(
            "cz_jmhz: u %s verzí zaměstnanců je identification_id jiné než dřívější ssnid (rodné číslo pro JMHZ); "
            "nepřepsáno, zkontrolujte ručně (hr_version.id, employee_id): %s", len(conflicts), conflicts,
        )

    cr.execute(
        """
        SELECT count(*)
          FROM hr_version
         WHERE NULLIF(TRIM(ssnid), '') IS NOT NULL
           AND employee_id NOT IN (SELECT employee_id FROM cz_jmhz_employment)
        """
    )
    others = cr.fetchone()[0]
    if others:
        _logger.warning(
            "cz_jmhz: %s verzí zaměstnanců bez dohody JMHZ má vyplněné pole ssnid, které Odoo 20 zrušilo; modul je "
            "nepřevádí, v Odoo 20 nebudou vidět (zůstanou jen ve sloupci hr_version.ssnid, pokud ho migrace nesmaže).",
            others,
        )
