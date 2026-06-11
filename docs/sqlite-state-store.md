# SQLite State Store

`SqliteStateStore` is the default durable state backend for local Canto.

The database is stored at:

```text
~/.canto/state/canto.db
```

It contains jobs, ordered job events, approval objects, artifact metadata,
registry snapshots, and execution plans. Artifact files remain in Canto-managed
job directories.

The store uses SQLite transactions, foreign-key enforcement, WAL journaling,
and atomic status updates. Job and approval transitions update only records in
an expected current state, preserving the compare-and-set behavior previously
provided by Redis.

The database currently uses schema version `1`. Canto rejects an unsupported
schema version rather than modifying it silently. Future schema changes require
explicit migrations.

Redis remains available through `RedisStateStore` for migration and legacy
development use, but it is no longer required for local startup or execution.
The Redis-to-SQLite migration utility is scoped to CP-5003.
