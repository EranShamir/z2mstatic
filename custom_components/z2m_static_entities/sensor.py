"""Sensor entities for Z2M Static Entities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import Z2MConfigEntry
from .entity import Z2MEntity
from .parser import ExposedEntity


class Z2MSensor(Z2MEntity, SensorEntity):
    """A read-only numeric or enum Z2M expose."""

    def __init__(
        self,
        entry: Z2MConfigEntry,
        ieee: str,
        description: ExposedEntity,
    ) -> None:
        """Initialize a sensor."""
        super().__init__(entry, ieee, description)
        self._attr_native_unit_of_measurement = description.unit
        if description.device_class is not None:
            self._attr_device_class = SensorDeviceClass(description.device_class)

    @property
    def native_value(self) -> StateType:
        """Return the last persisted property value."""
        record = self.record
        value = record.state.get(self.z2m_description.key) if record else None
        return value if isinstance(value, str | int | float) else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Z2MConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up and dynamically add sensor entities."""
    known: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[Z2MSensor] = []
        for ieee, record in entry.runtime_data.registry.devices.items():
            for description in record.entities:
                unique_id = f"{ieee}_{description.key}"
                if description.domain == "sensor" and unique_id not in known:
                    known.add(unique_id)
                    entities.append(Z2MSensor(entry, ieee, description))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(entry.runtime_data.async_add_listener(add_new_entities))
    add_new_entities()
