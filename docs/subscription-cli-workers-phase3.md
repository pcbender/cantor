# CP-1713 - Phase 3 Selection And Fallback Design

Status: design packet for approved Phase 3 implementation.

## Goal

Phase 3 makes Worker selection more explicit when subscription/local CLI
Workers are unavailable, exhausted, or disallowed. Canto must never silently
collapse work onto the Developer/orchestrator and must never silently spend API
credits after a CLI Worker fails.

## Scope

- Introduce a clear Worker failure taxonomy for CLI selection.
- Apply priority-driven fallback rules before using HTTP/API Workers.
- Preserve the existing single-user, local-only Worker pool.
- Improve selection evidence so Developer review can see why a Worker was
  selected, skipped, exhausted, or blocked.
- Keep Claude/Gemini adapters, performance feedback, and full capability floors
  deferred.

## Priority Fallback Rules

When CLI transport is allowed and CLI candidates fail before changing the
Workspace:

- `economy`: stop; do not use HTTP/API fallback.
- `balanced`: require explicit approval before HTTP/API fallback.
- `quality`: require explicit approval before HTTP/API fallback.
- `urgent`: allow policy-authorized HTTP/API fallback when `http` transport,
  cloud/API authority, and budget policy also allow it.

If a failed Worker changed the Workspace, fallback stops regardless of priority.
Canto must require review/revision of the changed Workspace.

## Transport Authority

HTTP/API fallback requires all of:

- `allowed_transports` is empty or contains `http`;
- cloud use is explicitly authorized for non-local HTTP endpoints;
- API fallback is explicitly authorized for the relevant priority;
- budget policy permits the estimated spend when pricing is known.

`allowed_transports = ["cli"]` remains a hard API-spend block.

## Orchestrator Provider Context

Phase 3 records optional orchestrator provider context as a policy/scoring input.
When present, it can penalize selecting a Worker from the same subscription pool.
This phase records and surfaces the context, but does not yet implement broad
performance-learning or provider-specific quota accounting.

## Non-Goals

- No Claude/Gemini CLI adapters.
- No autonomous approval.
- No new persisted Approval model.
- No hidden API fallback.
- No remote registry, hosted worker service, or multi-user identity.
- No Worker writes to durable memory outside existing proposal/approval paths.

## Work Packets

1. CP-1714 - Worker Exhaustion/Error Taxonomy
2. CP-1715 - Priority Fallback Policy
3. CP-1716 - Approval-Gated API Spill Placeholder
4. CP-1717 - Orchestrator Provider Context
5. CP-1718 - Provider Diversity Scoring Hook
6. CP-1719 - Selection Explanation Updates
7. CP-1720 - Phase 3 Dogfood

## Acceptance

- Economy CLI-only and CLI-preferred tasks do not spend API credits after CLI
  exhaustion.
- Balanced/quality tasks report that approval is required before API spill.
- Urgent tasks may fall back only when HTTP/API transport and cloud authority
  are explicitly permitted.
- Selection output records CLI candidate skips and fallback decisions.
- Existing `launch-ai` default behavior remains backward compatible.
- Full test suite passes without installed external CLIs or network access.
