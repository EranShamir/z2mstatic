# Z2M Static Entities

Personal Home Assistant custom integration that creates stable entities from
Zigbee2MQTT exposes without granting Zigbee2MQTT authority to delete them.

## Current support

- One integration entry manages multiple Z2M MQTT base topics.
- Physical devices are identified by IEEE address, so friendly-name changes and
  coordinator moves preserve entity unique IDs.
- Supported entities: switches, binary sensors, and sensors, including
  multi-endpoint Tuya switches and the supplied leak/smoke detector definitions.
- Writable binary controls can be classified in integration options as native
  `light` entities. GET-capable lights can verify and retry commands; selected
  idempotent switches can use the same reliable command mode.
- Backlight and child-lock switches are configuration entities; master switches
  remain primary controls.
- Definitions, routes, and last state persist across HA restarts.
- Battery and link-quality sensors expose measurement state classes so Home
  Assistant can retain long-term statistics across discovery migration.
- An unavailable device can be explicitly replaced by a compatible newly
  discovered IEEE while preserving the existing Home Assistant device/entity
  identity, names, icons, history, and light/reliable classifications.
- Z2M omission, removal, or retained-message purge never deletes HA entities.
- Stale devices generate a warning under Settings > System > Repairs.

## Development

The integration is mounted into the local hacore devcontainer from this
repository's:

```text
custom_components/z2m_static_entities
```

Dependency and validation commands use uv:

```bash
uv sync
./scripts/validate
```

Rebuild the hacore devcontainer after changing its mount configuration.

## Importing a new device type

Save the Z2M definition JSON to a temporary file and run:

```bash
uv run python scripts/import_device.py /path/to/definition.json \
  --name mmwave_presence
```

The importer creates a reviewed fixture pair under
`tests/fixtures/imported/`, reports active and future platform domains, and
refuses unknown composite behavior by default.

The repository-local Copilot skill is named **`new-device-import`**. While
working in this repository, ask Copilot to “use the new-device-import skill”
and provide the definition JSON or its file path.

## Initial Home Assistant test

1. Keep Zigbee2MQTT Home Assistant discovery enabled during the first comparison
   test; duplicate entities are expected temporarily.
2. Add **Z2M Static Entities** from Settings > Devices & services and enter all
   base topics, for example `zigbee2mqtt, zigbee2mqtt2`.
3. Confirm each physical device appears with the expected entities and that
   commands work.
4. Disable Home Assistant discovery in every Z2M instance only after the new
   entities and dependent helpers/automations are ready.

Removing or purging a device in Z2M only makes this integration's retained
device unavailable. A device can be manually removed from HA after it is absent
from all configured Z2M snapshots; that creates a tombstone. The options flow
can explicitly restore tombstoned IEEE addresses.

To replace failed hardware, first let the old device become absent from all
configured Z2M snapshots and pair the replacement. In integration options,
select the old device under **Existing unavailable device** and the new device
under **Replacement device**, then save. Every existing property must have a
compatible property on the replacement. This action is not needed when the same
physical IEEE merely moves to another coordinator; route migration is automatic.

Changing an existing control between `switch` and `light` changes its HA entity
ID because Home Assistant does not support moving an entity ID across domains.
The integration removes the obsolete registry entry, but automations,
dashboards, and helpers referencing the previous entity ID must be updated once.
