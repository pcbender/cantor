# Governed Memory Service

Canto Memory stores compact, reviewed context for future governed work. It is
not a transcript archive, credential store, vector database, or replacement for
Git, Graphify, Jobs, Plans, Delegations, artifacts, or documentation.

## Scopes

- `global:terminology`: shared single-user terminology only.
- `project:<project_id>`: memory shared by explicitly linked repositories.
- `repo:<repo_id>`: memory for one bootstrapped repository identity.

Workers receive explicit memory scopes. Project membership makes a repository
eligible for project memory but does not grant a Worker that scope by itself.

## Basic Flow

```bash
canto memory propose \
  --scope repo:REPO_ID \
  --type terminology \
  --title Developer \
  --body "The authorized person governing Canto work."

canto memory request-approval MEMORY_ID
canto approve APPROVAL_ID

canto memory resolve Developer --repo .
canto memory recall "approval model" --repo .
canto memory context-pack --repo . --profile startup
```

The existing top-level `canto approve` and `canto reject` commands remain the
only approval decision path. There are no separate memory approval commands.

## Context Profiles

| Profile | Items | Estimated tokens |
| --- | ---: | ---: |
| `startup` | 12 | 2,500 |
| `resolve-reference` | 5 | 750 |
| `review` | 20 | 4,000 |
| `planning` | 24 | 5,000 |

Retrieval is local, lexical, deterministic, and performs no model or network
calls.

## Projects

```bash
canto memory project create "Website migration"
canto memory project link-repository PROJECT_ID --repository .
canto memory project show PROJECT_ID
```

Projects use Canto-generated identity and explicit `repo_id` membership. Names
and filesystem paths are not identity keys.

## Retention And Audit

```bash
canto memory retain
canto memory audit
canto memory export
```

Retention is enforced by `MemoryService.run_retention()`, currently exposed as
the explicit local maintenance command `canto memory retain`. The local
single-user release does not run a daemon or background scheduler. Repository
bootstrap, demos, and future maintenance flows can call the same service method
at safe points. Later server deployments may schedule the same operation, but
the retention rules remain in the service.

Observations expire after 30 days, or 7 days when explicitly classified as low
value. Generated summaries and pending proposals expire after 90 days.
Governed outcomes and rejected/superseded audit records are retained until the
Developer deletes them. Rejected items are hidden from normal lists.

## Bounded Orchestrator Approval

Bounded Orchestrator approval is the default for low-risk memory. The Developer
defines the boundary; the Orchestrator may approve only within that boundary and
the existing Approval object records the decision as `decided_by=orchestrator:<id>`.

Allowed candidates are repository/project-scoped governed outcomes, source
pointers, and non-conflicting aliases. Decisions, preferences, durable
constraints, global terminology, conflicts, supersession, policy changes, and
broad project-scope changes still require Developer approval.

## Security

Memory content, source metadata, and event payloads are scanned before
persistence. Likely credentials and private keys are rejected without storing
the unsafe value. Credentials belong in Vault.

Read-only commands use read-only StateStore access and do not migrate state or
initialize WAL files merely to inspect memory.

## Deferred

The local release does not add a daemon, MCP adapter, vector search, cloud sync,
multi-user authority, broad global preferences, or orchestration HTTP contract
changes.
