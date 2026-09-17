"""Tests for the persistent Z2M device registry model."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.z2m_static_entities.const import STORE_KEY, STORE_VERSION
from custom_components.z2m_static_entities.registry import DeviceRegistry
from custom_components.z2m_static_entities.runtime import RegistryStore

FixtureLoader = Callable[[str], dict[str, Any]]
IEEE = "0x00124b0024abcdef"


def _device(
    definition: dict[str, Any],
    *,
    friendly_name: str = "Kitchen switch",
    disabled: bool = False,
) -> dict[str, Any]:
    return {
        "ieee_address": IEEE,
        "friendly_name": friendly_name,
        "type": "Router",
        "interview_completed": True,
        "disabled": disabled,
        "definition": definition,
    }


def test_reg_001_identity_does_not_depend_on_route(
    load_fixture: FixtureLoader,
) -> None:
    """REG-001: IEEE and expose property provide stable entity identities."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_3"))],
    )
    before = registry.devices[IEEE].entity_unique_ids

    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(load_fixture("gang_3"), friendly_name="Renamed switch")],
    )

    assert registry.devices[IEEE].entity_unique_ids == before
    assert all(unique_id.startswith(f"{IEEE}_") for unique_id in before)


def test_reg_002_003_empty_snapshot_and_purge_retain_device(
    load_fixture: FixtureLoader,
) -> None:
    """REG-002/REG-003: Omission and purge never delete persisted records."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_1"))],
    )

    registry.apply_device_list("zigbee2mqtt", [])
    registry.apply_device_list("zigbee2mqtt", None)

    assert IEEE in registry.devices
    assert not registry.devices[IEEE].present


def test_presence_is_aggregated_across_z2m_instances(
    load_fixture: FixtureLoader,
) -> None:
    """A device remains present while any configured instance reports it."""
    registry = DeviceRegistry(configured_base_topics={"zigbee2mqtt", "zigbee2mqtt2"})
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_1"))],
    )
    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(load_fixture("gang_1"), friendly_name="Other route")],
    )

    registry.apply_device_list("zigbee2mqtt", [])

    assert registry.devices[IEEE].present


def test_incomplete_known_entry_preserves_presence(
    load_fixture: FixtureLoader,
) -> None:
    """A transient missing definition does not make a known device absent."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_1"))],
    )

    registry.apply_device_list(
        "zigbee2mqtt",
        [
            {
                **_device(load_fixture("gang_1")),
                "definition": None,
                "interview_completed": False,
            }
        ],
    )

    assert registry.devices[IEEE].present


def test_mqt_003_state_message_moves_route_and_snapshot_cannot_steal_it(
    load_fixture: FixtureLoader,
) -> None:
    """MQT-003: State traffic wins over stale retained device snapshots."""
    registry = DeviceRegistry()
    definition = load_fixture("gang_3")
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(definition, friendly_name="Old route")],
    )
    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(definition, friendly_name="New route")],
    )

    now = datetime(2026, 9, 17, tzinfo=UTC)
    registry.note_state("zigbee2mqtt2", "New route", now)
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(definition, friendly_name="Old route")],
    )

    record = registry.devices[IEEE]
    assert record.base_topic == "zigbee2mqtt2"
    assert record.friendly_name == "New route"
    assert record.last_seen == now


def test_retained_snapshot_cannot_change_persisted_route(
    load_fixture: FixtureLoader,
) -> None:
    """MQT-003: Startup snapshot order cannot overwrite a stored route."""
    registry = DeviceRegistry()
    definition = load_fixture("gang_3")
    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(definition, friendly_name="Current route")],
    )
    restored = DeviceRegistry.from_dict(registry.to_dict())

    restored.apply_device_list(
        "zigbee2mqtt",
        [_device(definition, friendly_name="Stale route")],
    )

    assert restored.devices[IEEE].base_topic == "zigbee2mqtt2"
    assert restored.devices[IEEE].friendly_name == "Current route"


def test_route_migration_drops_old_explicit_availability(
    load_fixture: FixtureLoader,
) -> None:
    """MQT-003: Availability from an old coordinator does not follow a move."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_1"))],
    )
    registry.devices[IEEE].state["_availability"] = False

    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(load_fixture("gang_1"), friendly_name="Moved switch")],
    )
    registry.note_state(
        "zigbee2mqtt2",
        "Moved switch",
        datetime(2026, 9, 17, tzinfo=UTC),
        {"state": "ON"},
    )

    assert "_availability" not in registry.devices[IEEE].state


def test_old_route_state_cannot_reclaim_migrated_device(
    load_fixture: FixtureLoader,
) -> None:
    """A state message from an invalidated route cannot reverse migration."""
    registry = DeviceRegistry()
    definition = load_fixture("gang_1")
    registry.apply_device_list("zigbee2mqtt", [_device(definition)])
    registry.apply_device_list(
        "zigbee2mqtt2",
        [_device(definition, friendly_name="Moved switch")],
    )
    now = datetime(2026, 9, 17, tzinfo=UTC)
    registry.note_state("zigbee2mqtt2", "Moved switch", now, {"state": "ON"})

    result = registry.note_state(
        "zigbee2mqtt",
        "Kitchen switch",
        now,
        {"state": "OFF"},
    )

    assert result is None
    assert registry.devices[IEEE].base_topic == "zigbee2mqtt2"


def test_registry_ignores_coordinator_and_incomplete_entries(
    load_fixture: FixtureLoader,
) -> None:
    """Invalid bridge entries do not create or mutate device records."""
    registry = DeviceRegistry()
    definition = load_fixture("gang_1")
    registry.apply_device_list(
        "zigbee2mqtt",
        [
            {
                **_device(definition),
                "type": "Coordinator",
            },
            {
                **_device(definition),
                "ieee_address": "0x2",
                "interview_completed": False,
            },
            {
                **_device(definition),
                "ieee_address": "0x3",
                "definition": None,
            },
        ],
    )

    assert registry.devices == {}


def test_reg_005_tombstone_blocks_snapshots_until_restored(
    load_fixture: FixtureLoader,
) -> None:
    """REG-005: Explicit tombstones prevent stale retained resurrection."""
    registry = DeviceRegistry()
    entry = _device(load_fixture("gang_1"))
    registry.apply_device_list("zigbee2mqtt", [entry])
    registry.tombstone(IEEE, datetime(2026, 9, 17, tzinfo=UTC))

    registry.apply_device_list("zigbee2mqtt", [entry])
    assert IEEE not in registry.devices

    registry.restore_tombstone(IEEE)
    registry.apply_device_list("zigbee2mqtt", [entry])
    assert IEEE in registry.devices


def test_registry_round_trip_preserves_devices_and_tombstones(
    load_fixture: FixtureLoader,
) -> None:
    """Stored registry data survives serialization and restart."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("smoke_detector"))],
    )
    registry.tombstone("0xdead", datetime(2026, 9, 1, tzinfo=UTC))

    restored = DeviceRegistry.from_dict(registry.to_dict())

    assert restored.to_dict() == registry.to_dict()


async def test_store_v1_migration_rebuilds_access_flags(
    hass: HomeAssistant,
    load_fixture: FixtureLoader,
) -> None:
    """Stored V1 descriptions are re-derived with command access metadata."""
    registry = DeviceRegistry()
    registry.apply_device_list(
        "zigbee2mqtt",
        [_device(load_fixture("gang_3"))],
    )
    old_data = registry.to_dict()
    for entity in old_data["devices"][IEEE]["entities"]:
        entity.pop("access", None)
    old_data["devices"][IEEE]["entities"].append(
        {
            "key": "historical_property",
            "domain": "sensor",
            "name": "Historical",
        }
    )
    store = RegistryStore(hass, STORE_VERSION, STORE_KEY)

    migrated = await store._async_migrate_func(1, 1, old_data)

    state_s1 = next(
        entity
        for entity in migrated["devices"][IEEE]["entities"]
        if entity["key"] == "state_s1"
    )
    assert state_s1["access"] == 7
    assert any(
        entity["key"] == "historical_property"
        for entity in migrated["devices"][IEEE]["entities"]
    )
