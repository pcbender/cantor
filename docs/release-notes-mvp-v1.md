# Canto MVP v1 Release Notes

MVP v1 establishes Canto as a governed single-user local runtime for trusted
capabilities. It preserves orchestration contract v1.0 and the canonical
`(skill, provider)` execution identity.

## Highlights

- SQLite system of record for jobs, events, approvals, artifacts, registry
  snapshots, and plans; Redis is optional legacy state.
- Repeatable Redis/filesystem-plan migration into SQLite.
- AES-GCM local credential vault with scoped references, rotation, owner-only
  permissions, launch-time resolution, and output/artifact redaction.
- Validated write-provider contract and reversible managed-JSON reference
  provider.
- Immutable dry-run review, explicit promotion Approval, stale/tamper checks,
  live verification, atomic idempotency, and approval-gated rollback.
- Python, Node, local binary, and local-container runtime adapters behind the
  same `JobService` path.
- CPU, memory, wall-time, output, and artifact limits plus fail-closed egress
  declarations.
- Wheel-distributed built-in skills/tools, local upgrade documentation,
  deterministic quickstarts, and a reviewed seed capability catalogue.

## Compatibility

All HTTP changes are additive. Orchestration `contract_version` remains `1.0`.
Existing capability manifests remain valid, existing Python providers retain
their execution path, and retained Redis support exists for migration and
state-store compatibility tests.

## Security Boundary

MVP v1 is for trusted local capability code under one operating-system user.
It is loopback-only by default and does not provide hostile-code isolation,
multi-user authorization, remote registries, signing, automatic dependency
installation, autonomous approval, or unattended production writes.

## Verification

```bash
.venv/bin/pip check
.venv/bin/pytest tests import_capability/tests
./scripts/quickstart-mvp-v1.sh
./scripts/demo-mvp-v1.sh
```

The stability demo uses isolated local state and proves package install,
discovery, planning, approval, vault-backed execution, dry run, promotion,
verification, recovery approval, and rollback without Redis or network access.

Final result: `202 passed`, with one non-blocking Starlette `TestClient`
deprecation warning.
