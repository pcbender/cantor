# Canto Architecture Language Lexicon

Status: frozen on June 12, 2026. See
`docs/architecture-language-freeze.md` for adoption rules and exceptions.

## Purpose

Canto's public language must explain the product without requiring users to
understand its internal runtime architecture. This lexicon defines a small,
stable vocabulary for user-facing documentation, prompts, CLI help, messages,
and future interfaces.

Internal model names and frozen contract identifiers remain unchanged unless a
later compatibility-reviewed packet explicitly changes them.

## Core Statement

> Canto assigns an approved Toolbox and bounded Operation to a Worker. The
> Worker performs the work under Guardrails, Canto records the Result, and the
> Developer decides whether that exact Result may be Applied.

Canto selects and assigns the approved Toolbox, Operation, authority, and
scope. A Worker does not independently choose or expand them.

## Principles

1. Use familiar words before architectural terms.
2. Give each public term one primary meaning.
3. Describe user intent and outcomes, not service implementation.
4. Keep authority explicit: Workers perform work; Developers approve changes;
   Canto enforces the boundary.
5. Prefer verbs for actions and nouns for durable records.
6. Preserve precise internal terms in code, schemas, logs, diagnostics, and
   advanced views where translation would reduce accuracy.
7. Do not rename frozen HTTP fields, status values, model classes, package
   fields, or persisted records through documentation alone.

## Public Roles

### User

A person or calling system that states a goal, supplies permitted inputs, and
reviews the visible outcome. A User may also be a Developer when supervising
work.

User is a generic participant term, not an authority-bearing role. Developer
and Worker describe authority in a governed workflow.

### Developer

The person supervising governed work. A Developer defines or confirms scope,
reviews Plans and Results, grants or rejects Approval, requests revisions, and
decides whether an accepted Result should be Applied.

Developer and Worker describe authorities in a specific workflow, not permanent
human identities. The same person may occupy either role in different work,
but no actor may approve or Apply the same Result while acting as its Worker.

`Developer` replaces `Cantor` in public language. It does not rename an
existing internal identity, role enum, or persisted value by itself.

In non-software contexts, Developer means the authorized person developing or
changing the target system, workflow, content, or managed state.

### Worker

A human, local model, cloud model, or approved harness assigned to perform
bounded work. A Worker follows the assigned Operation, Toolbox, inputs,
Workspace, and Guardrails. A Worker cannot self-assign, broaden scope,
self-approve, or Apply its own Result.

`Worker` replaces `Executor` in public language. `ExecutorProfile` and related
internal records remain unchanged until separately migrated.

### Canto

The governed runtime and coordinator. Canto finds eligible Operations, creates
Plans, assigns approved work, enforces Guardrails, records Runs and Results,
manages Approval, and performs Apply after explicit authorization and
verification. The Developer authorizes Apply; Canto does not decide to Apply a
Result on its own.

## Public Objects

### Toolbox

A reusable, versioned collection that gives Canto the Operations, Tools,
metadata, and implementation bindings needed for a kind of work.

Publicly, `Toolbox` normally represents a capability package. It is assigned by
Canto for a task; it is not an unrestricted bag of commands selected by a
Worker.

Example: a website inventory Toolbox may contain an inventory Operation, a
public-site crawler implementation, report generation, and declared outputs.

### Operation

A named kind of work Canto can perform, expressed in outcome-oriented terms.
An Operation defines what is requested, not which implementation performs it.

Publicly, `Operation` maps to the internal `Skill` concept. For example,
`inventory_site` is an Operation; `public_html_crawler` is an internal Provider
binding that can perform it.

Operation is the formal noun for labels, reference documentation, and precise
explanations. General prose should prefer the outcome when that reads more
naturally, for example: "Canto found two ways to inventory this site."

### Tool

A bounded utility used while performing an Operation. Tool remains acceptable
in both public and internal language when it refers to a concrete utility, not
to a whole Toolbox or Operation.

### Plan

A reviewable proposal for satisfying a goal through one or more ordered
Operations. A Plan shows required inputs, expected Results, risks, missing
values, and Approval requirements. It does not perform work.

### Run

One recorded attempt to perform an Operation with specific inputs,
implementation identity, Guardrails, and status. Publicly, `Run` maps to an
internal Job.

### Result

The reviewable outcome of a Run or delegated Worker session. A Result may
include files, reports, patches, command evidence, logs, metadata, or other
Artifacts. Result is the public umbrella term; Artifact remains the precise
internal term for an individually recorded output.

### Approval

An explicit, persisted decision authorizing a gated action. Approval is not a
general statement that work looks good; it authorizes the specific Plan, Run,
write, recovery, or Apply action bound to its recorded evidence.

Only the Developer or another identity explicitly authorized by Guardrails may
grant Approval. Canto records the approving identity and verifies that the
Approval still matches the action and evidence being used.

Public Approval language may describe several approval moments, but persisted
Approval objects and other decision records remain governed by their
compatibility-reviewed internal models. This lexicon does not create or merge
approval models.

### Apply

To make an accepted Result affect canonical or target state after all required
Approval and verification checks pass.

Apply does not mean start a Run. For delegated development, Apply maps to patch
promotion. For governed writes, it maps to the approved live mutation or
recovery path appropriate to that workflow.

Never present a bare `Apply` action. The action label or confirmation must name
the exact Result and the target state being changed, for example:

- Apply accepted patch to repository.
- Apply approved changes to WordPress site.
- Apply recovery plan to target database.
- Apply Result `result_123` to canonical branch.

### Workspace

An isolated location where a Worker performs assigned work. For delegated
development this is a Canto-managed Git worktree tied to a repository identity
and base commit. Workspace does not imply hostile-code containment.

### Catalog

The user-facing view of installed Toolboxes and available Operations. Catalog
maps to Registry as a presentation concept. Canto searches the Catalog; a
Worker does not use it to independently acquire authority or expand scope.

In local releases, Catalog means installed local inventory. Remote Registry
browsing, package publishing, and source trust require a separate language
decision before MVP v3. `Marketplace` remains deferred and must not be used as
a synonym for Catalog.

### Guardrails

The user-facing description of enforced Policy: allowed inputs, paths,
commands, network access, credentials, approvals, limits, and write controls.
`Policy` remains appropriate in advanced configuration and diagnostics.

## Public-to-Internal Mapping

| Public term | Primary internal concept | Notes |
| --- | --- | --- |
| Developer | Cantor/orchestrator/reviewer role | Public role only until identity models are compatibility-reviewed. |
| Worker | Executor and ExecutorProfile | Human or model assigned bounded work. |
| Toolbox | Capability package or installed Capability | Distribution and provenance identity remain `capability@version`. |
| Operation | Skill | Execution identity remains `(skill, provider)`. |
| Tool | Tool | Same term where it denotes a concrete utility. |
| Plan | ExecutionPlan / workflow candidate | Same public term. |
| Run | Job | Durable execution attempt. |
| Result | Artifact set / DelegationResult | Public umbrella over immutable evidence. |
| Approval | Approval | Same term and same persisted authority object. |
| Apply | Promotion / approved live write or recovery | Context-specific internal implementation. |
| Workspace | DelegationWorkspace / job work directory | Isolated work location. |
| Catalog | Registry view | Installed local inventory, not a remote marketplace. |
| Guardrails | Policy and runtime limits | Friendly summary of enforced controls. |

## Internal and Advanced Terms

These terms remain valid internally and may appear in advanced diagnostics,
API documentation, package authoring, or compatibility material:

- **Capability**: package, version, checksum, risk, and provenance identity.
- **Skill**: internal operation identifier and half of canonical execution
  identity.
- **Provider**: implementation selected to perform a Skill; the other half of
  canonical execution identity.
- **Job**: persisted Run model used by JobService and the runner.
- **Artifact**: individually recorded output with metadata and integrity data.
- **Registry**: runtime and package metadata stores behind the Catalog view.
- **Policy**: machine-readable enforcement rules behind Guardrails.
- **ExecutorProfile**: persisted Worker harness and model configuration.
- **DelegationTask**: persisted delegated-work lifecycle record.
- **Promotion**: internal exact-result application mechanism.

Internal architecture remains anchored on `(skill, provider)` for execution and
`capability@version` for packaging and provenance.

## Discouraged Public Terms

| Avoid in general user language | Prefer | Reason |
| --- | --- | --- |
| Cantor | Developer | Cantor is brand-specific and does not explain authority. |
| Executor | Worker | Executor sounds mechanical and overlaps runtime implementation. |
| Skill | Operation | Skill anthropomorphizes package metadata and conflicts with worker ability. |
| Capability | Toolbox | Capability is abstract and conflates package, ability, and operation. |
| Provider | Omit or describe as implementation | Most users care what happens, not the selected binding. |
| Job | Run | Run is familiar as a recorded execution attempt. |
| Artifact | Result or output | Artifact is precise but implementation-oriented. |
| Registry | Catalog | Catalog describes the visible inventory without implying network behavior. |
| Policy | Guardrails | Guardrails communicates enforced boundaries; Policy remains advanced language. |
| Promote | Apply | Apply describes the user-visible effect on canonical state. |
| Orchestrator | Developer or Canto | Use only when discussing an external orchestration client or architecture. |

Do not mechanically replace these terms in source code, JSON, YAML, database
records, API paths, status enums, or historical documentation.

## Workflow Language

### Goal-to-Result Workflow

Preferred public loop:

```text
Find → Plan → Approve → Run → Review
```

- **Find**: Canto searches the local Catalog for eligible Toolboxes and
  Operations.
- **Plan**: Canto proposes ordered Operations, inputs, Results, and risks.
- **Approve**: the Developer authorizes gated work.
- **Run**: Canto performs approved Operations under Guardrails.
- **Review**: the User or Developer inspects status, Results, and explanations.

The frozen orchestration contract remains:

```text
Discover → Plan → Approve → Execute → Observe
```

The preferred words are a presentation layer, not an immediate API rename.
Future DX work may add `find` aliases, but existing discovery commands and
contract identifiers remain supported.

Passive observation uses precise supporting language:

- **Status** for current state and polling.
- **Timeline** for ordered lifecycle history.
- **Events** for machine-readable observations.
- **Review Result** when human judgment or a decision is required.

Do not label a passive status or event view as Review.

### Delegated Development Workflow

Preferred public loop:

```text
Define work → Assign Worker → Review Result → Request changes or Accept → Apply
```

1. The Developer defines bounded work and Guardrails.
2. Canto assigns an approved Worker profile, Toolbox, Workspace, and scope.
3. The Worker performs the assignment and leaves a Result for review.
4. The Developer reviews immutable evidence and either requests changes,
   rejects the Result, or accepts it.
5. Canto Applies only the exact accepted Result after verification.

The Worker never self-accepts or self-applies.

## Usage Examples

Prefer:

- "Canto found two Operations that can inventory this site."
- "Review the Plan before approving the Run."
- "The Worker completed the assignment and produced a Result."
- "This Run is blocked by Guardrails requiring Approval."
- "Apply the accepted patch to the canonical repository."
- "The Toolbox is installed in the local Catalog."

Avoid:

- "The Executor discovered a Provider and promoted its Artifact."
- "The Worker selected a Capability and expanded its own Policy."
- "Execute the Plan" when the intended action is only to Apply an already
  accepted Result.

## Compatibility Constraints

1. Existing manifests remain valid. Fields such as `skills`, `providers`,
   `tools`, `execution`, `intents`, `inputs`, and `outputs` are not renamed by
   this lexicon.
2. Existing CLI commands remain valid until a separately designed compatibility
   layer introduces aliases or replacements.
3. Frozen HTTP endpoints, request/response fields, status values, and
   `contract_version: 1.0` remain unchanged.
4. Persisted classes, database records, event types, artifact names, package
   formats, and canonical identifiers remain unchanged.
5. Public aliases should be additive first. Removal of established terms
   requires deprecation guidance and the applicable major-version process.
6. Error messages may include a public term followed by the internal identifier
   when precision is useful, for example: `Run job_123 failed`.
7. Historical specifications may retain their original terminology when
   rewriting them would obscure the implementation record.

## Surface Classification for the Sprint

Every occurrence found during the terminology audit should be classified as:

- **Public**: README, quickstarts, normal CLI help, prompts, routine status and
  error messages. Use the frozen public vocabulary.
- **Advanced**: package authoring, policy configuration, diagnostics, API and
  schema reference. Public terms lead; precise internal terms may follow.
- **Internal**: Python models, persisted fields, event names, service classes,
  runner contracts, and compatibility tests. Preserve internal nomenclature.
- **Historical**: completed design records and release notes. Update only when
  current guidance would otherwise be misleading.

## Frozen Decisions

1. **Developer** is the public supervising role. Supervisor is not a peer
   synonym. The non-software clarification above defines its broader use.
2. **Toolbox** is the normal public package metaphor. Capability remains the
   advanced package, provenance, and authoring term.
3. **Find** is the public action. Discover remains in the frozen API and
   advanced orchestration language. Friendly aliases are deferred to DX work.
4. **Review** means human judgment. Status, Timeline, and Events cover passive
   observation.
5. **Apply** is the public change verb, but it must always name the exact Result
   and target state.
6. Lowercase **task** remains ordinary prose. Canto does not introduce a
   capitalized universal Task object. Use DelegationTask only when naming the
   internal persisted model.

## Dogfood Findings

The first local dogfood exercise used a Codex CLI Worker profile backed by
Ollama `qwen2.5-coder:14b`. The model produced tool-call JSON as text instead of
executing the tools. Codex exited successfully, Canto marked the Worker done,
and capture then failed because the Workspace had no changes.

This does not change the lexicon, but it identifies future runtime and UX work:

- distinguish process success from completed assigned work;
- report zero-change Worker sessions before presenting Capture as the next
  action;
- describe model/harness tool-execution compatibility in Worker profile checks;
- keep advisory Workers useful even when they cannot edit a Workspace.

The Graphify Codex `PreToolUse` hook also blocked routine review commands after
repository changes until its hook file was disabled. Graph and Canto hooks need
bounded runtime and fail-open/fail-clear behavior before both are enabled in a
daily dogfood workflow.

## Freeze Rule

After approval, new user-facing surfaces must use this vocabulary or document a
specific exception. Changes to a frozen public definition require an
Architecture Language decision record and a compatibility review. Internal
renames are explicitly out of scope for this language freeze.
