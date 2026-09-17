"""Z2M Static Entities integration."""

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .runtime import Z2MRuntime

type Z2MConfigEntry = ConfigEntry[Z2MRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: Z2MConfigEntry) -> bool:
    """Set up Z2M Static Entities from a config entry."""
    runtime = Z2MRuntime(hass, entry)
    entry.runtime_data = runtime
    await runtime.async_start()
    runtime.reconcile_replacement_entities()
    runtime.reconcile_entity_domains()
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Z2MConfigEntry) -> bool:
    """Unload a Z2M Static Entities config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: Z2MConfigEntry,
    device: dr.DeviceEntry,
) -> bool:
    """Allow explicit removal only after the device disappeared from Z2M."""
    identifier = next(
        (value for domain, value in device.identifiers if domain == DOMAIN),
        None,
    )
    if identifier is None:
        return False
    record = entry.runtime_data.registry.devices.get(identifier)
    if record is None or record.present:
        return False
    entry.runtime_data.registry.tombstone(identifier, datetime.now(UTC))
    entry.runtime_data.clear_stale_issue(identifier)
    entry.runtime_data.schedule_save()
    return True
