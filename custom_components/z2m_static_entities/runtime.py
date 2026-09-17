"""MQTT runtime and persistence boundary."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.mqtt import (
    ReceiveMessage,
    async_wait_for_mqtt_client,
)
from homeassistant.components.mqtt import (
    client as mqtt,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    ACCESS_GET,
    COMMAND_ATTEMPTS,
    COMMAND_QUERY_SECONDS,
    COMMAND_SETTLE_SECONDS,
    CONF_BASE_TOPICS,
    CONF_LIGHT_ENTITIES,
    CONF_RELIABLE_ENTITIES,
    CONF_STALE_DAYS,
    DOMAIN,
    STALE_SCAN_INTERVAL,
    STORE_KEY,
    STORE_SAVE_DELAY,
    STORE_VERSION,
)
from .parser import ExposedEntity, parse_exposes
from .registry import DeviceRecord, DeviceRegistry

_LOGGER = logging.getLogger(__name__)

type RuntimeListener = Callable[[], None]
type CommandKey = tuple[str, str]


class RegistryStore(Store[dict[str, Any]]):
    """Versioned persistent registry store."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version != 1:
            raise NotImplementedError
        for record in old_data.get("devices", {}).values():
            parsed = parse_exposes({"exposes": record.get("exposes", [])})
            old_entities = {
                entity["key"]: entity
                for entity in record.get("entities", [])
                if "key" in entity and "domain" in entity
            }
            migrated = [
                asdict(
                    replace(
                        entity,
                        domain=old_entities.get(entity.key, {}).get(
                            "domain",
                            entity.domain,
                        ),
                    )
                )
                for entity in parsed
            ]
            migrated_keys = {entity["key"] for entity in migrated}
            migrated.extend(
                entity
                for key, entity in old_entities.items()
                if key not in migrated_keys
            )
            record["entities"] = migrated
        return old_data


class Z2MRuntime:
    """Own MQTT subscriptions, persisted records, and entity notifications."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the runtime."""
        self.hass = hass
        self.entry = entry
        self.registry = DeviceRegistry(
            configured_base_topics=set(entry.data[CONF_BASE_TOPICS])
        )
        self._store: Store[dict[str, Any]] = RegistryStore(
            hass,
            STORE_VERSION,
            STORE_KEY,
        )
        self._listeners: set[RuntimeListener] = set()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._device_unsubs: dict[tuple[str, str], list[CALLBACK_TYPE]] = {}
        self._bridge_online: dict[str, bool | None] = {}
        self.light_entities = set(
            entry.options.get(
                CONF_LIGHT_ENTITIES,
                entry.data.get(CONF_LIGHT_ENTITIES, []),
            )
        )
        self.reliable_entities = set(
            entry.options.get(
                CONF_RELIABLE_ENTITIES,
                entry.data.get(CONF_RELIABLE_ENTITIES, []),
            )
        )
        self.command_settle_seconds = COMMAND_SETTLE_SECONDS
        self.command_query_seconds = COMMAND_QUERY_SECONDS
        self.command_attempts = COMMAND_ATTEMPTS
        self._state_versions: dict[CommandKey, int] = {}
        self._state_events: dict[CommandKey, asyncio.Event] = {}
        self._command_tasks: dict[CommandKey, asyncio.Task[None]] = {}
        self._superseded_tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    @property
    def base_topics(self) -> list[str]:
        """Return configured Zigbee2MQTT MQTT base topics."""
        return self.entry.options.get(
            CONF_BASE_TOPICS,
            self.entry.data[CONF_BASE_TOPICS],
        )

    @property
    def stale_days(self) -> int:
        """Return the configured stale-device threshold."""
        return self.entry.options.get(
            CONF_STALE_DAYS,
            self.entry.data[CONF_STALE_DAYS],
        )

    async def async_start(self) -> None:
        """Load persisted state and subscribe to configured Z2M instances."""
        stored = await self._store.async_load()
        if stored is not None:
            self.registry = DeviceRegistry.from_dict(
                stored,
                configured_base_topics=set(self.base_topics),
            )

        if not await async_wait_for_mqtt_client(self.hass):
            raise ConfigEntryNotReady("MQTT integration is unavailable")

        for base_topic in self.base_topics:
            self._bridge_online[base_topic] = None
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self.hass,
                    f"{base_topic}/bridge/devices",
                    self._device_list_handler(base_topic),
                )
            )
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self.hass,
                    f"{base_topic}/bridge/state",
                    self._bridge_state_handler(base_topic),
                )
            )

        for record in self.registry.devices.values():
            if record.base_topic in self.base_topics:
                await self._async_subscribe_device_route(
                    record.base_topic,
                    record.friendly_name,
                )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self.check_stale_devices,
                STALE_SCAN_INTERVAL,
            )
        )
        self.check_stale_devices(datetime.now(UTC))

    async def async_close(self) -> None:
        """Remove subscriptions and flush persisted state."""
        self._closing = True
        current = asyncio.current_task()
        pending = [
            task
            for task in self._command_tasks.values()
            if task is not current and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for unsub in self._unsubs:
            unsub()
        for unsubs in self._device_unsubs.values():
            for unsub in unsubs:
                unsub()
        self._unsubs.clear()
        self._device_unsubs.clear()
        await self._store.async_save(self.registry.to_dict())

    @callback
    def async_add_listener(self, listener: RuntimeListener) -> CALLBACK_TYPE:
        """Register an entity-platform listener."""
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    @callback
    def schedule_save(self) -> None:
        self._store.async_delay_save(
            self.registry.to_dict,
            STORE_SAVE_DELAY,
        )

    def _device_list_handler(
        self,
        base_topic: str,
    ) -> Callable[[ReceiveMessage], Any]:
        async def handle(msg: ReceiveMessage) -> None:
            if not isinstance(msg.payload, str):
                return
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError:
                _LOGGER.warning("Invalid bridge/devices JSON on %s", msg.topic)
                return
            if not isinstance(payload, list):
                _LOGGER.warning("Expected a device list on %s", msg.topic)
                return

            self.registry.apply_device_list(base_topic, payload)
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                friendly_name = entry.get("friendly_name")
                ieee = entry.get("ieee_address")
                if (
                    isinstance(friendly_name, str)
                    and isinstance(ieee, str)
                    and self.registry.ieee_for_route(base_topic, friendly_name)
                    is not None
                ):
                    await self._async_subscribe_device_route(
                        base_topic,
                        friendly_name,
                    )
            self.schedule_save()
            self._notify()

        return handle

    def _bridge_state_handler(
        self,
        base_topic: str,
    ) -> Callable[[ReceiveMessage], None]:
        @callback
        def handle(msg: ReceiveMessage) -> None:
            payload = msg.payload
            online = False
            if isinstance(payload, str):
                if payload == "online":
                    online = True
                else:
                    try:
                        decoded = json.loads(payload)
                    except json.JSONDecodeError:
                        decoded = None
                    online = (
                        isinstance(decoded, dict) and decoded.get("state") == "online"
                    )
            self._bridge_online[base_topic] = online
            self._notify()

        return handle

    async def _async_subscribe_device_route(
        self,
        base_topic: str,
        friendly_name: str,
    ) -> None:
        route = (base_topic, friendly_name)
        if route in self._device_unsubs:
            return
        self._device_unsubs[route] = [
            await mqtt.async_subscribe(
                self.hass,
                f"{base_topic}/{friendly_name}",
                self._state_handler(base_topic, friendly_name),
            ),
            await mqtt.async_subscribe(
                self.hass,
                f"{base_topic}/{friendly_name}/availability",
                self._availability_handler(base_topic, friendly_name),
            ),
        ]

    def _state_handler(
        self,
        base_topic: str,
        friendly_name: str,
    ) -> Callable[[ReceiveMessage], None]:
        @callback
        def handle(msg: ReceiveMessage) -> None:
            if not isinstance(msg.payload, str):
                return
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError:
                return
            if not isinstance(payload, dict):
                return
            record = self.registry.note_state(
                base_topic,
                friendly_name,
                datetime.now(UTC),
                payload,
            )
            if record is None:
                return
            for property_ in payload:
                command_key = (record.ieee_address, property_)
                self._state_versions[command_key] = (
                    self._state_versions.get(command_key, 0) + 1
                )
                if event := self._state_events.get(command_key):
                    event.set()
            self.schedule_save()
            self.clear_stale_issue(record.ieee_address)
            self._notify()

        return handle

    def _availability_handler(
        self,
        base_topic: str,
        friendly_name: str,
    ) -> Callable[[ReceiveMessage], None]:
        @callback
        def handle(msg: ReceiveMessage) -> None:
            ieee = self.registry.ieee_for_route(base_topic, friendly_name)
            if ieee is None:
                return
            record = self.registry.devices[ieee]
            if isinstance(msg.payload, str):
                record.state["_availability"] = msg.payload == "online"
                self._notify()

        return handle

    def is_available(self, record: DeviceRecord) -> bool:
        """Return availability without treating a quiet battery device as lost."""
        if record.disabled or not record.present:
            return False
        if self._bridge_online.get(record.base_topic) is not True:
            return False
        explicit = record.state.get("_availability")
        if isinstance(explicit, bool):
            return explicit
        return True

    async def async_publish(self, record: DeviceRecord, key: str, value: Any) -> None:
        """Publish one non-retained Z2M property command."""
        await mqtt.async_publish(
            self.hass,
            f"{record.base_topic}/{record.friendly_name}/set",
            json.dumps({key: value}),
            qos=0,
            retain=False,
        )

    async def async_publish_get(self, record: DeviceRecord, key: str) -> None:
        """Request a property from the device without retaining the query."""
        await mqtt.async_publish(
            self.hass,
            f"{record.base_topic}/{record.friendly_name}/get",
            json.dumps({key: ""}),
            qos=0,
            retain=False,
        )

    def desired_domain(self, ieee: str, description: ExposedEntity) -> str:
        """Return the user-selected HA domain for a parsed expose."""
        if (
            description.domain == "switch"
            and self.control_key(ieee, description.key) in self.light_entities
        ):
            return "light"
        return description.domain

    def is_reliable(self, ieee: str, description: ExposedEntity) -> bool:
        """Return whether commands need state verification and retry."""
        key = self.control_key(ieee, description.key)
        return key in self.reliable_entities or (
            key in self.light_entities and bool(description.access & ACCESS_GET)
        )

    @staticmethod
    def control_key(ieee: str, property_: str) -> str:
        """Build a route-independent override key."""
        return f"{ieee}|{property_}"

    def control_choices(self) -> dict[str, str]:
        """Return persisted writable binary controls for the options flow."""
        choices: dict[str, str] = {}
        for ieee, record in self.registry.devices.items():
            suffix = "" if record.present else " (unavailable)"
            for description in record.entities:
                if description.domain != "switch":
                    continue
                key = self.control_key(ieee, description.key)
                choices[key] = (
                    f"{record.friendly_name} — {description.name} "
                    f"[{description.key}]{suffix}"
                )
        return choices

    def replacement_choices(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return unavailable logical sources and present physical targets."""
        replacement_logical_ieees = set(self.registry.replacements.values())
        sources = {
            ieee: f"{record.friendly_name} ({ieee})"
            for ieee, record in self.registry.devices.items()
            if not record.present
        }
        targets = {
            ieee: f"{record.friendly_name} ({ieee})"
            for ieee, record in self.registry.devices.items()
            if record.present and ieee not in replacement_logical_ieees
        }
        return (
            dict(sorted(sources.items(), key=lambda item: item[1].casefold())),
            dict(sorted(targets.items(), key=lambda item: item[1].casefold())),
        )

    @callback
    def reconcile_replacement_entities(self) -> None:
        """Remove transient registry rows created for replacement physical IDs."""
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry,
            self.entry.entry_id,
        )
        for physical_ieee in self.registry.replacements:
            prefix = f"{physical_ieee}_"
            for registry_entry in entries:
                if registry_entry.unique_id.startswith(prefix):
                    entity_registry.async_remove(registry_entry.entity_id)
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get_device_by_identifier(
                (DOMAIN, physical_ieee),
                self.entry.entry_id,
            )
            if device is not None:
                device_registry.async_remove_device(device.id)

    @callback
    def reconcile_entity_domains(self) -> None:
        """Remove this entry's unloaded registry entries in obsolete domains."""
        entity_registry = er.async_get(self.hass)
        loaded_platforms = entity_platform.async_get_platforms(self.hass, DOMAIN)
        for ieee, record in self.registry.devices.items():
            for description in record.entities:
                desired = self.desired_domain(ieee, description)
                if desired not in {"switch", "light"}:
                    continue
                old_domain = "light" if desired == "switch" else "switch"
                unique_id = f"{ieee}_{description.key}"
                entity_id = entity_registry.async_get_entity_id(
                    old_domain,
                    DOMAIN,
                    unique_id,
                )
                if entity_id is None or any(
                    platform.config_entry == self.entry
                    and entity_id in platform.entities
                    for platform in loaded_platforms
                ):
                    continue
                registry_entry = entity_registry.async_get(entity_id)
                if (
                    registry_entry is not None
                    and registry_entry.config_entry_id == self.entry.entry_id
                ):
                    entity_registry.async_remove(entity_id)

    async def async_command(
        self,
        record: DeviceRecord,
        description: ExposedEntity,
        target: Any,
    ) -> None:
        """Publish normally or verify an explicitly idempotent command."""
        if not self.is_reliable(record.ieee_address, description):
            await self.async_publish(record, description.key, target)
            return

        command_key = (record.ieee_address, description.key)
        current = asyncio.current_task()
        if current is None:
            raise HomeAssistantError("Command task is unavailable")
        if (
            (previous := self._command_tasks.get(command_key))
            and previous is not current
            and not previous.done()
        ):
            self._superseded_tasks.add(previous)
            previous.cancel()
        self._command_tasks[command_key] = current
        try:
            await self._async_verified_command(
                record.ieee_address,
                description,
                target,
            )
        except asyncio.CancelledError:
            if current in self._superseded_tasks:
                self._superseded_tasks.discard(current)
                raise HomeAssistantError(
                    f"Command for {description.name} was superseded"
                ) from None
            raise
        finally:
            if self._command_tasks.get(command_key) is current:
                self._command_tasks.pop(command_key, None)
            self._superseded_tasks.discard(current)

    async def _async_verified_command(
        self,
        ieee: str,
        description: ExposedEntity,
        target: Any,
    ) -> None:
        command_key = (ieee, description.key)
        event = self._state_events.setdefault(command_key, asyncio.Event())
        for _attempt in range(self.command_attempts):
            record = self.registry.devices.get(ieee)
            if record is None:
                raise HomeAssistantError(f"Device {ieee} is no longer available")

            event.clear()
            baseline = self._state_versions.get(command_key, 0)
            await self.async_publish(record, description.key, target)
            if await self._async_wait_for_target(
                record,
                description.key,
                target,
                baseline,
                self.command_settle_seconds,
                event,
            ):
                return

            if description.access & ACCESS_GET:
                record = self.registry.devices.get(ieee)
                if record is None:
                    raise HomeAssistantError(f"Device {ieee} is no longer available")
                event.clear()
                baseline = self._state_versions.get(command_key, 0)
                await self.async_publish_get(record, description.key)
                if await self._async_wait_for_target(
                    record,
                    description.key,
                    target,
                    baseline,
                    self.command_query_seconds,
                    event,
                ):
                    return

        raise HomeAssistantError(
            f"Command for {description.name} could not be confirmed "
            f"after {self.command_attempts} attempts"
        )

    async def _async_wait_for_target(
        self,
        record: DeviceRecord,
        key: str,
        target: Any,
        baseline: int,
        wait_seconds: float,
        event: asyncio.Event,
    ) -> bool:
        command_key = (record.ieee_address, key)
        deadline = self.hass.loop.time() + wait_seconds
        while True:
            if (
                self._state_versions.get(command_key, 0) > baseline
                and record.state.get(key) == target
            ):
                return True
            remaining = deadline - self.hass.loop.time()
            if remaining <= 0:
                return False
            event.clear()
            if (
                self._state_versions.get(command_key, 0) > baseline
                and record.state.get(key) == target
            ):
                return True
            try:
                await asyncio.wait_for(event.wait(), remaining)
            except TimeoutError:
                return False

    @callback
    def check_stale_devices(self, now: datetime) -> None:
        """Create or clear warning Repairs based on actual state traffic."""
        threshold = timedelta(days=self.stale_days)
        for ieee, record in self.registry.devices.items():
            last_report = record.last_seen or record.first_seen
            issue_id = _stale_issue_id(ieee)
            if now - last_report >= threshold:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    issue_domain=DOMAIN,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="stale_device",
                    translation_placeholders={
                        "device": record.friendly_name,
                        "days": str((now - last_report).days),
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @callback
    def clear_stale_issue(self, ieee: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, _stale_issue_id(ieee))


def _stale_issue_id(ieee: str) -> str:
    return f"stale_device_{ieee.lower().replace(':', '')}"
