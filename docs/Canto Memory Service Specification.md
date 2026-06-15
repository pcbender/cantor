# Canto Memory Service Specification

Status: Approved Design
Work packet: CP-1601
Target: Canto platform
Audience: Developers and Canto platform implementers

## 1. Product Thesis

Canto Memory is a governed platform service that helps Workers resolve
repository-specific context, terminology, decisions, outcomes, and references
without requiring the supervising Developer session to over-stuff every work
packet.

The core idea is:

> Existing Canto records store what happened.
> Memory stores what future governed work should know.

Canto Memory is not a transcript archive, not a vector dump, not a Codex-only plugin, and not a replacement for Git, Graphify, documentation, Registry, Vault, StateStore, or Approval.

It is a governed reference and decision layer.

## 2. Problem Statement

In the current Canto model, a Developer session can assign one or more Workers
through Canto. A Worker may use a local or cloud model to perform a bounded
task. Today the supervising session often has to include substantial repository
context in the work packet.

This creates several problems:

1. Work packets become too large and costly.
2. Workers fail when they encounter project-specific references not included in the packet.
3. Workers may guess incorrectly instead of asking for clarification.
4. Stable decisions and terminology must be repeated across many tasks.
5. Context from prior Jobs, Plans, and Delegations is not easily reusable.
6. Multiple Workers in separate terminal sessions cannot share approved repository memory.
7. Raw transcripts and tool outputs are too noisy to use directly as durable memory.

Canto needs a Memory Service that allows Workers to retrieve approved context
and propose new durable knowledge without owning or silently mutating global
terminology or project/repository memory.

## 3. Guiding Principle

Reference evidence broadly.
Promote knowledge narrowly.
Retrieve carefully.
Expire aggressively.

Canto must not duplicate every transcript, event, artifact, Job, Plan, or
Delegation record into memory. Memory points to authoritative evidence and
stores only compact knowledge selected for future retrieval.

## 4. Architectural Position

Canto Memory is a platform service.

It belongs beside:

* StateStore
* Registry
* Vault
* Jobs, Plans, Approvals, and Delegation records
* Worker orchestration

It does not belong inside an ordinary Capability or Toolbox.

`MemoryService` owns lifecycle, retrieval, conflict, and source-reference
rules. StateStore owns persistence and atomic transitions. CLI and future
adapters call MemoryService rather than reading memory tables directly. Memory
does not alter the Capability Registry or create a second execution path.

Capabilities may read memory or propose memories, but they do not own durable memory.

Workers may read memory allowed by scope and policy. Workers may propose
memories. Workers may attach observations and outcomes to existing Canto
records. Workers may not silently create authoritative global terminology or
project/repository memory.

The Developer controls durable global terminology. Repository policy may allow
lower-friction repository-scoped memory. Organization, workspace, and
multi-user authority are deferred until Canto has corresponding identity and
authorization models.

## 5. Relationship to Developer Sessions and Workers

The supervising Developer session remains responsible for giving the Worker a
precise bounded task. Canto remains responsible for enforcing scope and
recording evidence.

However, the supervising session should not have to include every stable
background fact, prior decision, alias, ticket history, terminology rule, or
repository convention in each work packet.

The Worker should receive:

* a task objective
* a scope
* allowed tools
* allowed memory scopes
* retrieval budget
* expected artifacts
* success criteria

When the Worker encounters an unknown reference and the task permits memory
access, it should use the Memory Service before guessing or escalating.

Example unknown references:

* `Developer`
* `CP-1314`
* `Registry Unification`
* `Capability Packaging`
* `Graphify`
* `SPEC-v1.MD`
* `MVP v2`
* `StateStore`
* `Vault`
* `Approval`
* `DelegationResult`

The Worker flow should be:

1. Check the task packet.
2. Check local task/session context.
3. Call Memory Reference Resolver.
4. Call scoped recall or context-pack if needed.
5. Continue if resolved.
6. Ask the supervising Developer session only if still ambiguous.

## 6. Goals

Canto Memory must:

1. Provide scoped, governed memory for all Workers.
2. Support multiple terminal sessions.
3. Support local and cloud Worker models.
4. Reduce repeated prompt stuffing.
5. Resolve project-specific terminology and references.
6. Preserve selected decisions and outcomes across Jobs, Plans, and Delegations.
7. Keep raw Job, Plan, Delegation, and artifact evidence separate from durable
   memory.
8. Allow Workers to propose memory without authoritatively mutating it.
9. Record provenance, author, source, confidence, and lifecycle status.
10. Support expiration, supersession, rejection, deletion, and export.
11. Integrate with existing SQLite system of record first.
12. Expose CLI first.
13. Add MCP adapter later using the same service API.
14. Reference Graphify snapshots and nodes without copying the whole graph.
15. Exclude secrets and credentials strictly.

## 7. Non-Goals

Canto Memory must not:

1. Replace Git.
2. Replace documentation.
3. Replace Graphify.
4. Replace Registry.
5. Replace Vault.
6. Store secrets.
7. Store entire source files.
8. Store entire Graphify graphs.
9. Store raw transcripts as active durable memory.
10. Allow Workers to silently modify global terminology or project/repository
    memory.
11. Treat every observation as truth.
12. Allow unbounded retrieval.
13. Become model-specific.
14. Depend on Codex-specific memory features.
15. Require a daemon for the first implementation unless necessary.

## 8. Memory Classes

Canto should separate four classes of stored information.

### 8.1 Evidence Reference

Evidence Reference points to an existing authoritative Canto record or
repository source.

Examples:

* Job and Job events
* ExecutionPlan and WorkflowStep
* Approval
* DelegationTask, ExecutorSession, ExecutorLaunch, DelegationResult, and review
* produced artifact
* repository document, commit, or ADR

Evidence remains owned by its existing subsystem and is not copied into active
memory. Memory records may carry typed source pointers to it. Evidence is not
retrieved by default as working memory.

Initial source kinds are `job`, `plan`, `approval`, `delegation_task`,
`executor_session`, `executor_launch`, `delegation_result`, `artifact`,
`repository_path`, `commit`, `documentation`, and `graphify`. The service
validates local Canto identifiers when practical. Historical external or
repository pointers may remain readable even when their target is no longer
present locally, but must be labeled unresolved rather than treated as current
proof.

### 8.2 Observation

An Observation is something a Worker noticed.

Examples:

* “Worker found old Cantor terminology in `docs/foo.md`.”
* “Worker observed registry tests rely on fixture X.”
* “Worker found no existing CLI command for memory review.”
* “Worker observed Graphify has a node connecting Registry and Packaging.”

Observations are low-authority.

Observations may expire.

Observations may be proposed for durable memory.

### 8.3 Proposed Memory

Proposed Memory is a memory item in `proposed` status awaiting review or a
conservative repository-policy decision.

Examples:

* “Proposed decision: Canto Memory is a platform service, not a Capability.”
* “Proposed terminology: Developer replaces Cantor across public docs.”
* “Proposed trap: Do not copy Graphify graph contents into memory.”

Proposed Memory requires explicit review unless repository policy permits a
specific repository-scoped promotion. There is no separate candidate-memory
object or second approval system.

### 8.4 Durable Memory

Durable Memory is approved, scoped, retrievable knowledge.

Examples:

* “Developer replaced Cantor as the preferred role name.”
* “Workers may propose memory but cannot silently create authoritative global
  terminology or project/repository memory.”
* “Public registry/package management is core product value.”
* “Graphify remains repository intelligence, not the memory store.”

Durable Memory is retrieved by default only when scope, type, status, freshness, and budget rules allow it.

## 9. Memory Types

Memory items must have an explicit type.

Initial types:

### 9.1 Terminology

Defines preferred terms, deprecated terms, aliases, and project vocabulary.

Examples:

* `Developer` replaces `Cantor`.
* `Capability` means reusable executable package.
* Avoid `Skill` as public terminology because it conflicts with AI prompt-skill usage.

### 9.2 Decision

Approved architecture, terminology, roadmap, or policy decision.

Examples:

* Canto Memory is a platform service.
* CLI first, MCP adapter second.
* SQLite first, daemon later only when needed.

### 9.3 Preference

Developer workflow or style preference.

Examples:

* Prefer dirt-simple developer-facing terminology.
* Prefer model-agnostic and provider-agnostic design.
* Prefer explicit task packets over vague delegation.

### 9.4 Constraint

System, environment, policy, compatibility, or design limit.

Examples:

* Trusted single-user Linux/WSL2 is the initial target.
* Python 3.11+ remains a baseline.
* Secrets must be excluded from memory.

### 9.5 Fact

Externally verifiable information with source and freshness.

Examples:

* Codex uses `AGENTS.md` for agent instructions.
* SQLite WAL supports better read/write concurrency.
* MCP servers expose tools to language models.

Facts must include source and observed date.

Facts should expire unless explicitly stable.

### 9.6 Observation

Worker-produced unverified evidence.

### 9.7 Outcome

What happened during a governed Job, Plan, or Delegation.

Examples:

* CP-703 through CP-712 completed Registry Unification.
* CP-801 through CP-810 froze orchestration contract.
* Verification at commit `COMMIT_SHA` completed with the recorded test result.

Outcomes must identify the governed source record and its freshness. A test
result without a commit, Job, Plan, Delegation, or artifact reference is not a
durable Outcome.

### 9.8 Known Trap

A mistake the system should avoid repeating.

Examples:

* Do not treat Graphify as the memory store.
* Do not key repository memory by folder name.
* Do not let raw Worker observations become authoritative without review.

### 9.9 Open Question

Known unresolved issue.

Examples:

* Should repository memory ever have narrow policy-based activation rules?
* When does Memory Service require a daemon?
* What is the minimal MVP MCP adapter surface?

### 9.10 Summary

Derived context that can be regenerated.

Summaries are useful but lower-authority than source evidence or approved decisions.

## 10. Memory Statuses

Memory items must have lifecycle status.

Initial statuses:

* `observed`
* `proposed`
* `active`
* `superseded`
* `expired`
* `rejected`
* `deleted`

Meaning:

* `observed`: Worker-produced evidence; not authoritative.
* `proposed`: candidate durable memory awaiting review.
* `active`: approved durable memory.
* `superseded`: replaced by newer memory.
* `expired`: no longer retrieved by default.
* `rejected`: reviewed and intentionally denied.
* `deleted`: removed by Developer request or policy.

No meaningful memory should be silently overwritten. Use supersession.

Initial legal transitions are deliberately small:

* `observed` to `proposed`, `expired`, or `deleted`
* `proposed` to `active`, `rejected`, `expired`, or `deleted`
* `active` to `superseded`, `expired`, or `deleted`
* `superseded`, `expired`, and `rejected` to `deleted`

Only an existing Approval decision may transition a proposal to `active` in
the initial release. Rejected, expired, superseded, and deleted items remain
available to administrative audit but are excluded from normal retrieval.
Supersession and the corresponding activation must be atomic.

## 11. Authority and Approval Model

Canto Memory must reuse the single persisted `Approval` model. It must not
introduce `MemoryApproval`, an independent proposal review state machine, or a
second approval endpoint family.

A proposed memory item may link to an Approval through additive,
compatibility-reviewed subject fields such as `subject_kind=memory` and
`subject_id=<memory_id>`. Approval and rejection transition the linked memory
item. Memory events record the result but do not replace Approval as the
authority object.

### 11.1 Worker

A Worker may:

* read memory allowed by task scope
* resolve references
* request a context pack
* attach observations to an existing Job, Plan, or Delegation
* propose memory
* attach outcomes to an existing Job, Plan, or Delegation if permitted

A Worker may not:

* approve global terminology or project/repository memory
* delete memory
* silently update durable memory
* access memory outside granted scope
* retrieve unbounded memory
* store secrets

### 11.2 Developer Session / Orchestrator Component

The supervising Developer session, using Canto's orchestration services, may:

* assign memory scopes in a task packet
* request context packs for task planning
* review Worker observations
* propose durable memories
* recommend promotion
* enforce retrieval budgets
* attach outcomes to existing Canto records

The orchestration component may not approve memory on the Developer's behalf.

### 11.3 Developer

The Developer may:

* approve durable global terminology
* approve future organizational memory when an organization identity model exists
* resolve conflicts
* supersede memory
* delete memory
* export memory
* set repository memory policy
* configure retention and expiration rules

### 11.4 Repository Policy

A repository may define policy for repository-scoped memories.

Possible future policies:

* `manual_review_only`
* `auto_expire_observations`
* `developer_approval_required`

The initial release supports `manual_review_only`, automatic observation
expiration, and Developer approval.

After dogfooding, repository policy may permit automatic activation only for:

* governed Job, Plan, or Delegation outcomes with valid source references;
* source pointers;
* non-conflicting reference aliases matched by deterministic conflict checks.

Repository-local terminology and known traps may be considered later. Decisions,
global or future organization preferences, and durable constraints always
require an individual Approval in this workstream.

## 12. Scopes and Inheritance

Every memory item must have an explicit scope.

Initial durable scope types:

* `global:terminology` for shared terminology in the current single-user Canto
  installation
* `project:<project_id>` for an explicitly configured group of repositories
* `repo:<repo_id>` using the bootstrapped Canto repository identity

Initial transient/source scopes:

* `job:<job_id>`
* `plan:<plan_id>`
* `delegation:<task_id>`
* `session:<session_id>`

Initial inheritance is deliberately small:

* repository work may read assigned repository memory, memory for projects to
  which the repository is explicitly linked, and explicitly allowed global
  terminology;
* Job, Plan, Delegation, and session records do not become durable merely by
  existing;
* transient observations require proposal and review before activation.

Broad global preferences, `workspace`, `organization`, `family`, and durable
Worker scopes are deferred until Canto defines stable owning identities and
authorization rules.

Retrieval must require explicit allowed scopes.

No Worker should retrieve “all memory.”

## 13. Repository Identity

Do not key memory by repository name or folder path alone.

Use repository identity.

Use Canto's existing `repo_id` as the durable lookup identity. Preserve the
existing repository identity evidence:

* canonical repository path
* Git common-dir identity
* initial HEAD
* configured remote URL metadata when present

Example identity:

```json
{
  "repo_id": "repo_55b3b21e37fa4bd99211d780ac1b044b",
  "canonical_path": "/home/mrose/canto",
  "git_common_dir": "/home/mrose/canto/.git",
  "initial_head": "<commit>",
  "remotes": {
    "origin": "https://github.com/pcbender/cantor.git"
  }
}
```

Repository memory binds to `repo_id`. Paths, remotes, and commits are identity
evidence and source context, not replacement keys. Remote-less local
repositories remain fully supported.

### 13.1 Project Identity

Project memory may span more than one repository, so it must not be keyed by a
project name or directory. Canto creates a durable `project_id` in global state.
A project record contains a human-readable label and an explicit set of member
`repo_id` values. Adding or removing a repository is a Developer-controlled,
audited operation.

Repository membership grants eligibility to retrieve the project's memory; it
does not bypass the Worker task's allowed-memory scopes. Organization-wide
membership and inherited organizational policy remain deferred.

## 14. Inclusion Policy

Promote something into durable memory only if it helps a future Worker:

1. understand a project reference
2. avoid repeating a settled decision
3. avoid a known mistake
4. obey a stable preference
5. obey a durable constraint
6. understand the result of prior work
7. find the right source of truth
8. resolve renamed or deprecated terminology
9. continue a multi-step project safely
10. reduce task packet size without increasing ambiguity

Good durable memory categories:

* terminology
* alias
* decision
* preference
* constraint
* outcome
* known trap
* open question
* source pointer

## 15. Exclusion Policy

Do not store the following as durable memory:

1. secrets
2. API keys
3. passwords
4. tokens
5. private keys
6. credentials
7. raw transcript dumps
8. entire source files
9. entire specs
10. entire Graphify graphs
11. large logs
12. temporary shell output
13. unreviewed Worker speculation
14. unscoped observations
15. stale external facts without source and freshness
16. user-sensitive details not required for project execution

Memory may reference documents, commits, Graphify snapshots, and governed
artifacts. It should not copy large source material into memory.

## 16. Secret Detection

Before any memory text, source metadata, or event payload is persisted, Canto
must scan for likely secrets.

Initial detection should combine conservative key-name checks, known token
prefixes, private-key markers, and high-confidence assignment patterns. The
scanner must avoid treating ordinary uses of words such as `token` or
`password` as secrets without value-like material.

* `sk-`
* `ghp_`
* `github_pat_`
* `-----BEGIN PRIVATE KEY-----`
* `AWS_SECRET_ACCESS_KEY`
* credential-like assignments with non-placeholder values
* `.env`-style credential patterns

If suspected secret material is detected:

1. reject memory write
2. record safe audit event
3. do not persist the secret text
4. tell caller the proposal was rejected due to secret-like content

Vault is the only appropriate home for credentials.

## 17. Retrieval Model

Retrieval must be budgeted and scoped.

Each recall request should include:

* query
* allowed scopes
* memory types
* status filter
* max items
* max token budget
* freshness policy
* whether observations are allowed
* whether superseded items are allowed

Default retrieval should include only `active` durable memory and exact global
terminology, project, and repository scopes granted by the caller.

The MVP uses deterministic lexical matching and SQLite FTS5 when available.
No embedding call, model invocation, or network request occurs during recall.
Token budgets use a documented deterministic estimator; they are not claimed
to reproduce every provider tokenizer exactly.

Default context-pack profiles are:

| Profile | Maximum items | Estimated-token budget |
| --- | ---: | ---: |
| `startup` | 12 | 2,500 |
| `resolve-reference` | 5 | 750 |
| `review` | 20 | 4,000 |
| `planning` | 24 | 5,000 |

Callers may request a smaller budget. Increasing a budget requires explicit
policy allowance; profiles are ceilings, not targets that must be filled.

Default retrieval should exclude:

* observations
* rejected items
* deleted items
* expired items
* superseded items
* raw evidence

## 18. Reference Resolver

The Reference Resolver is the highest-value MVP feature.

Command:

```bash
canto memory resolve "Developer" --repo .
```

Output should include:

* reference
* meaning
* memory type
* scope
* status
* source
* confidence
* freshness
* related aliases
* supersession notes if any

Example:

```text
Reference: Developer
Type: terminology
Meaning: Preferred public term replacing the older term "Cantor".
Scope: repo:repo_55b3b21e37fa4bd99211d780ac1b044b
Status: active
Confidence: verified
Source: architecture-language-lexicon review
```

The Worker should use Reference Resolver before escalating unknown project references.

## 19. Context Packs

A context pack is a curated, budgeted memory bundle for a task.

Command:

```bash
canto memory context-pack --repo . --delegation TASK_ID
```

A context pack may contain:

* glossary
* relevant decisions
* relevant constraints
* recent outcomes
* known traps
* open questions
* source pointers
* allowed Graphify references
* temporary session notes if authorized

A context pack should not contain raw transcripts, large logs, full docs, full source files, or entire Graphify graphs.

Example sections:

```text
Glossary
Relevant Decisions
Relevant Constraints
Recent Outcomes
Known Traps
Open Questions
Source Pointers
```

Developer sessions may use context packs during planning.

Workers should use context packs during execution.

## 20. CLI Surface

CLI comes first.

Initial commands:

```bash
canto memory status

canto memory project create
canto memory project list
canto memory project show
canto memory project link-repository
canto memory project unlink-repository

canto memory propose
canto memory list
canto memory show
canto memory request-approval
canto memory supersede
canto memory expire
canto memory delete
canto memory purge

canto memory recall
canto memory resolve
canto memory context-pack

canto memory attach-observation --delegation TASK_ID
canto memory attach-outcome --job JOB_ID

canto memory export
canto memory audit

canto approve APPROVAL_ID
canto reject APPROVAL_ID --reason "..."
```

Memory requests use the existing top-level Approval commands. There is no
parallel `canto memory approve` or `canto memory reject` authority path.

Suggested examples:

```bash
canto memory propose \
  --scope repo:repo_55b3b21e37fa4bd99211d780ac1b044b \
  --type decision \
  --title "Memory is a platform service" \
  --body "Canto Memory belongs beside StateStore, Registry, Vault, Approval, Jobs, Plans, and Delegation records."

canto memory resolve "CP-1314" --repo .

canto memory recall "registry package management" \
  --repo . \
  --types decision,constraint,outcome \
  --max-items 8 \
  --max-tokens 1500

canto memory context-pack \
  --repo . \
  --delegation TASK_ID
```

## 21. Internal Service API

The service API should be shared by CLI and future MCP adapter.

Suggested internal operations:

```python
memory.status()

memory.create_project(input)
memory.list_projects()
memory.get_project(project_id)
memory.link_repository(project_id, repo_id)
memory.unlink_repository(project_id, repo_id)

memory.propose(input)
memory.request_approval(memory_id)
memory.apply_approval_decision(approval_id)
memory.supersede(old_id, replacement)
memory.expire(item_id)
memory.delete(item_id)
memory.purge(item_id, reason)

memory.resolve(reference, scope_context)
memory.recall(query, retrieval_policy)
memory.context_pack(request)

memory.attach_observation(source_ref, observation)
memory.attach_outcome(source_ref, outcome)

memory.export(selector)
memory.audit(selector)
```

MCP must call this same API later.

MCP must not have privileged behavior. The initial CLI is a single-user local
administrative surface. A future server/MCP adapter must derive actor and scope
from a trusted Canto invocation context rather than accepting caller-supplied
authority fields at face value.

## 22. Storage

Initial implementation should use the existing SQLite system of record.

Use SQLite transactions and the existing global Canto state database.

Use FTS for text search.

Use JSON fields only where appropriate.

Do not use loose JSON files for canonical memory.

Do not require a daemon for MVP unless tests prove coordination requires it.
SQLite busy timeouts and transactional writes are the initial concurrency
mechanism.

Read-only commands such as `status`, `show`, `recall`, `resolve`, and
`context-pack` must use read-only StateStore access. They must not initialize
WAL files, run migrations, or otherwise require writable state merely to
inspect memory. When the store cannot be read, they must report a concise state
access error rather than emit a traceback.

The current StateStore schema version is fixed at version 1 and rejects unknown
versions. Memory implementation therefore requires a forward schema-migration
mechanism before adding tables. It must migrate existing user state in place;
resetting or replacing `~/.canto/state.sqlite` is not an acceptable migration.

A daemon may be added later for:

* long-lived multi-process coordination
* subscriptions
* live notifications
* streaming context packs
* locking beyond SQLite transactions
* shared memory service across tools that cannot invoke the CLI efficiently

## 23. Suggested Schema

Initial tables:

```text
memory_items
  memory_id
  scope
  type
  status
  title
  body
  confidence
  source_kind
  source_ref
  source_freshness
  author_kind
  author_id
  approval_id
  repo_id
  project_id
  created_at
  reviewed_at
  expires_at
  superseded_by
  deleted_at

memory_events
  event_id
  memory_id
  event_type
  actor_kind
  actor_id
  payload_json
  created_at

memory_links
  link_id
  from_memory_id
  to_memory_id
  relation
  created_at

memory_aliases
  alias_id
  memory_id
  alias
  normalized_alias
  created_at

memory_tags
  tag_id
  memory_id
  tag
  normalized_tag
  created_at

memory_projects
  project_id
  label
  created_by
  created_at
  updated_at

memory_project_repositories
  project_id
  repo_id
  linked_by
  linked_at

memory_fts
  title
  body
  tags
```

Proposals are represented by `memory_items.status=proposed`. Review authority
is represented by the linked existing Approval object. `memory_events` records
proposal, approval, rejection, supersession, expiration, deletion, and purge
events. This avoids duplicating proposal and approval state across tables.

Confidence should be explicit.

Suggested confidence values:

* `verified`
* `supported`
* `derived`
* `observed`
* `uncertain`

Confidence is epistemic metadata, not authority. Approval is represented by
the linked Approval and the memory lifecycle status; approving an item does
not by itself make the underlying claim verified.

## 24. Graphify Integration

Graphify remains separate.

Graphify supplies repository structure and relationships.

Canto Memory stores governed knowledge, decisions, observations, outcomes, references, and source pointers.

Memory may reference:

* Graphify snapshot ID
* Graphify node ID
* Graphify community ID
* Graphify report path
* Graphify graph artifact path

Memory should not copy the entire Graphify graph.

Example memory item:

```json
{
  "type": "observation",
  "scope": "repo:repo_55b3b21e37fa4bd99211d780ac1b044b",
  "title": "Registry and Packaging are structurally related",
  "body": "Graphify identifies Registry and Capability Packaging as closely related subsystems.",
  "source_kind": "graphify",
  "source_ref": "snapshot:2026-06-15,node:registry,node:capability-packaging",
  "confidence": "derived",
  "status": "observed"
}
```

Graphify facts should be treated as derived repository intelligence, not approved project decisions.

## 25. Codex / AGENTS.md Integration

`AGENTS.md` should not store memory.

`AGENTS.md` should instruct agents how to use Canto Memory.

Example guidance:

```markdown
## Canto Memory

Use `canto memory resolve` for unknown project references before guessing.

Use `canto memory context-pack` when beginning a bounded task.

Workers may propose memory but must not approve durable global terminology or
project/repository memory.

Do not store secrets in memory.
```

This gives Codex and other coding agents predictable guidance while keeping memory in the Canto platform.

## 26. MCP Adapter

MCP is a later adapter, not the primary implementation.

The MCP adapter should expose only safe operations:

* `memory.context_pack`
* `memory.resolve`
* `memory.recall_readonly`
* `memory.propose`
* `memory.attach_observation`
* `memory.attach_outcome`

The MCP adapter should not expose:

* `approve`
* `delete`
* `export`
* unrestricted recall
* raw database access
* Vault access
* unscoped write operations

MCP calls must enforce the same policy as CLI calls.

## 27. Worker Work Packet Additions

A future Worker task packet may include memory policy after the internal model
is implemented. These fields are not additions to the frozen orchestration
HTTP contract and must not be emitted there without compatibility review.

Suggested fields:

```json
{
  "task_id": "CP-MEM-004",
  "worker_role": "worker",
  "repo_id": "repo_55b3b21e37fa4bd99211d780ac1b044b",
  "allowed_memory_scopes": [
    "global:terminology",
    "project:project_0123456789abcdef",
    "repo:repo_55b3b21e37fa4bd99211d780ac1b044b"
  ],
  "allowed_memory_types": [
    "terminology",
    "decision",
    "preference",
    "constraint",
    "outcome",
    "known_trap",
    "open_question"
  ],
  "max_memory_items": 12,
  "max_memory_tokens": 2500,
  "may_propose_memory": true,
  "may_attach_observations": true,
  "may_approve_memory": false,
  "resolve_unknown_references_before_guessing": true
}
```

## 28. Conflict Handling

Memory conflicts must not be silently resolved.

If a proposed memory conflicts with active memory:

1. keep the item in `proposed` status
2. add a `conflicts_with` link to the active item
3. record the detected conflict in an audit event
4. require review
5. allow approval as an atomic supersession
6. preserve the old memory as superseded

Example conflict:

* Active: “Memory does not require a daemon for MVP.”
* Proposed: “Memory must run as a daemon in MVP.”

The review outcome should either reject, supersede, or split by scope.
Initial conflict detection is deterministic and conservative: explicit links,
aliases, and exact normalized reference matches only. Semantic or model-based
conflict detection is deferred and must never silently decide authority.

## 29. Export and Deletion

Developer-controlled export is required.

Export should support:

* all memory
* by scope
* by repo
* by type
* by status
* by date range

Deletion should support:

* soft delete by default
* audit trail
* purge only under an explicit Developer command and documented retention rule
* secret cleanup path if accidental secret-like material is detected

Deleted memory must not be retrieved.

Rejected proposals are hidden from normal administrative lists by default.
They remain visible in audit output and through explicit status or audit flags.

Default retention is:

| Record class | Retention |
| --- | --- |
| observations | 30 days |
| observations classified as low value | 7 days |
| generated summaries | 90 days |
| pending proposals | 90 days |
| governed outcomes | indefinite |
| rejected or superseded items | audit-only, indefinite until Developer deletion |

Expiration removes an item from normal retrieval but preserves its audit
history. Low-value observation retention applies only when the item carries an
explicit policy or author classification; Canto does not infer low value with a
model. When a pending proposal reaches its retention limit, expiration and the
linked pending Approval's rejection must occur atomically with a system
retention reason. This is policy cleanup, not approval on the Developer's
behalf. Retention processing must be deterministic and auditable.

Because secret-like content must be rejected before persistence, the normal
secret path records only a safe rejection event. Purge exists for legal,
privacy, corruption, or legacy-remediation cases; it is not ordinary lifecycle
management.

## 30. Acceptance Criteria

The MVP is acceptable when:

1. Memory records are stored in SQLite.
2. Every memory item has scope, type, status, source, author, timestamps, and confidence.
3. Workers can propose memory through a scope-limited service context.
4. Workers cannot approve durable global terminology or project/repository
   memory.
5. Developer can approve and reject through the existing Approval model, and
   can supersede, expire, delete, purge, and export memory.
6. CLI supports propose, list/show, request-approval, recall, resolve, and
   context-pack; existing top-level Approval commands make decisions.
7. Retrieval is scoped and budgeted.
8. Unknown references can be resolved from durable terminology and alias memory.
9. Job, Plan, and Delegation observations can be attached by typed source
   reference without becoming durable memory.
10. Graphify references can be stored without copying the graph.
11. Secret-like content is rejected before persistence.
12. Tests cover memory lifecycle, scope filtering, supersession, expiration, conflict handling, and retrieval budgets.
13. Read-only inspection does not require writable state or create WAL files.
14. No Memory Service field or endpoint is added to the frozen orchestration
    HTTP contract without compatibility review.
15. Project scopes use durable project identity and explicit repository
    membership.
16. Default context-pack budgets and retention rules are enforced.
17. Existing tests continue passing.

## 31. Candidate Work Areas

This section records Echo's original proposal decomposition for design history.
It is superseded by `docs/canto-memory-service-implementation-plan.md`. Do not
implement the `CP-MEM-*` labels below; the canonical proposed sequence is
CP-1601 through CP-1614. Schema migration and reuse of the existing Approval
object remain prerequisites, and MCP remains post-MVP.

### CP-MEM-001 — Memory Domain Model

Objective: Define the memory concepts and policy model.

Deliverables:

* memory types
* memory statuses
* memory classes
* scope model
* project identity and explicit repository membership
* authority rules
* inclusion/exclusion rules
* conflict rules
* retrieval budget rules

Acceptance:

* docs added
* terminology consistent
* no code behavior change required unless existing docs conflict

### CP-MEM-002 — SQLite Schema and Migrations

Objective: Add persistent memory storage to the existing SQLite system of record.

Deliverables:

* `memory_items`
* Approval subject linkage
* `memory_events`
* `memory_links`
* `memory_projects`
* `memory_project_repositories`
* FTS support
* migration tests

Acceptance:

* migrations apply cleanly
* forward migration from existing user state is tested
* failed migration leaves the prior database recoverable
* schema supports required fields
* tests pass

### CP-MEM-003 — Memory Proposal and Approval Linkage CLI

Objective: Implement basic governed write flow.

Deliverables:

* `canto memory propose`
* Developer-controlled project create/list/show/link/unlink commands
* `canto memory list`
* `canto memory show`
* `canto memory request-approval`
* `canto memory supersede`
* `canto memory expire`
* `canto memory delete`
* `canto memory purge`
* integration with existing `canto approve` and `canto reject`

Acceptance:

* Worker can propose
* Developer can approve/reject
* the existing Approval object authorizes activation
* rejection preserves audit
* supersession does not overwrite silently
* delete excludes from retrieval

### CP-MEM-004 — Scoped Recall

Objective: Implement budgeted, scoped retrieval.

Deliverables:

* `canto memory recall`
* scope filtering
* global terminology, project, and repository inheritance
* type filtering
* status filtering
* expiration filtering
* item and token budget enforcement
* named default budget profiles

Acceptance:

* recall excludes disallowed scopes
* recall excludes expired/rejected/deleted by default
* recall respects max items
* recall respects budget
* tests cover cross-scope inheritance

### CP-MEM-005 — Reference Resolver

Objective: Let Workers resolve unknown project references.

Deliverables:

* `canto memory resolve`
* terminology lookup
* alias lookup
* outcome lookup
* open question lookup
* source display

Acceptance:

* resolves active terminology
* resolves deprecated aliases
* returns confidence and source
* returns ambiguity when multiple matches exist
* does not guess when unresolved

### CP-MEM-006 — Context Packs

Objective: Produce curated context bundles for Developer sessions and Workers.

Deliverables:

* `canto memory context-pack`
* glossary section
* decisions section
* constraints section
* outcomes section
* known traps section
* open questions section
* source pointers section

Acceptance:

* context pack respects scope
* context pack respects token budget
* named startup, resolve-reference, review, and planning profiles are enforced
* context pack excludes raw evidence by default
* context pack is deterministic enough for tests

### CP-MEM-007 — Existing Record Integration

Objective: Attach observations and outcomes to existing governed records.

Deliverables:

* `canto memory attach-observation`
* `canto memory attach-outcome`
* Job ID linkage
* Plan ID linkage
* DelegationTask, session, launch, and Result linkage
* Worker/model provenance where already recorded
* audit events

Acceptance:

* observations remain non-durable by default
* outcomes can be reviewed/promoted
* existing history links to memory proposals without copying its payload
* Worker cannot approve durable memory

### CP-MEM-008 — Graphify Reference Integration

Objective: Allow memory to reference Graphify snapshots and nodes.

Deliverables:

* Graphify source kind
* Graphify snapshot reference fields
* Graphify node/community/report references
* validation for graph reference metadata

Acceptance:

* memory item can reference Graphify snapshot
* memory does not copy full graph
* recall can show Graphify source pointer
* absent local graph data does not invalidate a historical source pointer
* live Graphify reference validation is deferred

### CP-MEM-009 — Secret Detection

Objective: Prevent secrets from entering memory.

Deliverables:

* secret-like pattern scanner
* rejection path
* safe audit event
* tests for common token/key patterns

Acceptance:

* API keys rejected
* private keys rejected
* token-like values rejected
* rejected secret text is not persisted
* caller receives safe error

### CP-MEM-010 — MCP Adapter (Post-MVP Candidate)

Objective: Expose safe memory operations to AI clients.

Deliverables:

* `canto memory mcp`
* tools:

  * `memory.context_pack`
  * `memory.resolve`
  * `memory.recall_readonly`
  * `memory.propose`
  * `memory.attach_observation`
  * `memory.attach_outcome`
* policy enforcement through same service API as CLI

Acceptance:

* MCP cannot approve memory
* MCP cannot delete memory
* MCP cannot perform unrestricted recall
* MCP respects task/repo scope
* CLI and MCP behavior match

### CP-MEM-011 — Export and Audit

Objective: Support Developer ownership and reviewability.

Deliverables:

* `canto memory export`
* `canto memory audit`
* export by scope/type/status/date/repo
* audit log display
* deterministic retention processing

Acceptance:

* exports are deterministic
* deleted items excluded unless explicitly requested
* audit shows proposal/review/supersession/deletion events
* rejected proposals are hidden from normal lists by default
* retention expiry preserves audit and resolves linked pending Approval state
* tests cover export filters

## 32. Approved Design Defaults

Developer review established these defaults:

1. Context packs use the `startup`, `resolve-reference`, `review`, and
   `planning` profiles defined in the Retrieval Model.
2. Policy-based activation after dogfooding is limited to governed outcomes,
   source pointers, and non-conflicting reference aliases. Decisions,
   preferences, and durable constraints remain approval-gated.
3. Rejected proposals are hidden from normal lists and retained in audit.
4. Retention follows the table in Export and Deletion.
5. The first release supports repository memory, explicitly identified project
   memory, and global terminology. Broad global preferences are deferred.

## 33. Recommended MVP Boundary

The MVP should include:

* SQLite schema
* memory lifecycle
* CLI propose, inspect, request-approval, recall, resolve, and context-pack
* existing top-level Approval commands for approval and rejection
* scoped recall
* reference resolver
* context packs
* Job, Plan, and Delegation observation/outcome references
* secret detection
* opaque Graphify source pointers

The MVP should defer:

* daemon
* MCP adapter and any HTTP contract additions
* vector search
* cloud sync
* multi-user permissions
* broad global preferences
* workspace, organization, and family scope hierarchy
* automatic memory generation from full transcripts
* live validation of Graphify references

## 34. Summary

Canto Memory is not “every agent shares the same brain.”

The better product idea is:

> Every governed Worker can retrieve approved context and propose durable
> knowledge without owning or silently mutating global terminology or
> project/repository memory.

That keeps work packets smaller, gives Workers a safe way to resolve ambiguity,
preserves Developer authority, and prevents raw execution noise from becoming
permanent confusion.
