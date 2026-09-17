# Product specification

Z2M Static Entities creates Home Assistant devices and entities from the
`definition.exposes` data published by one or more Zigbee2MQTT instances. The
integration owns those registry entries; Zigbee2MQTT discovery deletion,
device-removal responses, retained-message purges, and disappearance from
`bridge/devices` must never delete them.

## Required behavior

- One config entry manages a configurable list of unique Z2M MQTT base topics.
- Devices are identified by IEEE address, independently of coordinator, base
  topic, friendly name, or Z2M instance.
- A state message from a device is authoritative for its active Z2M route.
  Retained `bridge/devices` snapshots may initialize an unknown route but never
  replace a route learned from state traffic in the current Home Assistant
  session. Moving a device between configured instances therefore updates the
  route without replacing Home Assistant device or entity unique IDs.
- Definitions and routes persist across Home Assistant restarts. A missing
  device remains registered and unavailable until it reports again or the user
  explicitly removes it in Home Assistant.
- An options-flow replacement action maps a present compatible physical IEEE to
  an unavailable existing logical IEEE. Existing Home Assistant unique IDs,
  entity IDs, metadata, history, and IEEE/property option keys remain stable;
  MQTT state and commands use the replacement device's current route.
- Replacement requires the old logical device to be unavailable, the target to
  be present, and every existing entity property contract to remain compatible.
  The retired physical IEEE is ignored if it later reappears. Replacement
  aliases and retired IEEE addresses persist across restart.
- New or changed exposes add supported entities without deleting historical
  entities that are no longer exposed.
- V1 maps binary, numeric, enum, and switch-composite exposes. Supported
  platforms are `switch`, `binary_sensor`, and `sensor`; later slices may add
  `number`, `select`, `button`, and richer composite platforms.
- Backlight and child-lock controls are configuration entities. Master and gang
  switches remain primary controls. Diagnostic exposes remain diagnostic.
- Users can classify any readable/writable binary expose as a native Home
  Assistant `light`. The override is stored by IEEE address plus expose
  property and is independent of Z2M route or friendly name.
- Users can mark idempotent binary controls for reliable command verification.
  Native-light overrides use verification automatically when the expose
  supports Z2M GET access. A newer command supersedes an older pending command
  for the same control.
- Exposes that map to a not-yet-supported V1 platform are parsed and persisted
  but skipped at platform setup, allowing later platform support without
  rediscovery.
- After configurable inactivity (default 30 days), a warning Repair issue is
  created. It clears when the device reports again or is manually removed.
- Removing a missing device from Home Assistant creates an IEEE tombstone so
  stale retained MQTT data cannot recreate it. An options-flow action restores
  selected tombstones when the user wants those devices discovered again.
- Zigbee2MQTT Home Assistant discovery must be disabled after migration to avoid
  duplicate Z2M-owned and integration-owned entities.

## Non-goals

- Reimplementing Zigbee2MQTT pairing, converters, availability settings, or
  firmware updates.
- Deleting entities because Z2M removed or purged a device.
- Guaranteeing support for a new expose type without a tested mapping.
- Retrying toggle, momentary, silence, test, or other non-idempotent actions
  unless the user explicitly and correctly classifies them.
