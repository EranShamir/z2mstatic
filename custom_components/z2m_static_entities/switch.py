"""Switch entities for Z2M Static Entities."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Z2MConfigEntry
from .entity import Z2MEntity


class Z2MSwitch(Z2MEntity, SwitchEntity):
    """A readable and settable binary Z2M expose."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the property matches its declared on value."""
        record = self.record
        if record is None or self.z2m_description.key not in record.state:
            return None
        return record.state[self.z2m_description.key] == self.z2m_description.value_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Request the expose's declared on value."""
        record = self.record
        if record is not None:
            await self._entry.runtime_data.async_command(
                record,
                self.z2m_description,
                self.z2m_description.value_on,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Request the expose's declared off value."""
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
    """Set up and dynamically add switch entities."""
    known: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities: list[Z2MSwitch] = []
        for ieee, record in entry.runtime_data.registry.devices.items():
            for description in record.entities:
                unique_id = f"{ieee}_{description.key}"
                if (
                    entry.runtime_data.desired_domain(ieee, description) == "switch"
                    and unique_id not in known
                ):
                    known.add(unique_id)
                    entities.append(Z2MSwitch(entry, ieee, description))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(entry.runtime_data.async_add_listener(add_new_entities))
    add_new_entities()
