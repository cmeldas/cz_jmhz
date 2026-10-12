# -*- coding: utf-8 -*-
"""Migrace cz_jmhz 19.0.1.0.0 → 20.0.1.0.0, před načtením modulu.

Odoo 20 nahradilo ``ir.model.access`` a ``ir.rule`` jedním modelem ``ir.access``. Modul v 20 zakládá
práva i pravidla více firem v ``security/ir.access.csv`` pod **stejnými XML ID** jako v 19. Odoo při
načtení dat odmítne XML ID, které ukazuje na záznam jiného modelu (ValidationError v ``_load_records``),
proto se stará XML ID modelů ``ir.model.access`` a ``ir.rule`` před aktualizací smažou a 20 je založí
znovu jako ``ir.access``. Staré řádky v tabulkách ``ir_model_access`` a ``ir_rule`` zůstávají
(OpenUpgrade nic nemaže), Odoo 20 je nečte.

Skript je idempotentní: když rámec migrace XML ID už převedl nebo smazal, nic neudělá.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'cz_jmhz'
           AND model IN ('ir.model.access', 'ir.rule')
        RETURNING name, model
        """
    )
    removed = cr.fetchall()
    if removed:
        _logger.info(
            "cz_jmhz: smazáno %s starých XML ID práv a pravidel (založí se znovu jako ir.access): %s",
            len(removed), ", ".join(f"{name} ({model})" for name, model in removed),
        )
