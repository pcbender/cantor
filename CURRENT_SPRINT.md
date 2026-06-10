# Current Sprint — v3.0 External Orchestrator Integration

## Sprint Goal

Prove that an external process can drive Canto entirely through the frozen v1.0
HTTP orchestration contract — `discover → plan → approve → execute → observe` —
with no in-process access and no caller-supplied executor. Canto owns execution;
the external orchestrator only calls the contract.

## Architecture Rule

This sprint must not change the frozen orchestration contract. The locked model
(Skill, Provider, Tool, Artifact, Job, Approval, Registry, Policy, Capability
package, Execution plan, Orchestration contract) stays intact. If integration
work surfaces a genuine contract gap, it is raised as an explicit
`contract_version` change — not patched silently. New work lives in client code,
examples, and docs.

## Tasks

| ID | Status | Task |
| --- | --- | --- |
| CP-1001 | READY | External orchestrator integration design: confirm the frozen contract against a real out-of-process client; record any wire-shape gaps as candidate `contract_version` 1.1 items. |
| CP-1002 | BLOCKED | Python client library over the HTTP contract (discover/plan/approve/execute/poll/explain/artifacts). Depends on CP-1001. |
| CP-1003 | BLOCKED | Contract smoke-test script exercising the full loop against a running server. Depends on CP-1002. |
| CP-1004 | BLOCKED | External orchestrator example prompts and request/response samples. Depends on CP-1002. |
| CP-1005 | BLOCKED | Human-in-the-loop approval demo (pause at `waiting_for_approval`, approve, resume). Depends on CP-1002. |
| CP-1006 | BLOCKED | Error-scenario examples: missing inputs, missing capability, rejected approval, failed step, missing artifact. Depends on CP-1002. |
| CP-1007 | BLOCKED | End-to-end external demo: `import my WordPress site and generate a migration report`. Depends on CP-1003–CP-1006. |
| CP-1008 | BLOCKED | v3.0 documentation pass and external orchestrator README. Depends on CP-1007. |

## Open Decision Carried Into This Sprint

Authentication and non-loopback enforcement are deferred contract items, but v3.0
is the first phase with real external callers. CP-1001 must decide whether a
minimal bearer-token + server-populated identity scheme is in scope now or
explicitly punted to a scheduled v3.x — adding auth to a frozen contract later is
itself a contract change.

## Definition of Done

- An external process completes discover → plan → approve → execute → poll →
  explain → inspect artifacts using only the HTTP contract.
- Existing tests still pass; new tests cover the client and error scenarios.
- No change to the frozen contract without an explicit `contract_version` bump.
- No remote registry, AI generation, autonomous approval, credential storage, or
  target writes introduced.
