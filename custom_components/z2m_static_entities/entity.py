"""Shared entity support."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityCategory

from . import Z2MConfigEntry
from .const import DOMAIN
from .parser import ExposedEntity
from .registry import DeviceRecord


class Z2MEntity(Entity):
    """Base entity backed by a persisted Z2M record."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: Z2MConfigEntry,
        ieee: str,
        description: ExposedEntity,
    ) -> None:
        """Initialize an entity."""
        self._entry = entry
        self._ieee = ieee
        self.z2m_description = description
        self._attr_unique_id = f"{ieee}_{description.key}"
        self._attr_name = description.name
        if description.entity_category is not None:
            self._attr_entity_category = EntityCategory(description.entity_category)

    @property
    def record(self) -> DeviceRecord | None:
        """Return the current persisted device record."""
        return self._entry.runtime_data.registry.devices.get(self._ieee)

    @property
    def device_info(self) -> DeviceInfo:
        """Group all exposes under the physical Zigbee device."""
        record = self.record
        return DeviceInfo(
            identifiers={(DOMAIN, self._ieee)},
            name=record.friendly_name if record else self._ieee,
            manufacturer=record.vendor if record else None,
            model=record.model if record else None,
        )

    @property
    def available(self) -> bool:
        """Return whether the active Z2M route is available."""
        record = self.record
        return record is not None and self._entry.runtime_data.is_available(record)

    async def async_added_to_hass(self) -> None:
        """Listen for state, route, and availability changes."""
        self.async_on_remove(
            self._entry.runtime_data.async_add_listener(self._handle_update)
        )

    def _handle_update(self) -> None:
        self.async_write_ha_state()
