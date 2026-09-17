"""Constants for the Z2M Static Entities integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "z2m_static_entities"
MANUFACTURER: Final = "Zigbee2MQTT"
CONF_BASE_TOPICS: Final = "base_topics"
CONF_LIGHT_ENTITIES: Final = "light_entities"
CONF_RELIABLE_ENTITIES: Final = "reliable_entities"
CONF_RESTORE_DEVICES: Final = "restore_devices"
CONF_STALE_DAYS: Final = "stale_days"
DEFAULT_STALE_DAYS: Final = 30
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
STORE_KEY: Final = f"{DOMAIN}.registry"
STORE_VERSION: Final = 2
STORE_SAVE_DELAY: Final = 30
STALE_SCAN_INTERVAL: Final = timedelta(hours=6)
COMMAND_ATTEMPTS: Final = 3
COMMAND_SETTLE_SECONDS: Final = 0.75
COMMAND_QUERY_SECONDS: Final = 1.25

# Bit flags from Zigbee2MQTT's expose "access" field.
# See https://www.zigbee2mqtt.io/guide/usage/exposes.html
ACCESS_STATE: Final = 1  # value is published in the device state
ACCESS_SET: Final = 2  # value can be set/commanded
ACCESS_GET: Final = 4  # value can be actively queried
