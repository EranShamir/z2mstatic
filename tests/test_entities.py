"""Tests for Home Assistant entity adapters."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.z2m_static_entities.binary_sensor import Z2MBinarySensor
from custom_components.z2m_static_entities.const import (
    CONF_BASE_TOPICS,
    CONF_STALE_DAYS,
    DOMAIN,
)
from custom_components.z2m_static_entities.runtime import Z2MRuntime
from custom_components.z2m_static_entities.sensor import Z2MSensor
from custom_components.z2m_static_entities.switch import Z2MSwitch

FixtureLoader = Callable[[str], dict[str, Any]]
IEEE = "0x00124b0024abcdef"


def _runtime(
    hass: HomeAssistant,
    definition: dict[str, Any],
) -> tuple[Z2MRuntime, MockConfigEntry]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPICS: ["zigbee2mqtt"], CONF_STALE_DAYS: 30},
    )
    runtime = Z2MRuntime(hass, entry)
    entry.runtime_data = runtime
    runtime.registry.apply_device_list(
        "zigbee2mqtt",
        [
            {
                "ieee_address": IEEE,
                "friendly_name": "Utility room",
                "type": "Router",
                "interview_completed": True,
                "disabled": False,
                "definition": definition,
            }
        ],
    )
    return runtime, entry


def test_switch_entity_metadata_and_state(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """Switch entities preserve stable IDs and config categorization."""
    runtime, entry = _runtime(hass, load_fixture("gang_3"))
    record = runtime.registry.devices[IEEE]
    descriptions = {entity.key: entity for entity in record.entities}
    record.state.update({"state_s1": "ON", "state_backlight": "OFF"})

    gang = Z2MSwitch(entry, IEEE, descriptions["state_s1"])
    backlight = Z2MSwitch(entry, IEEE, descriptions["state_backlight"])

    assert gang.unique_id == f"{IEEE}_state_s1"
    assert gang.is_on
    assert gang.entity_category is None
    assert not backlight.is_on
    assert backlight.entity_category is EntityCategory.CONFIG
    assert gang.device_info["identifiers"] == {(DOMAIN, IEEE)}


async def test_switch_waits_for_state_confirmation(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """A command publish does not optimistically mutate entity state."""
    runtime, entry = _runtime(hass, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")
    entity = Z2MSwitch(entry, IEEE, description)
    with patch.object(
        runtime,
        "async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await entity.async_turn_on()

    publish.assert_awaited_once_with(record, "state", "ON")
    assert entity.is_on is None


def test_detector_entity_values(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """Detector observations expose binary and numeric persisted state."""
    runtime, entry = _runtime(hass, load_fixture("leak_detector"))
    record = runtime.registry.devices[IEEE]
    descriptions = {entity.key: entity for entity in record.entities}
    record.state.update({"water_leak": True, "battery": 72})

    leak = Z2MBinarySensor(entry, IEEE, descriptions["water_leak"])
    battery = Z2MSensor(entry, IEEE, descriptions["battery"])

    assert leak.is_on
    assert battery.native_value == 72
