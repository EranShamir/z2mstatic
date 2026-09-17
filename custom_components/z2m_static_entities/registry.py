"""Persistent device registry model."""

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from typing import Any

from .parser import ExposedEntity, parse_exposes


@dataclass
class DeviceRecord:
    """Persisted description and active MQTT route for one physical device."""

    ieee_address: str
    friendly_name: str
    base_topic: str
    model: str
    vendor: str
    description: str
    exposes: list[dict[str, Any]]
    entities: list[ExposedEntity]
    first_seen: datetime
    last_seen: datetime | None = None
    disabled: bool = False
    present: bool = True
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def entity_unique_ids(self) -> set[str]:
        """Return stable IDs for every parsed expose."""
        return {f"{self.ieee_address}_{entity.key}" for entity in self.entities}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the record for Home Assistant storage."""
        data = asdict(self)
        data["first_seen"] = self.first_seen.isoformat()
        data["last_seen"] = self.last_seen.isoformat() if self.last_seen else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceRecord:
        """Restore a record from Home Assistant storage."""
        return cls(
            ieee_address=data["ieee_address"],
            friendly_name=data["friendly_name"],
            base_topic=data["base_topic"],
            model=data["model"],
            vendor=data["vendor"],
            description=data["description"],
            exposes=data["exposes"],
            entities=[
                ExposedEntity(
                    **{
                        key: value
                        for key, value in entity.items()
                        if key in _EXPOSED_ENTITY_FIELDS
                    }
                )
                for entity in data["entities"]
            ],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_seen=(
                datetime.fromisoformat(data["last_seen"])
                if data["last_seen"] is not None
                else None
            ),
            disabled=data["disabled"],
            present=data["present"],
            state=data.get("state", {}),
        )


@dataclass
class DeviceRegistry:
    """Additive registry whose records cannot be deleted by upstream MQTT."""

    devices: dict[str, DeviceRecord] = field(default_factory=dict)
    tombstones: dict[str, datetime] = field(default_factory=dict)
    replacements: dict[str, str] = field(default_factory=dict)
    retired_ieees: set[str] = field(default_factory=set)
    configured_base_topics: set[str] = field(default_factory=set, repr=False)
    _session_routes: set[str] = field(default_factory=set, repr=False)
    _topic_index: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _present_on: dict[str, set[str]] = field(default_factory=dict, repr=False)
    _snapshots_received: set[str] = field(default_factory=set, repr=False)

    def apply_device_list(
        self,
        base_topic: str,
        entries: list[dict[str, Any]] | None,
    ) -> None:
        """Merge a bridge/devices snapshot without deleting omitted records."""
        seen: set[str] = set()
        for entry in entries or []:
            physical_ieee = entry.get("ieee_address")
            if (
                not isinstance(physical_ieee, str)
                or physical_ieee in self.retired_ieees
            ):
                continue
            ieee = self.replacements.get(physical_ieee, physical_ieee)
            if (
                entry.get("type") != "Coordinator"
                and ieee not in self.tombstones
                and ieee in self.devices
            ):
                seen.add(ieee)

            definition = entry.get("definition")
            if (
                entry.get("type") == "Coordinator"
                or not entry.get("interview_completed", False)
                or not isinstance(definition, dict)
            ):
                continue

            if ieee in self.tombstones:
                continue

            seen.add(ieee)
            friendly_name = entry["friendly_name"]
            existing = self.devices.get(ieee)
            entities = parse_exposes(definition)
            now = datetime.now().astimezone()

            if existing is None:
                existing = DeviceRecord(
                    ieee_address=ieee,
                    friendly_name=friendly_name,
                    base_topic=base_topic,
                    model=definition.get("model", ""),
                    vendor=definition.get("vendor", ""),
                    description=definition.get("description", ""),
                    exposes=definition.get("exposes", []),
                    entities=entities,
                    first_seen=now,
                )
                self.devices[ieee] = existing
            else:
                existing.model = definition.get("model", existing.model)
                existing.vendor = definition.get("vendor", existing.vendor)
                existing.description = definition.get(
                    "description", existing.description
                )
                existing.exposes = definition.get("exposes", existing.exposes)
                existing.entities = _merge_entities(existing.entities, entities)
            existing.disabled = bool(entry.get("disabled", False))
            existing.present = True
            self._topic_index[(base_topic, friendly_name)] = ieee

        self._present_on[base_topic] = seen
        self._snapshots_received.add(base_topic)
        if not self.configured_base_topics or self.configured_base_topics.issubset(
            self._snapshots_received
        ):
            for ieee, record in self.devices.items():
                record.present = any(
                    ieee in present_ieees for present_ieees in self._present_on.values()
                )

    def note_state(
        self,
        base_topic: str,
        friendly_name: str,
        seen_at: datetime,
        payload: dict[str, Any] | None = None,
    ) -> DeviceRecord | None:
        """Make a state-producing route authoritative for this session."""
        ieee = self._topic_index.get((base_topic, friendly_name))
        if ieee is None or ieee in self.tombstones:
            return None
        record = self.devices[ieee]
        if record.base_topic != base_topic or record.friendly_name != friendly_name:
            record.state.pop("_availability", None)
            self._topic_index = {
                route: route_ieee
                for route, route_ieee in self._topic_index.items()
                if route_ieee != ieee or route == (base_topic, friendly_name)
            }
        record.base_topic = base_topic
        record.friendly_name = friendly_name
        record.last_seen = seen_at
        record.present = True
        self._present_on.setdefault(base_topic, set()).add(ieee)
        if payload is not None:
            record.state.update(payload)
        self._session_routes.add(ieee)
        return record

    def tombstone(self, ieee: str, removed_at: datetime) -> None:
        """Remove one record by explicit user action and block rediscovery."""
        self.devices.pop(ieee, None)
        self.tombstones[ieee] = removed_at
        self.replacements = {
            physical: logical
            for physical, logical in self.replacements.items()
            if logical != ieee
        }
        self._session_routes.discard(ieee)
        self._topic_index = {
            route: route_ieee
            for route, route_ieee in self._topic_index.items()
            if route_ieee != ieee
        }

    def restore_tombstone(self, ieee: str) -> None:
        """Allow a manually removed IEEE address to be discovered again."""
        self.tombstones.pop(ieee, None)

    def ieee_for_route(self, base_topic: str, friendly_name: str) -> str | None:
        """Return the IEEE address currently known for an MQTT route."""
        return self._topic_index.get((base_topic, friendly_name))

    def replace_device(self, old_ieee: str, replacement_ieee: str) -> None:
        """Move an unavailable logical identity to a compatible physical IEEE."""
        if old_ieee == replacement_ieee:
            raise ValueError("Replacement IEEE must differ from the existing device")
        old = self.devices.get(old_ieee)
        replacement = self.devices.get(replacement_ieee)
        if old is None:
            raise ValueError("Existing device is unknown")
        if replacement is None:
            raise ValueError("Replacement device is unknown")
        if old.present:
            raise ValueError("Existing device must be unavailable before replacement")
        if not replacement.present:
            raise ValueError("Replacement device must be present")
        if not _compatible_entities(old.entities, replacement.entities):
            raise ValueError("Replacement device exposes are not compatible")

        current_physical = next(
            (
                physical
                for physical, logical in self.replacements.items()
                if logical == old_ieee
            ),
            old_ieee,
        )
        old.friendly_name = replacement.friendly_name
        old.base_topic = replacement.base_topic
        old.model = replacement.model
        old.vendor = replacement.vendor
        old.description = replacement.description
        old.exposes = replacement.exposes
        old.entities = _merge_entities(old.entities, replacement.entities)
        old.last_seen = replacement.last_seen
        old.disabled = replacement.disabled
        old.present = True
        old.state = replacement.state.copy()

        self.devices.pop(replacement_ieee)
        self.retired_ieees.add(current_physical)
        self.retired_ieees.discard(replacement_ieee)
        self.replacements.pop(current_physical, None)
        self.replacements[replacement_ieee] = old_ieee

        for present_ieees in self._present_on.values():
            replacement_present = replacement_ieee in present_ieees
            present_ieees.discard(old_ieee)
            present_ieees.discard(current_physical)
            present_ieees.discard(replacement_ieee)
            if replacement_present:
                present_ieees.add(old_ieee)

        self._topic_index = {
            route: route_ieee
            for route, route_ieee in self._topic_index.items()
            if route_ieee not in {old_ieee, replacement_ieee}
        }
        self._topic_index[(replacement.base_topic, replacement.friendly_name)] = (
            old_ieee
        )
        self._session_routes.discard(replacement_ieee)
        self._session_routes.add(old_ieee)

    def to_dict(self) -> dict[str, Any]:
        """Serialize all persistent state."""
        return {
            "devices": {
                ieee: record.to_dict() for ieee, record in self.devices.items()
            },
            "tombstones": {
                ieee: removed_at.isoformat()
                for ieee, removed_at in self.tombstones.items()
            },
            "replacements": self.replacements,
            "retired_ieees": sorted(self.retired_ieees),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        configured_base_topics: set[str] | None = None,
    ) -> DeviceRegistry:
        """Restore persistent state and rebuild runtime indexes."""
        registry = cls(
            devices={
                ieee: DeviceRecord.from_dict(record)
                for ieee, record in data.get("devices", {}).items()
            },
            tombstones={
                ieee: datetime.fromisoformat(removed_at)
                for ieee, removed_at in data.get("tombstones", {}).items()
            },
            replacements=data.get("replacements", {}),
            retired_ieees=set(data.get("retired_ieees", [])),
            configured_base_topics=configured_base_topics or set(),
        )
        registry._topic_index = {
            (record.base_topic, record.friendly_name): ieee
            for ieee, record in registry.devices.items()
        }
        return registry


def _merge_entities(
    existing: list[ExposedEntity],
    current: list[ExposedEntity],
) -> list[ExposedEntity]:
    """Add newly exposed entities without deleting or changing existing domains."""
    by_key = {entity.key: entity for entity in existing}
    for entity in current:
        stored = by_key.get(entity.key)
        if stored is None:
            by_key[entity.key] = entity
        else:
            by_key[entity.key] = replace(entity, domain=stored.domain)
    return list(by_key.values())


def _compatible_entities(
    existing: list[ExposedEntity],
    replacement_entities: list[ExposedEntity],
) -> bool:
    """Return whether a replacement preserves every existing entity contract."""
    replacements = {entity.key: entity for entity in replacement_entities}
    return all(
        (candidate := replacements.get(entity.key)) is not None
        and candidate.domain == entity.domain
        and candidate.settable == entity.settable
        and candidate.value_on == entity.value_on
        and candidate.value_off == entity.value_off
        for entity in existing
    )


_EXPOSED_ENTITY_FIELDS = {item.name for item in fields(ExposedEntity)}
