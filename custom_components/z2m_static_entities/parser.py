"""Pure logic for mapping Zigbee2MQTT `exposes` definitions to Home Assistant
entity descriptions.

This module has no Home Assistant or MQTT dependency by design: it only
transforms the JSON shape Zigbee2MQTT publishes on `<base_topic>/bridge/devices`
(each device's `definition.exposes`) into a flat list of `ExposedEntity`
records. The coordinator layer is responsible for turning these into actual
HA entities and wiring them to MQTT topics.

Two access-bit flags matter here (see const.py): ACCESS_STATE (readable) and
ACCESS_SET (settable). Exposes are mapped to a domain based on their `type`
plus these bits, not by hardcoded property/model names, so new device models
using the same expose shapes work without code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import ACCESS_SET, ACCESS_STATE

# Cosmetic-only: property name -> HA device_class. Missing entries simply
# result in an entity with no device_class, never a missing/broken entity.
_BINARY_DEVICE_CLASS_MAP: dict[str, str] = {
    "water_leak": "moisture",
    "battery_low": "battery",
    "tamper": "tamper",
    "smoke": "smoke",
    "device_fault": "problem",
    "gas": "gas",
    "carbon_monoxide": "carbon_monoxide",
    "occupancy": "motion",
    "vibration": "vibration",
    "contact": "door",
}

_NUMERIC_DEVICE_CLASS_MAP: dict[str, str] = {
    "battery": "battery",
    "temperature": "temperature",
    "humidity": "humidity",
    "illuminance": "illuminance",
    "pressure": "pressure",
    "voltage": "voltage",
    "current": "current",
    "power": "power",
    "energy": "energy",
}

# Property/endpoint keywords that mark a settable entity as a configuration
# option rather than a primary control, regardless of which device model
# exposes it or which JSON shape (raw binary vs. composite switch) was used.
_CONFIG_KEYWORDS: frozenset[str] = frozenset({"backlight", "childlock", "child_lock"})


@dataclass(frozen=True)
class ExposedEntity:
    """One Home Assistant entity derived from a single Z2M expose."""

    key: str
    domain: str
    name: str
    endpoint: str | None = None
    device_class: str | None = None
    entity_category: str | None = None
    unit: str | None = None
    value_on: Any = None
    value_off: Any = None
    settable: bool = False
    access: int = 0


def _is_config_keyword(*names: str | None) -> bool:
    return any(name and name.lower() in _CONFIG_KEYWORDS for name in names)


def _parse_binary(expose: dict[str, Any], endpoint: str | None) -> ExposedEntity:
    access = expose["access"]
    property_ = expose["property"]
    readable = bool(access & ACCESS_STATE)
    settable = bool(access & ACCESS_SET)

    domain = ("switch" if readable else "button") if settable else "binary_sensor"

    entity_category = expose.get("category")
    if _is_config_keyword(property_, endpoint):
        entity_category = "config"

    return ExposedEntity(
        key=property_,
        domain=domain,
        name=expose.get("label") or expose.get("description") or property_,
        endpoint=endpoint,
        device_class=_BINARY_DEVICE_CLASS_MAP.get(property_),
        entity_category=entity_category,
        value_on=expose.get("value_on", "ON"),
        value_off=expose.get("value_off", "OFF"),
        settable=settable,
        access=access,
    )


def _parse_numeric(expose: dict[str, Any], endpoint: str | None) -> ExposedEntity:
    access = expose["access"]
    property_ = expose["property"]
    settable = bool(access & ACCESS_SET)
    domain = "number" if settable else "sensor"

    entity_category = expose.get("category")
    if _is_config_keyword(property_, endpoint):
        entity_category = "config"

    return ExposedEntity(
        key=property_,
        domain=domain,
        name=expose.get("label") or expose.get("description") or property_,
        endpoint=endpoint,
        device_class=_NUMERIC_DEVICE_CLASS_MAP.get(property_),
        entity_category=entity_category,
        unit=expose.get("unit"),
        settable=settable,
        access=access,
    )


def _parse_enum(expose: dict[str, Any], endpoint: str | None) -> ExposedEntity:
    access = expose["access"]
    property_ = expose["property"]
    settable = bool(access & ACCESS_SET)
    domain = "select" if settable else "sensor"

    entity_category = expose.get("category")
    if _is_config_keyword(property_, endpoint):
        entity_category = "config"

    return ExposedEntity(
        key=property_,
        domain=domain,
        name=expose.get("label") or expose.get("description") or property_,
        endpoint=endpoint,
        entity_category=entity_category,
        settable=settable,
        access=access,
    )


def _parse_switch_composite(expose: dict[str, Any]) -> ExposedEntity:
    endpoint = expose.get("endpoint")
    feature = expose["features"][0]
    name = expose.get("description") or feature.get("label") or feature["property"]

    entity_category = None
    if _is_config_keyword(feature["property"], endpoint):
        entity_category = "config"

    return ExposedEntity(
        key=feature["property"],
        domain="switch",
        name=name,
        endpoint=endpoint,
        entity_category=entity_category,
        value_on=feature.get("value_on", "ON"),
        value_off=feature.get("value_off", "OFF"),
        settable=True,
        access=feature["access"],
    )


_ROOT_PARSERS = {
    "binary": _parse_binary,
    "numeric": _parse_numeric,
    "enum": _parse_enum,
}


def parse_exposes(definition: dict[str, Any]) -> list[ExposedEntity]:
    """Parse a Z2M device `definition` dict into HA entity descriptions."""
    entities: list[ExposedEntity] = []

    for expose in definition.get("exposes", []):
        expose_type = expose["type"]

        if expose_type == "switch":
            entities.append(_parse_switch_composite(expose))
            continue

        parser = _ROOT_PARSERS.get(expose_type)
        if parser is None:
            continue

        entities.append(parser(expose, expose.get("endpoint")))

    return entities
