"""Tests for Zigbee2MQTT expose parsing."""

from collections.abc import Callable
from typing import Any

import pytest

from custom_components.z2m_static_entities.parser import (
    ExposedEntity,
    parse_exposes,
)

FixtureLoader = Callable[[str], dict[str, Any]]


def _by_key(entities: list[ExposedEntity]) -> dict[str, ExposedEntity]:
    return {entity.key: entity for entity in entities}


@pytest.mark.parametrize(
    ("fixture_name", "expected_keys"),
    [
        pytest.param(
            "gang_1",
            {"state", "master", "backlight", "childlock", "linkquality"},
            id="one-gang",
        ),
        pytest.param(
            "gang_3",
            {
                "state_s1",
                "state_s2",
                "state_s3",
                "state_master",
                "state_backlight",
                "state_childlock",
                "linkquality",
            },
            id="three-gang",
        ),
        pytest.param(
            "gang_4",
            {
                "state_s1",
                "state_s2",
                "state_s3",
                "state_s4",
                "state_master",
                "state_backlight",
                "state_childlock",
                "linkquality",
            },
            id="four-gang",
        ),
        pytest.param(
            "gang_6",
            {
                "state_s1",
                "state_s2",
                "state_s3",
                "state_s4",
                "state_s5",
                "state_s6",
                "state_master",
                "state_backlight",
                "state_childlock",
                "linkquality",
            },
            id="six-gang",
        ),
    ],
)
def test_switch_definitions_create_every_exposed_entity(
    load_fixture: FixtureLoader,
    fixture_name: str,
    expected_keys: set[str],
) -> None:
    """Every control and diagnostic exposed by a switch is represented."""
    entities = parse_exposes(load_fixture(fixture_name))

    assert {entity.key for entity in entities} == expected_keys


@pytest.mark.parametrize("fixture_name", ["gang_1", "gang_3", "gang_4", "gang_6"])
def test_switch_configuration_and_primary_entity_categories(
    load_fixture: FixtureLoader,
    fixture_name: str,
) -> None:
    """Backlight and child lock are config; master and gangs are controls."""
    entities = _by_key(parse_exposes(load_fixture(fixture_name)))
    backlight_key = "backlight" if fixture_name == "gang_1" else "state_backlight"
    childlock_key = "childlock" if fixture_name == "gang_1" else "state_childlock"
    master_key = "master" if fixture_name == "gang_1" else "state_master"

    assert entities[backlight_key].entity_category == "config"
    assert entities[childlock_key].entity_category == "config"
    assert entities[master_key].entity_category is None
    assert entities[master_key].domain == "switch"


def test_multi_endpoint_switches_preserve_endpoint_and_description(
    load_fixture: FixtureLoader,
) -> None:
    """Composite switch exposes retain their endpoint and human description."""
    entities = _by_key(parse_exposes(load_fixture("gang_3")))

    assert entities["state_s1"].endpoint == "s1"
    assert entities["state_s1"].name == "Left Switch"
    assert entities["state_master"].endpoint == "master"
    assert entities["state_master"].name == "Master switch"
    assert entities["state_s1"].access == 7


def test_root_binary_preserves_get_capability(
    load_fixture: FixtureLoader,
) -> None:
    """Access flags remain available for command verification decisions."""
    entities = _by_key(parse_exposes(load_fixture("gang_1")))

    assert entities["state"].access == 7
    assert entities["backlight"].access == 3


def test_leak_detector_mapping(load_fixture: FixtureLoader) -> None:
    """Leak detector exposes map to sensors with HA metadata."""
    entities = _by_key(parse_exposes(load_fixture("leak_detector")))

    assert set(entities) == {
        "water_leak",
        "battery_low",
        "battery",
        "tamper",
        "linkquality",
    }
    assert entities["water_leak"].domain == "binary_sensor"
    assert entities["water_leak"].device_class == "moisture"
    assert entities["battery_low"].device_class == "battery"
    assert entities["battery_low"].entity_category == "diagnostic"
    assert entities["battery"].domain == "sensor"
    assert entities["battery"].device_class == "battery"
    assert entities["battery"].unit == "%"
    assert entities["battery"].entity_category == "diagnostic"
    assert entities["tamper"].device_class == "tamper"
    assert entities["linkquality"].entity_category == "diagnostic"


def test_smoke_detector_mapping(load_fixture: FixtureLoader) -> None:
    """Smoke detector controls and observations map to suitable domains."""
    entities = _by_key(parse_exposes(load_fixture("smoke_detector")))

    assert set(entities) == {
        "smoke",
        "battery",
        "silence",
        "test",
        "smoke_concentration",
        "device_fault",
        "linkquality",
    }
    assert entities["smoke"].domain == "binary_sensor"
    assert entities["smoke"].device_class == "smoke"
    assert entities["silence"].domain == "switch"
    assert entities["silence"].settable
    assert entities["test"].domain == "binary_sensor"
    assert entities["smoke_concentration"].unit == "ppm"
    assert entities["device_fault"].device_class == "problem"
    assert entities["linkquality"].entity_category == "diagnostic"
