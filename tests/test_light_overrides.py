"""Tests for native-light entity overrides."""

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.z2m_static_entities.const import (
    CONF_BASE_TOPICS,
    CONF_LIGHT_ENTITIES,
    CONF_RELIABLE_ENTITIES,
    CONF_STALE_DAYS,
    DOMAIN,
)
from custom_components.z2m_static_entities.runtime import Z2MRuntime

FixtureLoader = Callable[[str], dict[str, Any]]
IEEE = "0x00124b0024abcdef"
STATE_S1 = f"{IEEE}|state_s1"


def _runtime(
    hass: HomeAssistant,
    definition: dict[str, Any],
    *,
    light_entities: list[str] | None = None,
    reliable_entities: list[str] | None = None,
) -> tuple[Z2MRuntime, MockConfigEntry]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BASE_TOPICS: ["zigbee2mqtt"],
            CONF_STALE_DAYS: 30,
        },
        options={
            CONF_LIGHT_ENTITIES: light_entities or [],
            CONF_RELIABLE_ENTITIES: reliable_entities or [],
        },
    )
    entry.add_to_hass(hass)
    runtime = Z2MRuntime(hass, entry)
    entry.runtime_data = runtime
    runtime.registry.apply_device_list(
        "zigbee2mqtt",
        [
            {
                "ieee_address": IEEE,
                "friendly_name": "Kitchen",
                "type": "Router",
                "interview_completed": True,
                "disabled": False,
                "definition": definition,
            }
        ],
    )
    return runtime, entry


def test_ent_001_light_override_changes_desired_domain(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """ENT-001: Selected binary controls become native light entities."""
    runtime, _entry = _runtime(
        hass,
        load_fixture("gang_3"),
        light_entities=[STATE_S1],
    )
    description = next(
        entity
        for entity in runtime.registry.devices[IEEE].entities
        if entity.key == "state_s1"
    )

    assert runtime.desired_domain(IEEE, description) == "light"
    assert runtime.is_reliable(IEEE, description)


def test_non_get_light_requires_explicit_reliable_selection(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """Access-3 lights are not automatically retried without user selection."""
    key = f"{IEEE}|backlight"
    runtime, _entry = _runtime(
        hass,
        load_fixture("gang_1"),
        light_entities=[key],
    )
    description = next(
        entity
        for entity in runtime.registry.devices[IEEE].entities
        if entity.key == "backlight"
    )

    assert runtime.desired_domain(IEEE, description) == "light"
    assert not runtime.is_reliable(IEEE, description)


def test_ent_002_reconcile_removes_obsolete_switch_registry_entry(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """ENT-002: Domain changes leave no stale registry entry."""
    runtime, entry = _runtime(
        hass,
        load_fixture("gang_3"),
        light_entities=[STATE_S1],
    )
    entity_registry = er.async_get(hass)
    stale = entity_registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{IEEE}_state_s1",
        config_entry=entry,
        suggested_object_id="kitchen_left",
    )
    hass.states.async_set(stale.entity_id, "off")

    runtime.reconcile_entity_domains()

    assert entity_registry.async_get(stale.entity_id) is None


def test_override_choices_include_unavailable_persisted_devices(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CFG-003: Missing physical devices retain selectable override keys."""
    runtime, _entry = _runtime(hass, load_fixture("gang_1"))
    runtime.registry.devices[IEEE].present = False

    choices = runtime.control_choices()

    assert f"{IEEE}|state" in choices
    assert "unavailable" in choices[f"{IEEE}|state"].lower()
