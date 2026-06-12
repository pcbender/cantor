# CP-1407 — Architecture Language Freeze and Adoption Record

Status: frozen

Freeze date: June 12, 2026

## Decision

Canto's normal public vocabulary is frozen as follows:

- **Developer**: the authorized person supervising governed work.
- **Worker**: a human, model, or approved harness performing bounded assigned
  work.
- **Toolbox**: an installed reusable package of Operations, Tools, metadata, and
  implementation bindings.
- **Operation**: a named outcome-oriented kind of work.
- **Run**: one recorded attempt to perform an Operation.
- **Result**: the reviewable outcome and evidence from a Run or Worker session.
- **Guardrails**: the enforced boundaries governing work.
- **Catalog**: the local user-facing inventory of installed Toolboxes and
  available Operations.
- **Review**: human judgment over an exact Result.
- **Apply**: a qualified action that makes an accepted Result affect a named
  canonical or target state.

Core authority statement:

> Canto assigns an approved Toolbox and bounded Operation to a Worker. The
> Worker performs the work under Guardrails, Canto records the Result, and the
> Developer decides whether that exact Result may be Applied.

The Developer authorizes Apply. Canto verifies and performs it. A Worker cannot
self-assign, expand scope, self-approve, or Apply its own Result.

## Workflow Language

Normal public workflow:

```text
Find -> Plan -> Approve -> Run -> Review
```

Passive observation uses Status, Timeline, or Events. Review is reserved for
human judgment.

The frozen orchestration API remains:

```text
Discover -> Plan -> Approve -> Execute -> Observe
```

No endpoint, wire field, status value, schema, or contract meaning changed.

## Internal and Advanced Language

The following remain authoritative internal or advanced terms:

- Capability and `capability@version` for packages and provenance;
- Skill and Provider, including `(skill, provider)`, for execution identity;
- Job for persisted Run records;
- Artifact for individually recorded Result files and metadata;
- Registry for package/runtime stores and source configuration;
- Policy for machine-readable enforcement;
- Approval for the persisted authorization model;
- ExecutorProfile and delegation `executor_*` fields/statuses;
- Promotion for internal exact-result application mechanisms.

Public documentation may introduce the friendly term and then show the exact
internal identifier where users need to author packages, call APIs, inspect
JSON, diagnose failures, or operate compatibility commands.

## Qualified Apply Rule

Never present a bare Apply action. Labels and confirmations must name:

1. the exact Result or revision;
2. the canonical or target state;
3. whether the action requests Approval or performs a verified mutation.

Patch promotion, governed live writes, and recovery remain distinct internal
paths with different safety semantics.

## Intentional Exceptions

Discouraged public terms may remain when they are:

- literal CLI commands, options, JSON keys, status values, IDs, filenames, or
  configuration keys;
- manifest fields, package layouts, API paths, OpenAPI, or JSON Schemas;
- Python classes, services, event names, persisted records, or diagnostics;
- advanced package, runtime, Policy, Registry, or Provider documentation;
- completed packet titles, ADRs, release notes, superseded designs, or other
  historical implementation records;
- references to an actual external orchestrator rather than the supervising
  Developer role.

The historical `docs/Canto Delegated Executor Workspaces.md` remains
superseded source material. Active guidance is
`docs/delegated-executors.md`, which now leads with Worker language.

## Deferred Adoption Work

- CP-1404 approves a future additive `canto find` alias for `canto discover`.
  Implementation requires a separate packet and parity tests.
- CLI help and human-readable dashboard label changes require a separate
  implementation packet. Existing JSON output remains stable.
- No generic `canto apply` alias is approved.
- Remote Registry language must be decided before MVP v3. Catalog currently
  means local installed inventory and does not mean marketplace.
- Future MVP v2 persisted authorization roles require a separate decision.

## Future Change Rule

A new public surface must use this vocabulary or record a specific exception.
Changing a frozen definition requires:

1. an Architecture Language decision record;
2. classification of affected Public, Advanced, Internal, and Historical
   surfaces;
3. compatibility review for commands, persistence, packages, and HTTP;
4. migration and verification evidence.

Documentation changes alone must never rename machine contracts.

## Verification

The CP-1406 audit records exact compatibility evidence. At freeze:

- `git diff --check` passes;
- `.venv/bin/pip check` reports no broken requirements;
- focused bootstrap and Worker launch tests pass (`21 passed`);
- `.venv/bin/pytest tests import_capability/tests` passes (`281 passed`) with
  one existing non-blocking Starlette deprecation warning;
- checked-in OpenAPI and JSON Schemas remain synchronized and unchanged.

## Adoption

README now leads with the public product model. Current public and advanced
guides use the vocabulary or identify why exact internal terms are required.
Generated repository manuals and launch prompts distinguish Developer and
Worker authority while preserving compatibility filenames and fields.

This record completes CP-1407 and closes the Architecture Language Sprint.
