"""Tests for MQTT commands, persisted state, and stale-device Repairs."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (  # type: ignore[import-untyped]
    MockConfigEntry,
)

from custom_components.z2m_static_entities.const import (
    CONF_BASE_TOPICS,
    CONF_RELIABLE_ENTITIES,
    CONF_STALE_DAYS,
    DOMAIN,
)
from custom_components.z2m_static_entities.runtime import Z2MRuntime

FixtureLoader = Callable[[str], dict[str, Any]]
IEEE = "0x00124b0024abcdef"


def _entry(*, reliable_entities: list[str] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_BASE_TOPICS: ["zigbee2mqtt", "zigbee2mqtt2"],
            CONF_STALE_DAYS: 30,
        },
        options={CONF_RELIABLE_ENTITIES: reliable_entities or []},
    )


def _add_device(runtime: Z2MRuntime, definition: dict[str, Any]) -> None:
    runtime.registry.apply_device_list(
        "zigbee2mqtt",
        [
            {
                "ieee_address": IEEE,
                "friendly_name": "Kitchen switch",
                "type": "Router",
                "interview_completed": True,
                "disabled": False,
                "definition": definition,
            }
        ],
    )


async def test_mqt_004_publish_uses_active_route_without_retain(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """MQT-004: Commands use JSON, QoS 0, and retain false."""
    runtime = Z2MRuntime(hass, _entry())
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await runtime.async_publish(record, "state", "ON")

    publish.assert_awaited_once_with(
        hass,
        "zigbee2mqtt/Kitchen switch/set",
        json.dumps({"state": "ON"}),
        qos=0,
        retain=False,
    )
    assert "state" not in record.state


def test_reg_004_state_survives_registry_round_trip(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """REG-004: Last state is persisted for restoration after restart."""
    runtime = Z2MRuntime(hass, _entry())
    _add_device(runtime, load_fixture("smoke_detector"))
    runtime.registry.note_state(
        "zigbee2mqtt",
        "Kitchen switch",
        datetime(2026, 9, 17, tzinfo=UTC),
        {"smoke": True, "battery": 87},
    )

    restored = runtime.registry.from_dict(runtime.registry.to_dict())

    assert restored.devices[IEEE].state == {"smoke": True, "battery": 87}


def test_rep_001_stale_device_creates_and_fresh_device_clears_repair(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """REP-001: Staleness is based on device state timestamps."""
    runtime = Z2MRuntime(hass, _entry())
    _add_device(runtime, load_fixture("leak_detector"))
    record = runtime.registry.devices[IEEE]
    now = datetime(2026, 9, 17, tzinfo=UTC)
    record.first_seen = now - timedelta(days=31)

    with (
        patch(
            "custom_components.z2m_static_entities.runtime.ir.async_create_issue"
        ) as create_issue,
        patch(
            "custom_components.z2m_static_entities.runtime.ir.async_delete_issue"
        ) as delete_issue,
    ):
        runtime.check_stale_devices(now)
        create_issue.assert_called_once()

        record.last_seen = now
        runtime.check_stale_devices(now)
        delete_issue.assert_called_with(
            hass,
            DOMAIN,
            "stale_device_0x00124b0024abcdef",
        )


def test_bridge_offline_overrides_cached_device_availability(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """MQT-004: An offline bridge always makes its devices unavailable."""
    runtime = Z2MRuntime(hass, _entry())
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    record.state["_availability"] = True
    runtime._bridge_online["zigbee2mqtt"] = False

    assert not runtime.is_available(record)


async def test_cmd_002_fast_matching_state_completes_without_get(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CMD-002/003: A fast post-set confirmation cannot be missed."""
    key = f"{IEEE}|state"
    runtime = Z2MRuntime(hass, _entry(reliable_entities=[key]))
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")
    state_handler = runtime._state_handler("zigbee2mqtt", "Kitchen switch")

    async def publish(
        hass_arg: HomeAssistant,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        if topic.endswith("/set"):
            state_handler(
                type(
                    "Message",
                    (),
                    {
                        "topic": "zigbee2mqtt/Kitchen switch",
                        "payload": '{"state":"ON"}',
                    },
                )()
            )

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        side_effect=publish,
    ) as mqtt_publish:
        await runtime.async_command(record, description, "ON")

    assert mqtt_publish.await_count == 1


async def test_cmd_002_queries_then_retries_until_matching(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CMD-002: A mismatch triggers GET and another SET attempt."""
    key = f"{IEEE}|state"
    runtime = Z2MRuntime(hass, _entry(reliable_entities=[key]))
    runtime.command_settle_seconds = 0.01
    runtime.command_query_seconds = 0.01
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")
    state_handler = runtime._state_handler("zigbee2mqtt", "Kitchen switch")
    set_count = 0
    topics: list[str] = []

    async def publish(
        hass_arg: HomeAssistant,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        nonlocal set_count
        topics.append(topic)
        if topic.endswith("/set"):
            set_count += 1
            if set_count == 2:
                state_handler(
                    type(
                        "Message",
                        (),
                        {
                            "topic": "zigbee2mqtt/Kitchen switch",
                            "payload": '{"state":"ON"}',
                        },
                    )()
                )

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        side_effect=publish,
    ):
        await runtime.async_command(record, description, "ON")

    assert topics == [
        "zigbee2mqtt/Kitchen switch/set",
        "zigbee2mqtt/Kitchen switch/get",
        "zigbee2mqtt/Kitchen switch/set",
    ]


async def test_cmd_004_exhaustion_raises_and_next_command_works(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CMD-004: Failure is visible and does not poison later commands."""
    key = f"{IEEE}|state"
    runtime = Z2MRuntime(hass, _entry(reliable_entities=[key]))
    runtime.command_settle_seconds = 0.001
    runtime.command_query_seconds = 0.001
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        with pytest.raises(HomeAssistantError, match="could not be confirmed"):
            await runtime.async_command(record, description, "ON")
        with pytest.raises(HomeAssistantError, match="could not be confirmed"):
            await runtime.async_command(record, description, "OFF")

    assert publish.await_count == 12


async def test_cmd_005_new_command_supersedes_pending_target(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CMD-005: A newer target cancels the previous transaction."""
    key = f"{IEEE}|state"
    runtime = Z2MRuntime(hass, _entry(reliable_entities=[key]))
    runtime.command_settle_seconds = 10
    runtime.command_query_seconds = 10
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        new_callable=AsyncMock,
    ):
        first = asyncio.create_task(runtime.async_command(record, description, "ON"))
        await asyncio.sleep(0)
        second = asyncio.create_task(runtime.async_command(record, description, "OFF"))
        with pytest.raises(HomeAssistantError, match="superseded"):
            await first
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second


async def test_cmd_005_unload_cancels_pending_verification(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """CMD-005: Runtime shutdown awaits cancellation of pending commands."""
    key = f"{IEEE}|state"
    runtime = Z2MRuntime(hass, _entry(reliable_entities=[key]))
    runtime.command_settle_seconds = 10
    runtime.command_query_seconds = 10
    _add_device(runtime, load_fixture("gang_1"))
    record = runtime.registry.devices[IEEE]
    description = next(entity for entity in record.entities if entity.key == "state")

    with patch(
        "custom_components.z2m_static_entities.runtime.mqtt.async_publish",
        new_callable=AsyncMock,
    ):
        command = asyncio.create_task(runtime.async_command(record, description, "ON"))
        await asyncio.sleep(0)
        await runtime.async_close()

    assert command.cancelled()
