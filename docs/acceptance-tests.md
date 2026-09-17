# Acceptance tests

- **PAR-001** Current 1/3/4/6-gang fixtures produce every gang, master,
  backlight, child-lock, and link-quality entity.
- **PAR-002** Backlight and child-lock are configuration entities; master and
  gang entities are primary controls.
- **PAR-003** Leak and smoke fixtures map readings, controls, units, device
  classes, and diagnostic categories correctly.
- **PAR-004** Unsupported V1 domains remain represented by parsed descriptions
  and can be skipped without losing their stored definitions.
- **CFG-001** Setup accepts and normalizes one or more unique MQTT base topics.
- **CFG-002** Options update base topics and stale-device threshold.
- **CFG-003** Options list discovered writable binary exposes and persist
  independent native-light and reliable-command selections by IEEE/property.
- **REG-001** Device identity and entity unique IDs depend on IEEE address and
  expose property, not friendly name or Z2M base topic.
- **REG-002** Persisted devices load on restart even when absent from all
  `bridge/devices` payloads.
- **REG-003** Removal, purge, or omission never deletes persisted entities.
- **REG-004** Restart loads persisted devices and their last entity states before
  fresh device traffic; bridge availability controls entity availability.
- **REG-005** Manual HA removal tombstones a missing IEEE; stale MQTT snapshots
  cannot recreate it, and an explicit options action can restore it.
- **MQT-001** `bridge/devices` updates definitions and the active route by IEEE.
- **MQT-002** State messages update entities and command entities publish the
  expose property to the active route's `/set` topic.
- **MQT-003** A state message from another configured base topic moves the active
  route while preserving entity unique IDs; retained snapshots cannot overwrite
  the session-authoritative route.
- **MQT-004** Commands publish non-retained JSON to the active
  `<base>/<friendly_name>/set` topic and update only after matching state.
- **ENT-001** A light override creates a native `light` entity and no active or
  orphaned `switch` registry entry for the same unique ID.
- **ENT-002** Changing a switch/light override reconciles the obsolete registry
  domain on reload; the IEEE/property identity remains stable.
- **CMD-001** A normal control publishes one `/set` command.
- **CMD-002** A reliable control publishes `/set`, waits for matching state,
  queries GET-capable exposes through `/get`, and retries up to three attempts.
- **CMD-003** Matching state ends verification immediately; HA state is never
  updated optimistically. Pre-existing matching state does not count, and a
  fast response immediately after `/set` is not missed.
- **CMD-004** Exhausted verification raises a visible Home Assistant action
  error, while a later user command remains usable.
- **CMD-005** A newer target supersedes the pending transaction for the same
  entity; unload cancels and awaits all pending transactions.
- **REP-001** Stale devices create one warning Repair issue after the configured
  threshold and reporting devices clear it.
