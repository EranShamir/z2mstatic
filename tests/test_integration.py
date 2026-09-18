"""End-to-end Home Assistant lifecycle tests with mocked MQTT."""

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.z2m_static_entities.const import (
    CONF_BASE_TOPICS,
    CONF_LIGHT_ENTITIES,
    CONF_RELIABLE_ENTITIES,
    CONF_REPLACE_FROM,
    CONF_REPLACE_TO,
    CONF_STALE_DAYS,
    DOMAIN,
)

FixtureLoader = Callable[[str], dict[str, Any]]
IEEE = "0x00124b0024abcdef"


async def test_mqtt_discovery_creates_stable_device_entities_and_state(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """MQT-001/002: MQTT device metadata creates and updates HA entities."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPICS: ["zigbee2mqtt"], CONF_STALE_DAYS: 30},
    )
    entry.add_to_hass(hass)
    subscriptions: dict[str, Callable[..., Any]] = {}

    async def subscribe(
        hass_arg: HomeAssistant,
        topic: str,
        callback: Callable[..., Any],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        assert hass_arg is hass
        subscriptions[topic] = callback
        return lambda: None

    with (
        patch(
            "custom_components.z2m_static_entities.runtime.async_wait_for_mqtt_client",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.z2m_static_entities.runtime.mqtt.async_subscribe",
            side_effect=subscribe,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

        device_payload = [
            {
                "ieee_address": IEEE,
                "friendly_name": "Utility room",
                "type": "Router",
                "interview_completed": True,
                "disabled": False,
                "definition": load_fixture("gang_1"),
            }
        ]
        await subscriptions["zigbee2mqtt/bridge/devices"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/devices",
                payload=json.dumps(device_payload),
            )
        )
        subscriptions["zigbee2mqtt/bridge/state"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/state",
                payload="online",
            )
        )
        subscriptions["zigbee2mqtt/Utility room"](
            SimpleNamespace(
                topic="zigbee2mqtt/Utility room",
                payload=json.dumps(
                    {
                        "state": "ON",
                        "master": "OFF",
                        "backlight": "ON",
                        "childlock": "OFF",
                        "linkquality": 144,
                    }
                ),
            )
        )
        await hass.async_block_till_done()
        options_result = await hass.config_entries.options.async_init(entry.entry_id)

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        entity_registry,
        entry.entry_id,
    )
    assert {item.unique_id for item in entries} == {
        f"{IEEE}_state",
        f"{IEEE}_master",
        f"{IEEE}_backlight",
        f"{IEEE}_childlock",
        f"{IEEE}_linkquality",
    }

    state_entry = next(item for item in entries if item.unique_id == f"{IEEE}_state")
    backlight_entry = next(
        item for item in entries if item.unique_id == f"{IEEE}_backlight"
    )
    linkquality_entry = next(
        item for item in entries if item.unique_id == f"{IEEE}_linkquality"
    )
    state = hass.states.get(state_entry.entity_id)
    backlight = hass.states.get(backlight_entry.entity_id)
    linkquality = hass.states.get(linkquality_entry.entity_id)
    assert state is not None
    assert backlight is not None
    assert linkquality is not None
    assert state.state == "on"
    assert backlight.state == "on"
    assert linkquality.state == "144"
    assert linkquality.attributes["state_class"] == "measurement"
    assert linkquality.attributes["unit_of_measurement"] == "lqi"
    assert linkquality_entry.original_icon == "mdi:signal"
    assert backlight_entry.entity_category == "config"

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(
        device_registry,
        entry.entry_id,
    )
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, IEEE)}
    schema = options_result["data_schema"]
    assert schema is not None
    assert CONF_LIGHT_ENTITIES in schema.schema
    assert CONF_RELIABLE_ENTITIES in schema.schema


async def test_ent_001_light_override_loads_native_light_only(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """ENT-001: A selected control loads as light without a switch duplicate."""
    ieee = "0x00124b0000000009"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPICS: ["zigbee2mqtt"], CONF_STALE_DAYS: 30},
        options={CONF_LIGHT_ENTITIES: [f"{ieee}|state_s1"]},
    )
    entry.add_to_hass(hass)
    subscriptions: dict[str, Callable[..., Any]] = {}

    async def subscribe(
        hass_arg: HomeAssistant,
        topic: str,
        callback: Callable[..., Any],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        subscriptions[topic] = callback
        return lambda: None

    with (
        patch(
            "custom_components.z2m_static_entities.runtime.async_wait_for_mqtt_client",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.z2m_static_entities.runtime.mqtt.async_subscribe",
            side_effect=subscribe,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await subscriptions["zigbee2mqtt/bridge/devices"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/devices",
                payload=json.dumps(
                    [
                        {
                            "ieee_address": ieee,
                            "friendly_name": "Native light test",
                            "type": "Router",
                            "interview_completed": True,
                            "disabled": False,
                            "definition": load_fixture("gang_3"),
                        }
                    ]
                ),
            )
        )
        subscriptions["zigbee2mqtt/bridge/state"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/state",
                payload="online",
            )
        )
        subscriptions["zigbee2mqtt/Native light test"](
            SimpleNamespace(
                topic="zigbee2mqtt/Native light test",
                payload='{"state_s1":"ON"}',
            )
        )
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    assert (
        entity_registry.async_get_entity_id(
            "light",
            DOMAIN,
            f"{ieee}_state_s1",
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            "switch",
            DOMAIN,
            f"{ieee}_state_s1",
        )
        is None
    )


async def test_reg_006_options_replacement_preserves_entity_and_new_route_state(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """REG-006: Options replacement keeps identity and adopts new MQTT state."""
    replacement_ieee = "0x00124b0024fedcba"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_TOPICS: ["zigbee2mqtt"], CONF_STALE_DAYS: 30},
    )
    entry.add_to_hass(hass)
    subscriptions: dict[str, Callable[..., Any]] = {}

    async def subscribe(
        hass_arg: HomeAssistant,
        topic: str,
        callback: Callable[..., Any],
        qos: int = 0,
        encoding: str | None = "utf-8",
    ) -> Callable[[], None]:
        subscriptions[topic] = callback
        return lambda: None

    definition = load_fixture("gang_1")
    with (
        patch(
            "custom_components.z2m_static_entities.runtime.async_wait_for_mqtt_client",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.z2m_static_entities.runtime.mqtt.async_subscribe",
            side_effect=subscribe,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await subscriptions["zigbee2mqtt/bridge/devices"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/devices",
                payload=json.dumps(
                    [
                        {
                            "ieee_address": IEEE,
                            "friendly_name": "Old switch",
                            "type": "Router",
                            "interview_completed": True,
                            "disabled": False,
                            "definition": definition,
                        }
                    ]
                ),
            )
        )
        await hass.async_block_till_done()
        entity_registry = er.async_get(hass)
        stable_entity_id = entity_registry.async_get_entity_id(
            "switch",
            DOMAIN,
            f"{IEEE}_state",
        )
        assert stable_entity_id is not None

        await subscriptions["zigbee2mqtt/bridge/devices"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/devices",
                payload=json.dumps(
                    [
                        {
                            "ieee_address": replacement_ieee,
                            "friendly_name": "New switch",
                            "type": "Router",
                            "interview_completed": True,
                            "disabled": False,
                            "definition": definition,
                        }
                    ]
                ),
            )
        )
        await hass.async_block_till_done()
        assert (
            entity_registry.async_get_entity_id(
                "switch",
                DOMAIN,
                f"{replacement_ieee}_state",
            )
            is not None
        )

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_BASE_TOPICS: "zigbee2mqtt",
                CONF_STALE_DAYS: 30,
                CONF_REPLACE_FROM: IEEE,
                CONF_REPLACE_TO: replacement_ieee,
            },
        )
        assert result["type"].value == "create_entry"
        await hass.async_block_till_done()

        assert (
            entity_registry.async_get_entity_id(
                "switch",
                DOMAIN,
                f"{replacement_ieee}_state",
            )
            is None
        )
        assert (
            entity_registry.async_get_entity_id(
                "switch",
                DOMAIN,
                f"{IEEE}_state",
            )
            == stable_entity_id
        )

        subscriptions["zigbee2mqtt/bridge/state"](
            SimpleNamespace(
                topic="zigbee2mqtt/bridge/state",
                payload="online",
            )
        )
        subscriptions["zigbee2mqtt/New switch"](
            SimpleNamespace(
                topic="zigbee2mqtt/New switch",
                payload='{"state":"ON"}',
            )
        )
        await hass.async_block_till_done()

    state = hass.states.get(stable_entity_id)
    assert state is not None
    assert state.state == "on"
    assert entry.runtime_data.registry.replacements == {replacement_ieee: IEEE}
