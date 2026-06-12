# Canto Shared Agent Instructions

- Canto is globally installed; do not install Canto into this repository.
- Durable state, credentials, artifacts, and workspaces live under `~/.canto`.
- Repository-local Canto intent and policy live under `.canto/`.
- Delegated executor work happens only in Canto-managed Git worktrees.
- Canonical repository changes require Canto review, acceptance, and promotion.
- Do not commit or push unless the human explicitly instructs you to do so.
- Do not access secrets, credential vault files, or paths denied by task policy.
- Sparse checkout limits context but is not a security boundary.
