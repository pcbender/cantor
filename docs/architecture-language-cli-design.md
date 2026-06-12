# CP-1404 — CLI, Help, and Message Language Design

Status: approved design; implementation deferred

## Purpose

Define how the frozen public vocabulary should appear in the CLI without
renaming established commands, JSON fields, persisted identifiers, or the
frozen orchestration contract.

This packet is design only. It does not change CLI behavior.

## Rules

1. Existing commands, options, exit codes, and JSON output remain supported.
2. Public terms lead in help and human-readable output; exact internal terms
   remain visible when they identify commands, fields, or diagnostics.
3. Aliases are additive and map to exactly one existing action.
4. An alias must not collapse actions with different Approval or safety
   semantics.
5. Review is reserved for human judgment. Passive inspection says Status,
   Timeline, or Events.
6. A bare Apply command or label is prohibited. The exact Result and target
   must be named, and requesting Approval must not be described as performing
   the mutation.
7. `--json` output remains an internal/advanced compatibility surface and does
   not receive public-language key aliases in this sprint.

## Command Decisions

### Find and Search

`canto find GOAL` is approved as a future additive alias for
`canto discover GOAL`.

Find means goal-oriented matching across installed Toolboxes and Operations.
Its output and exit behavior must remain identical to `discover` unless a
future versioned presentation format is explicitly requested.

`canto search QUERY` remains the literal local Catalog metadata search. Find
must not become an alias for search because the two commands answer different
questions:

- Find: "Which installed Toolbox can satisfy this goal?"
- Search: "Which installed package record matches this query?"

The frozen `POST /discover` endpoint and Discover terminology in contract
documentation remain unchanged.

### Plan and Run

`canto plan` remains unchanged.

`canto run SKILL --provider PROVIDER` already performs one direct internal
Operation binding and remains supported. Help should describe this as running
an Operation while retaining the literal Skill and Provider argument names.

`canto execute PLAN_ID` remains the established plan command and frozen API
verb. No `canto run PLAN_ID` overload is approved because it would conflict
with direct Operation execution. Human-facing prose may say "Run this Plan"
while showing the exact `canto execute` command.

### Runs, Jobs, Results, and Artifacts

The existing `canto job` group and `job_id` values remain unchanged. Help may
describe a Job as the durable record for a Run.

The existing `job artifacts` command and Artifact records remain unchanged.
Human-readable headings may say Results and then identify the Artifact path or
record precisely.

No `run show`, `result`, or `results` alias is approved yet. Those aliases would
need a clear decision about whether they cover Job Artifacts, delegation
Results, or both.

### Workers and Delegation

The `canto delegate` command group remains unchanged. `delegate` describes the
workflow action and does not expose a conflicting universal Task model.

Future presentation changes may use:

- Worker for Executor in help and terminal labels;
- Result for captured delegation evidence;
- Developer for the reviewing/authorizing role;
- Apply readiness for an accepted Result that can affect the canonical
  repository.

Internal options and values such as `--executor`, `executor_id`,
`ExecutorProfile`, status enums, records, and JSON keys remain unchanged.

### Apply, Promotion, and Recovery

No generic `canto apply` alias is approved.

Current promotion commands have different semantics:

- `canto promote JOB_ID` requests Approval for a reviewed write dry run; it does
  not immediately mutate the target.
- `canto delegate promote TASK_ID` applies an already accepted exact patch to
  the canonical repository after verification.
- `canto delegate queue-promote TASK_ID` applies one accepted queued patch when
  unblocked.

Conflating these actions under one bare alias would hide whether the command
requests Approval or performs a verified mutation. Help and confirmations
should instead use qualified phrases:

- "Request Approval to Apply write Result from Run `job_id` to target `X`."
- "Apply accepted Result revision `N` to canonical repository `X`."
- "Apply recovery Result for Run `job_id` to target `X`."

Any future Apply alias must encode or display the Result identity, target, and
whether the command requests Approval or performs the mutation before it is
accepted.

### Capability and Registry Commands

Existing `capability`, `list`, `search`, `inspect`, `install`, `pack`, `export`,
and validation commands remain unchanged.

Normal help may introduce capability packages as Toolboxes and the installed
Registry view as the local Catalog. Exact Capability and Registry language
remains appropriate for package authoring, provenance, paths, diagnostics, and
JSON output.

## Human-Readable Output

The future presentation pass should update headings and prose, not machine
fields.

Recommended delegation dashboard labels:

| Current label | Public label | Compatibility note |
| --- | --- | --- |
| `TASK` | `WORK` or `ASSIGNMENT` | Keep `task_id` in JSON and detail output. |
| `EXECUTOR` | `WORKER` | Keep `executor_id` in JSON. |
| `REV` | `RESULT` | Display the immutable Result revision number. |
| `Artifacts:` | `Results:` | Include the exact Artifact path. |
| `Promotion ready:` | `Ready to Apply accepted Result:` | Only when target and revision are shown. |

`WORK` is preferred over introducing a capitalized Task product object.

Recommended diagnostic pattern:

```text
Run job_123 failed: Provider source_inventory.public_html_crawler exceeded a Guardrail.
```

The public term explains the event; the exact internal identifier preserves
debugging value.

## Help Text Direction

Top-level help should describe Canto as a governed local runtime rather than an
execution broker. Command groups should use these descriptions when an
implementation packet is approved:

- `capability`: author and validate Toolbox packages (Capabilities);
- `skill`: inspect internal Operation identifiers (Skills);
- `provider`: inspect internal Operation implementations (Providers);
- `job`: inspect durable Run records (Jobs);
- `delegate`: coordinate bounded Worker assignments and review exact Results;
- `profile`: manage local Worker profiles (ExecutorProfiles).

Help must not suggest that a Worker chooses its own Toolbox, expands scope,
approves work, or Applies Results.

## Implementation Order

A later implementation packet should proceed in this order:

1. Update top-level and command-group help.
2. Update human-readable labels and messages while snapshotting `--json` output.
3. Add `canto find` as an alias for `discover` with parity tests.
4. Update documentation examples to show Find while retaining Discover in API
   and compatibility sections.
5. Defer any Apply alias until each mutation path can display Result, target,
   Approval semantics, and verification state unambiguously.

## Required Tests for Later Implementation

- Existing commands still parse and return the same exit codes.
- Existing JSON keys and status values are unchanged.
- `find` and `discover` return identical structured results for the same state.
- `search` remains metadata search and is not redirected to discovery.
- Human-readable delegation output says Worker and Result while JSON retains
  `executor_id`, task records, and Artifact fields.
- No help, label, or confirmation presents a bare Apply action.
- OpenAPI and checked-in schemas remain unchanged.

## CP-1404 Acceptance

- Additive alias policy is explicit.
- Find and Search have distinct meanings.
- Direct Run and Plan execution are not overloaded.
- Worker/Result presentation changes preserve internal delegation fields.
- Apply remains qualified and no unsafe generic alias is approved.
- Implementation is deferred to a separately approved packet.
