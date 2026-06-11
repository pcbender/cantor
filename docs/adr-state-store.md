# ADR: State Store Backend — SQL as System of Record, Redis as Optional Adjunct

Status: **Accepted** · Date: 2026-06-10

## Context

Canto's durable state (jobs, events, approvals, artifact metadata, registry snapshot) currently
lives in Redis (`canto/core/state.py`, `RedisStateStore`). Redis was chosen because it was easy
to wire up, not as a strategic decision.

Two facts make this cheap to revisit:

1. **State is already abstracted.** All access goes through the `StateStore` Protocol (12
   methods) in `canto/core/state.py`. A `MemoryStateStore` alternate already exists and is
   dependency-injected into the API (`create_app(store=...)`) and CLI. Changing backends means
   adding a `StateStore` implementation — not rearchitecting.
2. **Redis is barely used as Redis.** The only non-trivial primitives are:
   - **Optimistic compare-and-set** for status transitions
     (`transition_job` / `transition_approval`, via `WATCH`/`MULTI`/`EXEC`).
   - **Ordered append** for events (`RPUSH` / `LRANGE`).
   Everything else is `GET`/`SET` of JSON blobs. There is no pub/sub, no streams, no TTL, no
   queue, no Lua. Both real primitives map directly to SQL:
   - CAS → `UPDATE … SET status=? WHERE id=? AND status IN (…)` (act on affected-row count).
   - Ordered append → an `events` table ordered by an autoincrement / timestamp column.

Using an in-memory KV store as the **system of record** creates two mismatches:

- **Durability.** Default Redis persistence is snapshot-based; a restart can drop recent writes.
  For a system whose core value is the approval/audit trail, an ephemeral store of record is the
  wrong default.
- **Query shape.** The MVP roadmap adds identity-stamped audit, per-user visibility, and
  retention/cleanup (MVP v2). Those are relational queries Redis serves poorly and SQL serves
  natively.

## Decision

Adopt **Option D: a SQL store of record, with Redis demoted to an optional coordination/eventing
adjunct** — all behind the existing `StateStore` Protocol.

`StateStore` implementations:

| Implementation | Role | Tier |
|---|---|---|
| `MemoryStateStore` | tests / ephemeral | (existing) |
| `SqliteStateStore` | embedded, single-file, ACID, zero-ops system of record | **MVP v1** (single-user local) |
| `MySqlStateStore` | server-class system of record: real concurrency, relational audit/retention, managed HA/backup | **MVP v2 / MVP v3** (team & public servers) |
| `PostgresStateStore` | server-class system of record; operator-choice alternative to MySQL | **MVP v3** (public server) |
| `RedisStateStore` | retained but no longer the system of record | legacy / dev convenience |

The `StateStore` Protocol is the stable seam. The relational schema is an implementation detail
shared by `SqliteStateStore`, `MySqlStateStore`, and `PostgresStateStore` (compatible SQL
dialect, same tables); they differ in driver, concurrency model, and deployment, not in
contract. At MVP v3 the operator may choose MySQL or PostgreSQL as the system of record.

The SQL system of record covers **all durable state behind the `StateStore` seam — jobs, events,
approvals, artifact metadata, the registry snapshot, and execution plans.** `PlanStore` (today
filesystem JSON under `~/.canto/.../plans`) folds into this store; plans become rows like jobs,
gaining the same durability, multi-user visibility, audit, and retention. Plans are server-owned
state — the external orchestrator holds only a `plan_id` and reaches plans through the HTTP
contract, never a client-side store. (Artifact *files* remain on the filesystem; only their
metadata lives in the store.)

**Redis is not removed — it is repositioned.** It returns only where it is genuinely the right
tool, as an *adjunct* to the SQL store of record, never as the store of record itself:

- **Event fan-out / SSE.** Real-time streaming of job/plan events to many clients (the SSE work
  deferred in the contract) is a natural fit for Redis pub/sub or Streams.
- **Job queue.** If execution becomes async/distributed across workers (MVP v2/v3), a Redis-backed
  queue is a reasonable coordination layer.

Both are additive and optional; the durable truth always lives in SQL.

## Tier mapping

- **MVP v1 (single-user local):** `SqliteStateStore` as default. No daemon to install or run,
  durable by default, audit-queryable. Removes the current "install and start Redis" setup
  friction from the single-user story.
- **MVP v2 (team server):** `MySqlStateStore`. Multi-process concurrency for shared workers plus
  the relational queries that v2's identity-audit / per-user-visibility / retention deliverables
  require. Optional Redis adjunct for event fan-out and/or a job queue.
- **MVP v3 (public server):** managed / HA MySQL **or** PostgreSQL as system of record
  (`MySqlStateStore` / `PostgresStateStore`, operator's choice); Redis adjunct where event
  fan-out or queueing is required at scale.

## Consequences

Positive:

- Durable, ACID system of record by default — the audit/approval trail survives restarts.
- Relational audit, per-user visibility, and retention/cleanup become straightforward queries.
- Zero-ops local story (SQLite) and a real server story (MySQL) without changing the rest of the
  system — only the injected `StateStore` differs.
- Redis becomes an intentional, optional capability rather than an accidental database.

Negative / cost:

- Two new `StateStore` implementations to write and test against the Protocol's contract
  (including the CAS and ordered-append semantics).
- A one-time Redis → SQLite/MySQL state-migration tool for any existing deployments.
- MySQL is a real operational dependency for the server tiers (mitigated by managed offerings).

Neutral:

- The `StateStore` Protocol may need minor additions to express relational reads (e.g. list/filter
  jobs by identity and time) that the current blob interface does not expose. These are additive.

## Alternatives considered

- **A — Keep Redis, make it strategic** (AOF + Sentinel/Cluster). Rejected: hardens a cache into a
  database it does not want to be; audit/retention queries stay painful.
- **B — SQLite only.** Good for v1, but single-writer concurrency does not serve the team/public
  tiers. Adopted *as the v1 tier* within Option D rather than as the whole answer.
- **C — PostgreSQL for servers.** Equivalent technically and equally supported by the Protocol.
  Not an either/or: MySQL is the named server store for MVP v2/v3, and `PostgresStateStore` is
  also in scope at MVP v3 as an operator-choice system of record.

## Notes

- CP-5002 implemented `SqliteStateStore` as the default local backend. Redis is
  retained for migration and optional legacy use.
- Production plan persistence now uses the injected `StateStore`. The
  filesystem `PlanStore` adapter remains only for legacy migration and focused
  compatibility tests. Artifact *files* remain on the filesystem; metadata is
  stored in SQLite.
