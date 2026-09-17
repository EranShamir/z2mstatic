"""Binary sensor entities for Z2M Static Entities."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Z2MConfigEntry
from .entity import Z2MEntity
from .parser import ExposedEntity


class Z2MBinarySensor(Z2MEntity, BinarySensorEntity):
    """A read-only binary Z2M expose."""

    def __init__(
        self,
        entry: Z2MConfigEntry,
        ieee: str,
        description: ExposedEntity,
    ) -> None:
        """Initialize a binary sensor."""
        super().__init__(entry, ieee, description)
        if description.device_class is not None:
            self._attr_device_class = BinarySensorDeviceClass(description.device_class)

    @property
    def is_on(self) -> bool | None:
        """Return whether the property matches its declared on value."""
        record = self.record
        if record is None or self.z2m_description.key not in record.state:
            return None
        return record.state[self.z2m_description.key] == self.z2m_description.value_on


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Z2MConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up and dynamically add binary sensor entities."""
    known: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[Z2MBinarySensor] = []
        for ieee, record in entry.runtime_data.registry.devices.items():
            for description in record.entities:
                unique_id = f"{ieee}_{description.key}"
                if description.domain == "binary_sensor" and unique_id not in known:
                    known.add(unique_id)
                    entities.append(Z2MBinarySensor(entry, ieee, description))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(entry.runtime_data.async_add_listener(add_new_entities))
    add_new_entities()
