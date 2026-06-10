# Approval Unification

## Current Split

Canto currently represents approval in two ways:

- `JobService` creates persisted `Approval` objects when provider policy requires
  review. They are linked to a job, stored through `StateStore`, and managed by
  the canonical `/approvals/{approval_id}/approve` and `/reject` endpoints.
- Orchestration records plan approval as `ExecutionPlan.status == "approved"`
  plus an `approved_at` timestamp. This is a separate gate without an Approval
  object.

This split allows a plan to be approved while a later job independently waits
for provider approval. Plan status therefore does not describe the state of all
step approvals and jobs.

## Target State

`Approval` remains the single persisted approval object. Canto must not create a
second plan-specific approval type.

Step-level approvals are preferred because risk, policy, and runnable identity
belong to a concrete `(skill, provider)` step. An orchestration plan stores or
links the Approval IDs associated with its gated steps. The existing
`/approvals` endpoints remain the canonical decision interface.

Plan status becomes a rollup over its step approvals and jobs:

- `draft`: the plan has not requested approval.
- `waiting_for_approval`: one or more required step approvals are pending.
- `rejected`: at least one required step approval is rejected.
- `approved`: all required step approvals are approved, or no step requires an
  approval gate and approval intent has been recorded.
- `running`, `completed`, or `failed`: derived from step job execution.

Approval does not bypass `JobService` policy evaluation. Execution still uses
the canonical `(skill, provider)` identity and existing job lifecycle.

## Migration Steps

1. Extend persisted plans with step-to-Approval links while retaining existing
   status and timestamp fields for saved-plan compatibility.
2. On plan approval, evaluate each resolved provider with the existing policy
   rules and create Approval objects for gated steps.
3. Derive plan readiness from linked Approval states instead of treating the
   plan timestamp as sufficient authorization.
4. Reuse approved step authorization when `JobService` creates the step job, so
   execution does not create a duplicate approval object.
5. Propagate rejection to plan status and prevent execution.
6. Keep existing job approval routes and payloads stable throughout migration.
7. Remove the legacy independent plan-approval interpretation only after saved
   plans have a compatibility path.

Authentication, remote approval services, and a new approval API are outside
this work.
