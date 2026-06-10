# Authentication Placeholder

Canto does not implement authentication in orchestration contract v1.0. The
default server bind address is `127.0.0.1`, and the current API assumes the
loopback caller is trusted.

## Loopback Default

- The unauthenticated API is intended for loopback-only use.
- Operators must not expose the current server directly on an untrusted
  interface.
- `requested_by` and `approved_by` are audit labels supplied by the caller; they
  are not authenticated identities.

## Reserved Header

For future non-loopback use, Canto reserves:

```http
Authorization: Bearer <token>
```

The header will apply to mutating endpoints, including:

- `POST /plans`
- `POST /plans/{plan_id}/approve`
- `POST /plans/{plan_id}/execute`
- `POST /jobs`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`

Read-only endpoints may also require authorization in a future contract when
they expose sensitive registry, plan, job, or artifact metadata.

## Deferred Work

Contract v1.0 does not define token issuance, storage, rotation, scopes,
identity providers, authentication middleware, or server-derived actor names.
Those features require a later security design. Adding enforcement for
non-loopback deployments must preserve the reserved bearer header and follow
the contract compatibility policy.
