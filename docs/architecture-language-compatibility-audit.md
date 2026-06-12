# CP-1406 — Architecture Language Compatibility Audit

Status: complete

## Scope

Verify that the Architecture Language Sprint changes presentation and
Canto-owned agent instructions without silently renaming or reinterpreting
runtime, package, persistence, CLI, or frozen HTTP interfaces.

## Result

The migration is compatible. Public documentation and Canto-owned role prose
now lead with Developer, Worker, Toolbox, Operation, Run, Result, Guardrails,
Catalog, Review, and qualified Apply actions. Internal identities and machine
interfaces remain unchanged.

## Verified Unchanged

### Execution and Packaging

- Canonical execution identity remains `(skill, provider)`.
- Package and provenance identity remains `capability@version`.
- Capability manifest fields, package paths, archive format, checksums, and
  Registry metadata are unchanged.
- Provider execution, JobService, runner behavior, Artifact collection, Policy
  enforcement, and Approval behavior are unchanged.

### Delegation Persistence and Commands

- `DelegationTask`, `ExecutorProfile`, `ExecutorSession`, `ExecutorLaunch`, and
  related Python models retain their names and fields.
- `executor_id`, `executor_working`, and other persisted values are unchanged.
- `.canto/delegate.toml` retains `orchestrator_instructions` and
  `executor_instructions` keys.
- `.canto/agents/orchestrator.md` and `.canto/agents/executor.md` remain the
  compatibility filenames.
- Existing `canto delegate` commands, options, exit behavior, and JSON fields
  are unchanged.
- Promotion implementation and commands remain unchanged. Public prose calls
  the verified effect a qualified Apply action without adding a generic Apply
  command.

### Frozen Orchestration Contract

- HTTP endpoints and methods are unchanged.
- Request and response fields are unchanged.
- Status values and transitions are unchanged.
- Checked-in `docs/openapi.json` and `docs/schemas/*.json` have no diff.
- `contract_version: 1.0` remains unchanged.
- The exact contract loop remains Discover -> Plan -> Approve -> Execute ->
  Observe.

The public Find -> Plan -> Approve -> Run -> Review loop is presentation only.

## Additive Behavior

`canto repo init` now refreshes three Canto-owned instruction manuals so an
existing bootstrapped repository receives the frozen role language:

- `.canto/agents/shared.md`;
- `.canto/agents/orchestrator.md` (Developer manual);
- `.canto/agents/executor.md` (Worker manual).

The delimited Canto section in `AGENTS.md` was already refreshable. Human text
outside that section remains preserved. Configuration, repository identity,
secrets, durable state, and user-authored files outside the Canto-owned manuals
are not rewritten.

Codex CLI launch prompts now state the Worker authority explicitly. The command
argv, sandbox mode, profile lookup, task state transitions, session records,
launch records, and captured provenance remain unchanged.

## Verification

Commands run on June 12, 2026:

```bash
git diff --check
.venv/bin/pip check
.venv/bin/pytest tests/test_repository.py tests/test_delegation_executor.py
.venv/bin/pytest tests import_capability/tests
```

Results:

- formatting check passed;
- no broken Python requirements;
- focused bootstrap and launch suite: `21 passed`;
- full project and import-capability suite: `281 passed`, with one existing
  non-blocking Starlette `TestClient` deprecation warning.

The full suite includes checked-in OpenAPI and JSON Schema synchronization
tests.

## Deferred

- The additive `canto find` alias and CLI presentation changes remain future
  implementation work under the approved CP-1404 design.
- No generic Apply alias is approved.
- Renaming internal Executor, Job, Artifact, Capability, Skill, Provider,
  Registry, Policy, or Promotion identifiers requires a separate compatibility
  decision and is not implied by this sprint.
- Future MVP v2 authorization roles require their own role-model decision; this
  public Developer term does not silently rename a persisted role.

## CP-1406 Acceptance

- Machine contracts and canonical identities are unchanged.
- Existing manifests and packages remain valid.
- Existing CLI and delegation state remain compatible.
- The frozen HTTP contract and generated artifacts remain synchronized.
- Focused and full tests pass.
