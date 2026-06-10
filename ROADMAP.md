# Canto Roadmap

Status: updated after completion of v1.x, v2.0, v2.1 Registry Unification, and v2.2 Contract Freeze.

Canto has moved beyond proof-of-concept. The system can now package capabilities, install them, discover them, compose approved plans, execute those plans through the bounded JobService/runner path, expose orchestration over HTTP, and publish a frozen v1.0 orchestration contract.

The next phase begins with **v3.0 — External Orchestrator Integration**.

---

## Operating Model

Canto development uses an Orchestrator / Worker pattern.

- **Cantor**: human authority; approves direction, risk, registration, releases, and destructive actions.
- **Orchestrator**: maintains architectural intent, defines work packets, reviews changes, and controls sequencing.
- **Worker**: implements bounded tasks exactly as scoped.

The worker must not redesign the architecture unless a work packet explicitly authorizes an architecture change.

---

## Architecture Lock

The following concepts are locked unless changed by an explicit architecture ticket:

- Skill
- Provider
- Tool
- Artifact
- Job
- Approval
- Registry
- Policy
- Dependency checking
- Bounded local execution
- Capability package
- Execution plan
- Orchestration contract

Workers may add capabilities and integrations inside this model. Workers may not rename, replace, or bypass this model.

---

## Canonical Identity Decision

Canto uses two identities for two different purposes:

- **`(skill, provider)`** is the canonical execution identity.
- **`capability@version`** is the packaging, provenance, checksum, risk, and distribution identity.

A capability may expose one or more executable `(skill, provider)` pairs. The package identity never replaces the runner identity.

---

# Completed Phases

## v1.1 — Capability Packaging

Goal: turn local skills/providers/tools into installable capability packages.

Delivered:

- Capability manifest format
- Manifest validation
- Capability package layout
- Validation command
- Package design documentation
- Fixtures and CLI/unit tests

Success condition met:

A local capability can be described, validated, and prepared for deterministic packaging.

---

## v1.2 — Local Capability Registry

Goal: install, list, inspect, validate, and remove packaged capabilities from a local registry.

Delivered:

- Local registry directory layout
- Registry API
- Registry index model
- Local list/search
- Inspect command
- Remove command
- Installed package validation
- Directory-first install design and implementation

Success condition met:

A capability can be installed locally, discovered in the local registry, inspected, validated, and removed safely.

---

## v1.3 — Import Capability

Goal: build the first showcase reusable capability for CMS/content import planning.

Delivered:

- Import capability skeleton
- Static HTML provider
- WordPress REST inventory provider
- ProcessWire exported-JSON provider
- SQL dump inventory and CMS detection
- Inventory artifact
- Content artifact
- Schema artifact
- Migration plan artifact
- Crosswalk mappings
- Artifact-only transformation rules

Non-goals preserved:

- No destructive import
- No production writes
- No credential storage
- No live database connections

Success condition met:

Canto can analyze content sources and produce migration-ready artifacts without writing to a target system.

---

## v1.3.5 — Capability Archives

Goal: complete the local package lifecycle before capability scaffolding.

Delivered:

- Deterministic `.canto` archive creation
- Archive validation
- Installation from `.canto` archives
- Export of installed capabilities
- Pack → install → list → inspect → execute → export lifecycle
- Installed checksum validation
- Collision rejection

Success condition met:

A capability directory can be packed, validated, installed, executed, and exported as a deterministic `.canto` archive.

---

## v1.4 — Capability Scaffolding Workflow

Goal: create deterministic local capability scaffolds that can be validated, packed, and installed.

Delivered:

- Scaffold design documentation
- `canto scaffold NAME`
- Manifest generation
- Skill/provider/test templates
- Scaffold → validate → pack → install flow

Non-goals preserved:

- No AI generation
- No remote registry
- No dependency installation
- No automatic trust

Success condition met:

Canto can create a valid placeholder capability package that fits the local capability lifecycle.

---

## v2.0 — Orchestrated Capability Discovery

Goal: discover installed local capabilities, propose reviewable workflows, and execute only approved plans.

Delivered:

- Capability intent/input/output metadata
- Deterministic local discovery
- Workflow candidate model
- Persisted plan model
- Draft and approved plans
- Approved-only sequential execution
- Exact artifact dependency resolution
- Plan explanation
- Full discover → plan → approve → execute → explain demo

Non-goals preserved:

- No remote registry
- No AI-generated capabilities
- No credential handling
- No target writes
- No dependency auto-installation

Success condition met:

Canto can discover installed capabilities for a goal, create a deterministic plan, approve it, execute it, and explain it.

---

## v2.1 — Registry Unification

Goal: unify discovery, planning, execution, approvals, and HTTP visibility around one executable registry view.

Delivered:

- Registry audit
- Canonical execution identity ADR
- HTTP/CLI registry parity
- Capability manifest provider bindings
- Provider binding validation
- Plan steps carrying runnable `(skill, provider)` identity
- Artifact-to-input binding model
- JobService-backed orchestration execution
- Single approval model unification
- Lazy registry reload semantics
- End-to-end unification test

Success condition met:

The same installed capability is visible to CLI registry, HTTP registry, discovery, planning, approval, JobService execution, explanation, and artifact production.

---

## v2.2 — Contract Freeze

Goal: freeze the v1.0 orchestration API contract for external callers.

Delivered:

- Contract freeze audit
- `contract_version` field on orchestration-facing responses
- OpenAPI export
- JSON Schemas
- HTTP orchestration endpoints:
  - `POST /discover`
  - `POST /plans`
  - `GET /plans/{plan_id}`
  - `GET /plans/{plan_id}/explain`
  - `POST /plans/{plan_id}/approve`
  - `POST /plans/{plan_id}/execute`
  - `GET /plans/{plan_id}/events`
- Polling semantics
- Auth placeholder documentation
- Contract compatibility statement
- HTTP contract integration coverage

Success condition met:

The external orchestration loop is frozen as:

```text
Discover → Plan → Approve → Execute → Observe
```

Canto owns execution. External orchestrators call Canto through the contract; they do not supply executors or bypass policy.

---

# Forward Roadmap

The forward plan is three MVP release tiers, built in order — **MVP v1** (single-user,
write-capable, local), **MVP v2** (local team server), **MVP v3** (public server). Each tier is
a usable release and the foundation for the next.

How to read this:

- Build the tiers in order. Within a tier, start with its foundation packets (the state store
  first) and work down the list.
- Workstreams that were previously standalone phases (external integration, MCP adapter, UX,
  remote registry, signing) are folded into the tier that needs them, shown as labeled
  work-packet groups under each tier. **AI-Assisted Authoring** and **Advanced Workflow
  Orchestration** are post-MVP — see the section after the tiers.
- Work-packet IDs (`CP-####`) are stable identifiers carried over from earlier revisions; the
  leading digits reflect the original workstream, not execution order. Sequencing is given by
  list position within a tier, not by the numeric ID.
- State moves off Redis as the system of record, per `docs/adr-state-store.md`: a SQL store
  behind the `StateStore` Protocol (`SqliteStateStore` for v1; `MySqlStateStore`, plus
  `PostgresStateStore` at v3, for the servers), covering jobs, events, approvals, artifact
  metadata, the registry snapshot, and execution plans (`PlanStore` folds in as server-owned
  state). Redis is retained only as an optional event/queue adjunct, never the durable truth.

Each tier extends the previously frozen contract; every contract-affecting change is an explicit
`contract_version` bump, not a silent edit.

---

## MVP v1 — Single-User, Write-Capable (local)

Goal: a single developer runs Canto locally and uses it end to end to perform real guarded
target-system writes — the first genuinely usable release.

Folds in: Orchestrator UX & Developer Experience (formerly v3.2).

Deliverables:

- `SqliteStateStore` as the default system of record (behind the existing `StateStore`
  Protocol), replacing Redis as durable truth; embedded, single-file, ACID, no daemon — see
  `docs/adr-state-store.md`. Covers jobs, events, approvals, artifact metadata, the registry
  snapshot, and execution plans (`PlanStore` folds into the store of record)
- One-time Redis → SQLite state-migration tool for existing local deployments
- Single-user credential vault: scoped local secrets, vault-backed `*_ref` resolution
  (extending the `env:` model), rotation, and guaranteed redaction in artifacts/events/logs
- Guarded target-system writes honoring `destructive` / `production_access` permissions, with
  dry-run → live promotion, idempotency, and a rollback / compensation path
- Write-provider contract and a reference write-capable provider
- Pre-write validation and post-write verification artifacts
- Multi-runtime provider execution (non-Python: node / container / binary) under the same
  policy, bounds, approval, and artifact contract
- Baseline execution hardening: CPU / memory / disk limits and per-job network egress allowlist
- Developer experience (formerly v3.2): improved `canto demo` family, human-readable plan
  display, artifact summary views, plan timeline / event display, better missing-input and
  missing-capability prompts, a troubleshooting guide, and an `examples/` directory
- Local install / packaging of Canto itself and a quickstart
- Seed set of trusted local capabilities, including at least one real write workflow
- 1.0-single-user stability for contract, manifest, and package formats; release notes

Non-goals:

- No multi-user, authentication, or networked exposure (loopback only)
- No unattended or rollback-free writes; no write without a dry-run artifact
- No remote registry or third-party capability trust
- No server-class database or external state daemon required

Success condition:

A single developer installs Canto locally, stores credentials in the vault, installs a trusted
capability, approves a plan, and performs a real reversible guarded write to a target system —
observed and audited — with no networked multi-user surface.

Recommended work packets — core (state, credentials, writes, runtime, packaging):

- CP-5001 — MVP v1 Scope and Design
- CP-5002 — `SqliteStateStore` System of Record (behind the `StateStore` Protocol)
- CP-5003 — Redis → SQLite State-Migration Tool
- CP-5004 — Single-User Credential Vault and Vault-Backed `*_ref` Resolution
- CP-5005 — Secret Rotation and Redaction Guarantees
- CP-5006 — Guarded Write Execution Path (dry-run → live promotion)
- CP-5007 — Idempotency and Rollback / Compensation
- CP-5008 — Write-Provider Contract and Reference Provider
- CP-5009 — Pre-Write Validation and Post-Write Verification
- CP-5010 — Multi-Runtime Provider Execution (node / container / binary)
- CP-5011 — Baseline Resource Limits and Per-Job Egress Allowlist
- CP-5012 — Local Install / Packaging and Quickstart
- CP-5013 — Seed Trusted Capability Set
- CP-5014 — MVP v1 Stability, Release Notes, and Documentation

Recommended work packets — developer experience (formerly v3.2):

- CP-1201 — UX/DX Audit and Design
- CP-1202 — `canto demo` Command Family
- CP-1203 — Human-Readable Plan Display
- CP-1204 — Artifact Summary Views
- CP-1205 — Plan Timeline / Event Display
- CP-1206 — Improved Missing-Input Prompts
- CP-1207 — Improved Missing-Capability Suggestions
- CP-1208 — Troubleshooting Guide
- CP-1209 — `examples/` Workflow Directory
- CP-1210 — Developer-Experience Documentation Pass

---

## MVP v2 — Local Team Server

Goal: deploy one Canto instance on an internal network that a team of humans and AI
orchestrators share, with authenticated identity, per-user isolation, and operability.

Folds in: External Orchestrator Integration (formerly v3.0) and the MCP / Tool Adapter Layer
(formerly v3.1) — the team's humans and model clients reach the shared server through the frozen
HTTP contract and a local MCP bridge.

Deliverables:

- `MySqlStateStore` as the server-tier system of record (behind the `StateStore` Protocol),
  with multi-process concurrency and relational audit/retention queries — see
  `docs/adr-state-store.md`
- Optional Redis adjunct for event fan-out (SSE) and/or an async job queue — never the system
  of record
- Authentication (API keys / bearer tokens) on all mutating endpoints, with a documented
  `contract_version` bump
- Server-populated identity replacing client-supplied `requested_by` / `approved_by`
- Role model (Cantor / operator / viewer) and per-resource authorization
- Identity-stamped audit trail across jobs, plans, approvals, and secret access
- Multi-user secret scoping, ownership, and explicit grants
- Per-user state isolation and visibility rules
- Job-level execution sandboxing between users (stronger than the v1 baseline bounds)
- External orchestrator integration (formerly v3.0): reference client, contract smoke demo,
  request/response examples, human-in-the-loop approval flow, and error-scenario coverage
- MCP / tool adapter (formerly v3.1): a local MCP bridge mapping discover / plan / approve /
  execute / observe / explain / list-artifacts onto the frozen HTTP endpoints
- Deployment and operability: containerized deployment, configuration management, MySQL
  durability / HA and backup-restore, structured logging / metrics / tracing,
  health / readiness / liveness, retention and cleanup, rate limits and quotas
- 1.0-team release with upgrade and state-migration tooling and an operator runbook

Non-goals:

- No public exposure or untrusted third-party capabilities
- No federated / third-party identity providers
- No managed multi-tenant hosting

Success condition:

A team deploys Canto on an internal network, authenticates multiple users and orchestrators
(including model clients via MCP), isolates their work, runs approved guarded writes attributed
to real identities, and operates the service — observe, recover, retain, throttle — from
documented runbooks.

Recommended work packets — core (identity, state, isolation, operability):

- CP-6001 — MVP v2 Scope and Threat Model
- CP-6002 — `MySqlStateStore` Server-Tier System of Record (behind the `StateStore` Protocol)
- CP-6003 — Optional Redis Event-Bus / Queue Adjunct (event fan-out, async execution)
- CP-6004 — API Key / Bearer Token Authentication
- CP-6005 — Server-Populated Identity
- CP-6006 — Role and Authorization Model
- CP-6007 — Identity-Stamped Audit Trail
- CP-6008 — Multi-User Secret Scoping and Grants
- CP-6009 — Per-User State Isolation and Visibility
- CP-6010 — Job-Level Execution Sandboxing
- CP-6011 — Containerized Deployment and Configuration
- CP-6012 — MySQL Durability / HA and Backup-Restore
- CP-6013 — Logging, Metrics, and Tracing
- CP-6014 — Health / Readiness / Liveness and Retention
- CP-6015 — Rate Limits and Quotas
- CP-6016 — Upgrade / State-Migration Tooling and Operator Runbook
- CP-6017 — MVP v2 Release Notes and Documentation

Recommended work packets — external orchestrator integration (formerly v3.0):

- CP-1001 — External Orchestrator Integration Design
- CP-1002 — Python Client Library
- CP-1003 — Contract Smoke Test Script
- CP-1004 — External Orchestrator Example Prompts
- CP-1005 — Human Approval Demo
- CP-1006 — Error Scenario Examples
- CP-1007 — End-to-End External Demo
- CP-1008 — External-Integration Documentation Pass

Recommended work packets — MCP / tool adapter (formerly v3.1):

- CP-1101 — MCP Adapter Design
- CP-1102 — MCP Tool Definitions (discover, plan, approve, execute, observe, explain, list artifacts)
- CP-1103 — Local MCP Server / Bridge Implementation
- CP-1104 — MCP-to-Frozen-HTTP Endpoint Mapping
- CP-1105 — Approval and Execution Boundary Safety Notes
- CP-1106 — Adapter Tests Using Mock Capabilities
- CP-1107 — MCP-Adapter Documentation Pass

---

## MVP v3 — Public Server

Goal: operate Canto as a publicly reachable service that can safely accept and run capabilities
from many mutually-distrusting sources at scale.

Folds in: Remote Registry & Publishing (formerly v4.0) and Package Trust, Signing & Provenance
(formerly v4.1) — public sharing and trust-at-scale are public-tier concerns.

Deliverables:

- Managed / HA MySQL **or** PostgreSQL as the system of record at public scale
  (`MySqlStateStore` / `PostgresStateStore`, operator's choice), with a Redis adjunct for event
  fan-out and queueing where required — see `docs/adr-state-store.md`
- Full sandboxed isolation of untrusted and remotely-installed capabilities
  (container / namespace / seccomp-class)
- Hardened per-job network egress control and abuse protection at public scale
- Remote registry and publishing (formerly v4.0): remote registry, metadata schema,
  `canto registry add/remove/list/search`, `canto publish`, package download flow, registry
  cache, and local install from a downloaded archive
- Package trust, signing, and provenance (formerly v4.1): signing, signature verification,
  publisher identity, provenance fields, `canto verify`, and handling for unsigned / invalid /
  revoked / unknown packages — enforced at public scale
- Federated / third-party identity provider integration
- Public-grade multi-tenant isolation and quota / abuse controls
- Independent public security audit and penetration-test sign-off
- Public trust, abuse, and incident-response policy
- Public release posture and supported-configuration matrix

Non-goals:

- No marketplace or payments
- No autonomous approval or self-trust
- No silent trust escalation for unsigned or unknown packages

Success condition:

Canto runs as a public service where mutually-distrusting users install signed capabilities
from a remote registry and execute approved guarded writes in isolated sandboxes, and the
platform withstands an independent security audit — without any capability exceeding its
declared permissions, network scope, or resource budget.

Recommended work packets — core (isolation, federation, multi-tenant, audit):

- CP-7001 — MVP v3 Scope and Public Threat Model
- CP-7002 — Managed / HA MySQL or PostgreSQL (`PostgresStateStore`) and Redis Adjunct at Public Scale
- CP-7003 — Sandboxed Isolation of Untrusted / Remote Capabilities
- CP-7004 — Hardened Egress Control and Abuse Protection
- CP-7005 — Remote-Registry Trust Automation at Public Scale (implementation in the Remote Registry group below)
- CP-7006 — Enforced Signing / Provenance at Public Scale (implementation in the Signing group below)
- CP-7007 — Federated / Third-Party Identity Integration
- CP-7008 — Public Multi-Tenant Isolation and Quotas
- CP-7009 — Independent Security Audit and Pen-Test Sign-Off
- CP-7010 — Trust, Abuse, and Incident-Response Policy
- CP-7011 — MVP v3 Public Release and Supported-Configuration Matrix

Recommended work packets — remote registry and publishing (formerly v4.0):

- CP-2001 — Remote Registry Design
- CP-2002 — Registry Metadata Schema
- CP-2003 — `canto registry add/remove/list`
- CP-2004 — `canto registry search`
- CP-2005 — `canto publish` Design
- CP-2006 — Package Download Flow
- CP-2007 — Trust and Provenance Metadata
- CP-2008 — Checksum Verification on Download
- CP-2009 — Registry Cache
- CP-2010 — Local Install from Downloaded Archive
- CP-2011 — Remote-Registry Documentation Pass

Recommended work packets — package trust, signing, and provenance (formerly v4.1):

- CP-2101 — Package Signing Design
- CP-2102 — Signature Verification
- CP-2103 — Publisher Identity Metadata
- CP-2104 — Provenance Fields
- CP-2105 — Trust Policy Document
- CP-2106 — `canto verify` Command
- CP-2107 — Unsigned / Invalid / Revoked / Unknown Package Handling
- CP-2108 — Signing-and-Trust Documentation Pass

---

# Post-MVP

Deferred until after the MVP tiers ship. Not required for a usable release; each builds on the
proven MVP foundation.

## AI-Assisted Capability Authoring (formerly v5.0)

Goal: let an orchestrator help create or modify capabilities while Canto enforces scaffold, validation, tests, packaging, approval, and install boundaries.

Deliverables:

- Authoring workflow design
- Missing-capability-to-scaffold workflow
- Orchestrator-generated implementation proposal format
- Test generation guidelines
- Review gates
- Pack/install only after validation and approval
- Audit trail for AI-assisted changes

Non-goals:

- No autonomous code trust
- No self-installing generated capabilities
- No bypass of tests or approval
- No production writes by generated capabilities unless separately approved

Success condition:

A missing capability can be scaffolded, implemented with AI assistance, tested, packed, reviewed, approved, and installed without bypassing Canto's safety model.

Recommended work packets:

- CP-3001 — AI-Assisted Authoring Workflow Design
- CP-3002 — Missing-Capability-to-Scaffold Workflow
- CP-3003 — Orchestrator Implementation Proposal Format
- CP-3004 — Test Generation Guidelines
- CP-3005 — Review Gates
- CP-3006 — Validation-and-Approval-Gated Pack/Install
- CP-3007 — Audit Trail for AI-Assisted Changes
- CP-3008 — AI-Authoring Documentation Pass

---

## Advanced Workflow Orchestration (formerly v6.0)

Goal: support richer workflows after the linear, approved, artifact-based model has proven stable.

Potential deliverables:

- Branching plans
- Conditional steps
- Parallel-safe execution
- Retry policy
- Plan cancellation
- Resume from failed step
- Artifact versioning
- Plan templates

Non-goals:

- No uncontrolled autonomy
- No hidden execution
- No background mutation without explicit approval

Success condition:

Canto can express and execute richer workflows while maintaining explainability, artifact traceability, approval gates, and bounded execution.

Recommended work packets:

- CP-4001 — Advanced Workflow Model Design
- CP-4002 — Branching Plans
- CP-4003 — Conditional Steps
- CP-4004 — Parallel-Safe Execution
- CP-4005 — Retry Policy
- CP-4006 — Plan Cancellation
- CP-4007 — Resume From Failed Step
- CP-4008 — Artifact Versioning
- CP-4009 — Plan Templates
- CP-4010 — Advanced-Workflow Documentation Pass

---

## Deferred Until Explicitly Approved

Now scheduled (moved out of deferral):

- Credential vaulting → MVP v1
- Target-system writes → MVP v1
- Non-Python runners → MVP v1
- Full multi-user authentication and authorization → MVP v2
- Hosted/public Canto service → MVP v3
- Remote registry trust automation → MVP v3
- Federated / third-party identity providers → MVP v3
- Parallel execution → Post-MVP (Advanced Workflow Orchestration)

The following remain intentionally deferred:

- Autonomous package installation
- Dependency auto-installation
- Marketplace / payment features
- Autonomous approval or self-trust

---

## Release Status Summary

Current completed milestone:

```text
v2.2 — Orchestration Contract Freeze
```

Next recommended milestone:

```text
MVP v1 — Single-user, write-capable (local)
  first packet: CP-5002 (SqliteStateStore system of record)
```

MVP tiers (forward spine, built in order):

```text
MVP v1 — Single-user, write-capable (local)
MVP v2 — Local team server
MVP v3 — Public server
```

Post-MVP: AI-Assisted Authoring, Advanced Workflow Orchestration.

Strategic direction:

```text
Canto is not the AI.
Canto is the governed capability runtime that AIs and humans can call.
```
