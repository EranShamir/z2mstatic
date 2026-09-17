# Development plan

1. **Parser foundation — PAR-001..003**
   - Preserve the supplied real-device fixtures.
   - Test and implement generic expose mapping.
   - Exit: focused parser tests pass.
2. **Configuration lifecycle — CFG-001..002**
   - Add config/options flows, translations, and setup/unload wiring.
   - Exit: flow tests pass and normalized topics persist.
3. **Persistent registry — REG-001..003**
   - Define stored device schema and additive merge behavior.
   - Exit: persistence, restart, tombstone, migration, and removal-immunity
     tests pass.
4. **MQTT runtime — MQT-001..003**
   - Subscribe to bridge/device topics and publish commands.
   - Exit: mocked MQTT contract tests pass.
5. **Entity platforms and repairs — REP-001**
   - Add switch, sensor, binary-sensor adapters and stale-device Repairs.
   - Exit: HA entity/device registry and Repair tests pass.
6. **Validation**
   - Run `scripts/validate`, Home Assistant manifest validation in the hacore
     devcontainer, focused code review, and document installation/migration.
7. **Native lights and verified commands — CFG-003, ENT-001..002, CMD-001..004**
   - Add failing parser/options/entity/command tests.
   - Persist IEEE/property overrides and reconcile entity-registry domains.
   - Add native binary-light entities and serialized set/wait/get/retry logic.
   - Exit: focused and full automated validation pass.
8. **Three-phase feature acceptance**
   - Run mocked HA acceptance, isolated real-MQTT acceptance, then selected
     physical-device acceptance before resuming production migration.
