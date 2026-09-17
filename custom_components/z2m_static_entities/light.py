"""Native binary light entities for Z2M Static Entities."""

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Z2MConfigEntry
from .entity import Z2MEntity
from .parser import ExposedEntity


class Z2MLight(Z2MEntity, LightEntity):
    """A user-classified binary Z2M light."""

    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self,
        entry: Z2MConfigEntry,
        ieee: str,
        description: ExposedEntity,
    ) -> None:
        """Initialize a binary light."""
        super().__init__(entry, ieee, description)
        self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        """Return whether the property matches its declared on value."""
        record = self.record
        if record is None or self.z2m_description.key not in record.state:
            return None
        return record.state[self.z2m_description.key] == self.z2m_description.value_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Request and verify the expose's declared on value."""
        record = self.record
        if record is not None:
            await self._entry.runtime_data.async_command(
                record,
                self.z2m_description,
                self.z2m_description.value_on,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Request and verify the expose's declared off value."""
        record = self.record
        if record is not None:
            await self._entry.runtime_data.async_command(
                record,
                self.z2m_description,
                self.z2m_description.value_off,
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Z2MConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up and dynamically add user-classified light entities."""
    known: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[Z2MLight] = []
        for ieee, record in entry.runtime_data.registry.devices.items():
            for description in record.entities:
                unique_id = f"{ieee}_{description.key}"
                if (
                    entry.runtime_data.desired_domain(ieee, description) == "light"
                    and unique_id not in known
                ):
                    known.add(unique_id)
                    entities.append(Z2MLight(entry, ieee, description))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(entry.runtime_data.async_add_listener(add_new_entities))
    add_new_entities()
