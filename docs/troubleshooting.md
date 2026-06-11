# MVP v1 Troubleshooting

## Health is degraded

Run `canto health` and confirm `state` is `ok`. SQLite lives at
`~/.canto/state/canto.db`; check that `~/.canto` is writable by the current
user. Redis is not required. Legacy state migration is documented in
`docs/state-migration.md`.

## A credential cannot be resolved

Use `canto credential list` to confirm the `vault:scope/name` reference exists.
For `env:NAME`, export the variable in the process that starts Canto. Do not put
plaintext values in job inputs. Recreate or rotate corrupt records; never edit
encrypted vault JSON manually.

## A provider is waiting for approval

Inspect the job and events, then use the listed approval ID with `canto approve`
or `canto reject`. Write promotion and recovery each require their own Approval.
Changing a reviewed artifact, provider package, target identity, credential
reference, or input invalidates promotion.

## A live write fails before mutation

Check the validation and change-set artifacts from the dry run. The reference
provider rejects target drift between review and live execution. Run a new dry
run rather than editing artifacts. Direct live write jobs are intentionally
rejected.

## A provider exceeds a runtime limit

Inspect the `runtime_limits_applied` job event. Providers may request lower
limits, but not raise global ceilings. Relevant environment variables are
listed in `.env.example`. Local runtime enforcement requires Linux `prlimit`.

## Network access is denied

The job policy must allow network access and list approved domains. The
provider must declare `runner.egress_enforcement: provider_allowlist`. Canto
fails closed when the active runtime cannot enforce the declared network
permission. Network-write providers are not supported in MVP v1.

## Node, binary, or container execution fails

Node and executable binaries must already exist locally. Binary entrypoints
must have execute permission. Container providers require Docker or Podman and
an image already present on the machine; Canto never pulls images.

## Installation or wheel verification fails

Install the local build/test extras with `pip install -e '.[test]'`, then run
`pip check`. Wheel and upgrade instructions are in
`docs/local-installation.md`. Capability package installation remains explicit
and local; there is no remote registry or automatic dependency installation.
