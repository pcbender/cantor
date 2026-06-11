# Provider Runtimes

Provider manifests select one runner type while retaining the same Canto
request/result protocol:

- `python`: local Python entrypoint.
- `node`: local Node entrypoint; Node must already be installed.
- `binary`: executable local entrypoint.
- `container`: an explicitly declared local image and command.

All adapters run through `JobService` and the shared runner, including timeout,
output-size, redaction, artifact, policy, and event handling. Canto does not
install runtimes or pull container images. Container execution fails clearly
when Docker/Podman or the declared local image is unavailable.
