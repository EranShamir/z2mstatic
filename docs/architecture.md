# Architecture

The integration uses a single config entry to own all configured Zigbee2MQTT
base topics. This avoids config-entry ownership changes when a physical device
moves between coordinators.

`Z2MRegistry` is the runtime boundary. It subscribes through Home Assistant's
MQTT integration, merges `bridge/devices` snapshots by IEEE address, stores the
last supported expose definitions and active `{base_topic, friendly_name}`
route, dispatches state changes, and publishes commands. Its persisted store is
authoritative for retention; upstream absence can mark unavailable but cannot
remove records.

## Device-list handling

For each `<base_topic>/bridge/devices` entry:

| Condition | Action |
|---|---|
| `type == "Coordinator"` | Ignore |
| `definition` is null or interview is incomplete | Ignore without changing a persisted record |
| IEEE is tombstoned | Ignore |
| New supported device | Persist definition and initialize its route |
| Existing device on another route | Update metadata, but do not replace a session-authoritative route |
| `disabled == true` | Retain and mark unavailable |
| Device omitted or list purged | Retain and mark unavailable only when no configured instance reports it |

State traffic on an exact known device state topic makes that route
session-authoritative. Retained snapshots can only initialize a route before
state traffic is seen. Removing a configured base topic drops its subscriptions
and marks only devices exclusively associated with it unavailable; records and
routes remain persisted for later restoration.

## Persistence

Home Assistant `Store` key `z2m_static_entities.registry`, version 2, contains:

```text
{
  devices: {
    <ieee>: {
      friendly_name, base_topic, model, vendor, description,
      exposes, entities, first_seen, last_seen, disabled, present, state
    }
  },
  tombstones: {<ieee>: {removed_at}}
}
```

Version 1 migrates by rebuilding parsed entity descriptions from each record's
raw persisted `exposes`, including access flags. Deserialization ignores unknown
entity-description fields for forward compatibility. Unknown future store
versions abort setup instead of resetting data. Definition, route, and tombstone
changes schedule a delayed save. State timestamps are coalesced and never cause
one disk write per MQTT message.

The expose parser is pure and Home Assistant independent. Platform entities are
thin adapters over immutable parsed descriptions and registry state. Unique IDs
use `{ieee_address}_{property}` because Z2M properties already include endpoint
suffixes where required. The first duplicate property wins with a warning. If a
later definition changes an existing property's domain, the stored domain is
retained and the incompatible change is logged.

V1 platforms instantiate only `switch`, `binary_sensor`, and `sensor`
descriptions. Other parsed domains remain stored for later platform support.

## Entity overrides

Config-entry options store `light_entities` and `reliable_entities` as sorted
lists of stable `<ieee>|<property>` keys; runtime converts them to sets. Missing
keys default to empty for existing entries. The options flow lists persisted
readable/writable binary controls, including unavailable devices, and groups
labels by device. Existing selections not rendered in the form are preserved.

`desired_domain()` changes a parsed switch description to `light` when selected.
After runtime storage loads and before platforms are forwarded, the runtime
removes only its own unloaded entity-registry entry when its domain no longer
matches the desired domain. It never removes a live state-machine entity. HA
does not support cross-domain entity-ID migration, so the
one-time switch-to-light classification changes `switch.*` to `light.*`; no
duplicate or unavailable old entry remains. Device identity and the unique-ID
body remain IEEE/property based.

Binary lights declare `ColorMode.ONOFF`. The README warns that the one-time
domain change requires updating references to the previous `switch.*` entity.

## MQTT and availability

The registry subscribes to each configured `<base>/bridge/devices` and
`<base>/bridge/state` topic. After processing a device snapshot it subscribes to
the exact device state and availability topics derived from the current route,
avoiding wildcard ambiguity from friendly names containing `/`, `+`, or `#`.
`bridge/*`, `/set`, `/get`, and `/availability` payloads are never treated as
device state.

Commands publish JSON `{"<property>": <value>}` to
`<base>/<friendly_name>/set` with QoS 0 and `retain=False`. Command entities are
not optimistic; they change only when matching state arrives.

Normal controls publish once. A new reliable command supersedes an older
in-flight command for the same IEEE/property. Before every `/set`, the runtime
arms a fresh-state sequence waiter and always publishes at least once, even when
stored state already matches. Each attempt re-resolves the active route,
publishes `/set`, waits 0.75 seconds for a newer payload containing the target
raw value, then—when the expose access bitmask includes GET—publishes
`{"<property>": ""}` to `<base>/<friendly_name>/get` and waits 1.25 seconds.
The transaction makes at most three set attempts. Any matching raw state ends
the transaction. Exhaustion raises `HomeAssistantError`; it does not alter
reported state. Transaction registrations are removed in `finally`; unload
cancels and awaits all pending transactions.

Only explicitly selected controls are reliable, except native lights which are
automatically reliable when GET-capable. Access-3 controls may be explicitly
selected for set/wait/retry but cannot issue `/get`.

Entity state is restored across restart. Availability priority is: device
`disabled` is unavailable; MQTT disconnected is unavailable; explicit device
availability is authoritative when configured; otherwise bridge online means
available. Before bridge status is known after restart, restored entities are
unavailable rather than implying a live connection.

## Removal and Repairs

`async_remove_config_entry_device` accepts only devices owned by this entry that
are absent from all current device snapshots. It removes the persisted record
and creates an IEEE tombstone. The options flow lists tombstones and can clear
selected ones for explicit rediscovery.

Repairs are derived from the last actual device-state timestamp, not
`bridge/devices` presence. A six-hour timer creates issue
`stale_device_<normalized_ieee>` with `IssueSeverity.WARNING`,
`is_fixable=False`, after the configured threshold. Any device state clears the
issue. Lowering the threshold may create issues at the next scan.
