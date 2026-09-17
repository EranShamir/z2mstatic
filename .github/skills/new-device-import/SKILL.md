---
name: new-device-import
description: Import and assess a new Zigbee2MQTT device definition for the Z2M Static Entities integration. Use when the user says "new device import", provides Z2M exposes JSON, adds a Zigbee device type, or asks whether a device is automatically supported.
---

# New Z2M device import

Work only in the `z2m_static_entities` repository. Preserve the integration's
core invariant: MQTT discovery deletion, purge, removal, and omission never
authorize deleting Home Assistant devices or entities.

## Input

Obtain the complete Zigbee2MQTT device definition JSON containing `model`,
`vendor`, and `exposes`. A single `bridge/devices` entry containing a
`definition` object is also accepted. Save user-provided JSON to a temporary
file outside the repository; do not manually rewrite it.

Choose a concise lowercase fixture name using letters, numbers, and underscores.

## Import

Run:

```bash
uv run python scripts/import_device.py /path/to/definition.json --name <name>
```

The importer must refuse unknown expose shapes by default. Never use
`--allow-unsupported` merely to make the command pass.

## Interpret the report

- `switch`, `binary_sensor`, and `sensor` are active V1 platforms.
- `button`, `number`, and `select` are understood generic mappings but require
  their platform adapters if not yet implemented.
- `text`, `light`, `cover`, `climate`, `lock`, `fan`, and unknown composites
  require deliberate domain-specific design. Do not generate Python behavior
  from their names alone.
- Property/device-class metadata may be extended through generic rules only
  when semantics are clear from Z2M's declared expose contract.

Review both generated files under `tests/fixtures/imported/`. Confirm names,
domains, access semantics, endpoints, categories, units, on/off values, and
device classes against the source definition.

## Implement only reusable capability

If all entities use existing active platforms, no production-code change is
needed. If known future domains appear, add the missing generic platform once,
with parameterized tests. If unknown expose types appear, stop and describe the
unsupported contract before coding.

Never add model-specific Python branches when a generic expose rule or a small
reviewed metadata override can express the behavior.

## Validate

Run the focused importer/parser tests, then:

```bash
./scripts/validate
```

Report the imported model/vendor, generated entity inventory, automatically
supported entities, deferred domains, unsupported contracts, and validation
result.
