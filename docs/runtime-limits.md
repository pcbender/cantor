# Runtime Limits and Egress

Canto applies global ceilings with optional lower per-provider `limits` values:

```yaml
limits:
  wall_seconds: 30
  cpu_seconds: 10
  memory_bytes: 268435456
  artifact_bytes: 52428800
```

Linux local runtimes use `prlimit` for CPU, address-space, and per-file limits.
Canto uses a separate process group for each provider, kills that group on wall
timeout, bounds captured stdout/stderr, and checks aggregate artifact usage.
Container commands receive memory/CPU constraints when a local runtime exists.
Applied values are recorded in job events.

Network permissions fail closed unless a provider explicitly declares
`runner.egress_enforcement: provider_allowlist` and policy supplies approved
domains. Approved domains are passed as `CANTO_APPROVED_DOMAINS`; the provider
must constrain every request and redirect. Network-write permission is not
supported in this local runtime baseline.

These controls reduce accidental resource and egress mistakes for trusted
installed code. They are not hostile-code isolation; that remains future
multi-user/untrusted-package work.
