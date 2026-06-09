# Canto Local Orchestration

Orchestration converts a user goal into a reviewable sequence of installed
local capabilities. Discovery and planning do not execute providers or change
artifacts.

## Terms

### Goal

A goal is the user-provided statement of desired outcome, such as `import my
wordpress site`. It is treated as local matching text, not as an instruction
to generate code, fetch remote packages, or infer credentials.

### Capability match

A capability match is an installed local capability whose manifest metadata
overlaps the goal. Matching uses only declared name, description, intents,
inputs, and outputs. A match includes a deterministic score and the metadata
reasons that contributed to that score.

### Workflow candidate

A workflow candidate is an ordered proposal made from capability matches. Each
step names one capability, explains why it was selected, lists its required
inputs, and lists its produced artifacts. A workflow candidate may report
missing user inputs or artifact dependencies. It does not authorize execution.

### Execution plan

An execution plan is a persisted workflow candidate with a stable plan ID and
status. It records the exact installed capability versions and metadata used
when planning. Only an approved plan may be submitted for execution, and steps
run in their recorded order.

### Approval gate

The approval gate is the explicit transition from a draft plan to an approved
plan. Approval records intent to execute the recorded plan; it does not execute
the plan itself, install dependencies, supply missing values, or bypass normal
provider policy and approval checks.

## Boundaries

Orchestration uses installed local capabilities only. It does not access a
remote registry, generate capabilities with AI, handle live credentials, write
to target systems, or automatically install dependencies. Planning never
executes providers. Execution remains subject to existing provider policy,
artifact, dependency, timeout, and approval controls.
