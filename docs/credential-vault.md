# Local Credential Vault

Canto stores single-user credentials in an encrypted local vault under
`~/.canto/vault`. AES-GCM records, the master key, and their parent directories
use owner-only filesystem permissions. This protects secrets at rest while the
machine and user account remain trusted.

```bash
canto credential set api_token --scope wordpress
canto credential rotate api_token --scope wordpress
canto credential list
canto credential delete api_token --scope wordpress
```

Provider inputs refer to a record without containing its value:

```yaml
api_token_ref: vault:wordpress/api_token
```

The existing `env:VARIABLE_NAME` form remains supported. Jobs and plans persist
the reference only. Canto resolves references immediately before provider
launch and sends the provider request through an anonymous in-memory file, not
a job artifact. Credential values are never returned by vault CLI commands.

Rotation replaces the encrypted value and increments the record generation
without changing its reference. Known secret values and references are
redacted from provider results, errors, stdout, stderr, and produced artifacts
before job state or artifact metadata is persisted.

The local master key is not a defense against an attacker who controls the same
operating-system account. Multi-user key custody is deferred beyond MVP v1.
