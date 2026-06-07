# Canto v1

Canto is a deliberately small local execution broker for Echo. It discovers registered skills, providers, and tools from YAML manifests; stores jobs, events, approvals, artifacts, and registry snapshots in Redis; executes registered Python providers with time and output bounds; and keeps artifacts on the local filesystem.

## Requirements

- WSL2 Ubuntu or another Linux environment
- Python 3.11+
- Redis 7 running inside WSL2

## Install and run

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
sudo apt update
sudo apt install redis-server
sudo service redis-server start
.venv/bin/canto serve
```

The API listens on `http://127.0.0.1:8765` by default. Interactive API documentation is at `/docs`.

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/registry
```

Check Redis directly with:

```bash
redis-cli ping
```

Expected response: `PONG`.

## Run a source inventory

```bash
.venv/bin/canto run source_inventory \
  --provider public_html_crawler \
  --allow-network \
  --input source_url=https://example.com \
  --input max_depth=2
```

The crawler stays on the source hostname, uses bounded request and process timeouts, and defaults to at most 100 pages. Outputs are written under `work/jobs/<job_id>/`.

## Approval flow

Providers can declare approval rules. Canto checks dependencies and policy before execution and places gated jobs in `waiting_for_approval`. Approve or reject them with:

```bash
.venv/bin/canto approve approval_YYYYMMDD_abcdef
.venv/bin/canto reject approval_YYYYMMDD_abcdef --reason "Not yet"
```

The built-in `scaffold_skill`, `scaffold_provider`, and `scaffold_tool` capabilities always require approval. Their output remains in the job artifact directory and is never automatically added to the live registry.

## API summary

- `GET /health`
- `GET /registry`
- `GET /skills/{skill}`
- `GET /skills/{skill}/providers/{provider}`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/events`
- `GET /jobs/{job_id}/artifacts`
- `GET /jobs/{job_id}/artifacts/{artifact_name}`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`

Unknown skills and providers return structured `missing_skill` or `missing_provider` responses with approval-gated scaffold suggestions.

## Security boundaries

Canto only launches entrypoints declared by registered provider manifests. It rejects entrypoints outside their provider directory, enforces subprocess timeouts and output limits, validates policy before launch, and only collects declared artifacts whose resolved paths remain inside the job artifact directory. v1 does not provide a kernel-level filesystem or network sandbox, so manifests and provider code remain trusted local configuration.

## Tests

```bash
.venv/bin/pytest
```
