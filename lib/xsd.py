# -*- coding: utf-8 -*-
"""Kontrola XML podání proti XSD schématům ČSSZ přibaleným v modulu (``data/xsd/<druh>/<verze>``)."""
import functools
from pathlib import Path

from lxml import etree

XSD_ROOT = Path(__file__).resolve().parents[1] / "data" / "xsd"
JMH_XSD_VERSION = "1.4.3.6"
REGZEC_XSD_VERSION = "1.4.0.4"

_ROOT_FILES = {
    "jmhz": "jmhzPodani.xsd",
    "regzec": "REGZEC25.xsd",
}
_DEFAULT_VERSIONS = {
    "jmhz": JMH_XSD_VERSION,
    "regzec": REGZEC_XSD_VERSION,
}


@functools.lru_cache(maxsize=None)
def _schema(kind: str, version: str) -> etree.XMLSchema:
    path = XSD_ROOT / kind / version / _ROOT_FILES[kind]
    return etree.XMLSchema(etree.parse(str(path)))


def default_version(kind: str) -> str:
    return _DEFAULT_VERSIONS[kind]


def validate(kind: str, xml: bytes, version: str | None = None) -> list[str]:
    """Vrátí seznam chyb (prázdný = XML odpovídá schématu)."""
    schema = _schema(kind, version or default_version(kind))
    try:
        document = etree.fromstring(xml)
    except etree.XMLSyntaxError as error:
        return [f"XML nejde načíst: {error}"]
    if schema.validate(document):
        return []
    return [f"řádek {error.line}: {error.message}" for error in schema.error_log]
