# Legacy State Migration

CP-5003 provides a one-time copy from legacy Redis state and filesystem plans
to the local SQLite system of record.

```bash
canto migrate-state
```

Optional overrides:

```bash
canto migrate-state \
  --redis-url redis://localhost:6379/0 \
  --plans-dir ~/.canto/plans \
  --sqlite-path ~/.canto/state/canto.db
```

The command copies jobs, ordered events, approval objects, artifact metadata,
the registry snapshot, and plan JSON. Existing destination identifiers are
skipped, making the migration safely repeatable. The result reports imported
and skipped counts by record type.

Migration never deletes Redis keys or filesystem plans. Operators should keep a
backup and verify the SQLite state before retiring legacy storage.
