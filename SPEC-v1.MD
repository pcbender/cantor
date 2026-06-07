Canto v1 Specification

A dirt-simple local skill orchestration system for Echo

Working name: Canto
Reason: Cantor is you, the human authority. Canto is the local “song/phrase” Echo can call into: small, bounded, repeatable work.

1. Purpose

Canto v1 is a local WSL2 service that lets a cloud orchestrator, called Echo, run bounded local jobs through declared skills, providers, and tools.

The system should support:

Echo → Canto → Skill → Provider → Tool → Artifact → Echo review → Cantor approval if needed

Canto is not a general autonomous agent. It is a controlled local execution broker.

2. Core goals

Canto v1 should:

Maintain a registry of available skills, providers, and tools.
Let Echo request a job using a known skill/provider.
Store job state in Redis.
Run local tools/scripts in WSL2.
Produce durable artifacts on disk.
Return structured job results to Echo.
Detect missing dependencies.
Support simple approval gates.
Allow missing skills/providers/tools to be scaffolded, but not auto-registered without approval.
3. Non-goals for v1

Do not build these yet:

No web dashboard.
No complex multi-agent swarm.
No automatic production deployments.
No credential vault beyond local env/config.
No long-running distributed queue system.
No multi-user auth system.
No full plugin marketplace.
No automatic remote tunnel.
No autonomous self-modification without approval.

Keep v1 boring and useful.

4. Runtime assumptions

Environment:

OS: WSL2 Ubuntu
State: Redis
Language: Python 3.11+
API: FastAPI
CLI: Typer or argparse
Artifacts: local filesystem
Models: optional Ollama adapter
Coding agent: optional Codex CLI adapter

Suggested repo layout:

canto/
  canto/
    api/
      server.py
      routes.py
    core/
      registry.py
      jobs.py
      runner.py
      policy.py
      dependencies.py
      artifacts.py
      approvals.py
    models/
      schemas.py
    cli.py
  skills/
    source_inventory/
      skill.yaml
      providers/
        public_html_crawler/
          provider.yaml
          run.py
  tools/
    http_fetch/
      tool.yaml
      run.py
  work/
    jobs/
  tests/
  pyproject.toml
  README.md
5. Vocabulary
Cantor

The human authority. In this case, Michael.

Cantor approves risky actions, schema changes, registration of new capabilities, production actions, credential access, and destructive operations.

Echo

The cloud frontier orchestrator.

Echo plans jobs, selects skills/providers, reviews artifacts, asks Cantor questions, and decides next steps.

Canto

The local broker running inside WSL2.

Canto stores job state, validates requests, checks policy, runs providers/tools, and returns artifacts.

Skill

A reusable capability.

Examples:

source_inventory
extract_content
map_schema
build_import
validate_import
scaffold_tool
check_dependencies

A skill defines the common contract.

Provider

A specific implementation of a skill.

Examples:

source_inventory.public_html_crawler
source_inventory.wordpress_rest_api
source_inventory.wordpress_database
extract_content.readability_html
extract_content.ollama_assisted
Tool

The concrete executable mechanism.

Examples:

python script
bash script
wp-cli
mysql
curl
playwright
ollama
codex CLI
Artifact

A durable output file.

Examples:

inventory.json
report.md
git_diff.patch
dry_run_report.md
normalized_content.json
6. Redis state model

Use Redis as the source of truth for job state.

Key patterns
canto:job:{job_id}
canto:job:{job_id}:events
canto:job:{job_id}:artifacts
canto:approval:{approval_id}
canto:registry:snapshot
Job object

Stored as JSON.

{
  "job_id": "job_20260607_abc123",
  "status": "queued",
  "created_at": "2026-06-07T12:00:00Z",
  "updated_at": "2026-06-07T12:00:00Z",
  "requested_by": "echo",
  "skill": "source_inventory",
  "provider": "public_html_crawler",
  "goal": "Inventory Maricopa Records website for CMS migration",
  "inputs": {
    "source_url": "https://maricoparecords.com",
    "max_depth": 3
  },
  "policy": {
    "mode": "dry_run",
    "allow_network": true,
    "allow_filesystem_write": true,
    "allow_destructive": false
  },
  "artifact_dir": "./work/jobs/job_20260607_abc123",
  "result": null,
  "error": null,
  "requires_approval": false,
  "approval_id": null
}
Job statuses
queued
checking_dependencies
waiting_for_approval
running
completed
failed
cancelled
rejected
Event log

Append-only list.

Example event:

{
  "timestamp": "2026-06-07T12:01:00Z",
  "type": "dependency_check_completed",
  "message": "All dependencies satisfied.",
  "data": {}
}
7. API endpoints
Health
GET /health

Response:

{
  "status": "ok",
  "redis": "ok",
  "version": "0.1.0"
}
List registry
GET /registry

Returns available skills, providers, and tools.

Response:

{
  "skills": [
    {
      "name": "source_inventory",
      "description": "Create a structured inventory of content from an existing website or CMS.",
      "providers": [
        "public_html_crawler"
      ]
    }
  ]
}
Get skill
GET /skills/{skill_name}

Response includes skill manifest and providers.

Get provider
GET /skills/{skill_name}/providers/{provider_name}

Response includes provider manifest, tool dependencies, risk level, inputs, outputs, and approval requirements.

Create job
POST /jobs

Request:

{
  "skill": "source_inventory",
  "provider": "public_html_crawler",
  "goal": "Inventory Maricopa Records website for CMS migration",
  "inputs": {
    "source_url": "https://maricoparecords.com",
    "max_depth": 3,
    "include_media": true
  },
  "policy": {
    "mode": "dry_run",
    "allow_network": true,
    "allow_filesystem_write": true,
    "allow_destructive": false
  }
}

Response:

{
  "job_id": "job_20260607_abc123",
  "status": "queued"
}
Get job
GET /jobs/{job_id}

Returns current job object.

Get job events
GET /jobs/{job_id}/events

Returns append-only event history.

Get job artifacts
GET /jobs/{job_id}/artifacts

Returns artifact metadata.

{
  "job_id": "job_20260607_abc123",
  "artifacts": [
    {
      "name": "inventory_json",
      "path": "./work/jobs/job_20260607_abc123/inventory.json",
      "mime_type": "application/json",
      "size_bytes": 12045
    },
    {
      "name": "report_md",
      "path": "./work/jobs/job_20260607_abc123/report.md",
      "mime_type": "text/markdown",
      "size_bytes": 4022
    }
  ]
}
Read artifact
GET /jobs/{job_id}/artifacts/{artifact_name}

Returns artifact contents if text/JSON/Markdown.

For binary artifacts, return metadata only in v1.

Approve job
POST /approvals/{approval_id}/approve

Request:

{
  "approved_by": "cantor",
  "note": "Approved read-only WordPress database inventory."
}
Reject job
POST /approvals/{approval_id}/reject

Request:

{
  "rejected_by": "cantor",
  "reason": "Do not access production database yet."
}
8. CLI

Canto should also have a CLI so it can be used manually.

Examples:

canto health
canto registry
canto skill show source_inventory
canto provider show source_inventory public_html_crawler

Run job:

canto run source_inventory \
  --provider public_html_crawler \
  --input source_url=https://maricoparecords.com \
  --input max_depth=3

Check job:

canto job show job_20260607_abc123
canto job events job_20260607_abc123
canto job artifacts job_20260607_abc123

Approve:

canto approve approval_abc123
canto reject approval_abc123 --reason "Not yet"
9. Manifest format
Skill manifest

Example:

name: source_inventory
version: 0.1.0
description: Create a structured inventory of content from an existing website or CMS.
domain: migration

inputs:
  source_url:
    type: string
    required: false
  source_path:
    type: string
    required: false
  options:
    type: object
    required: false

outputs:
  inventory_json:
    type: file
    format: json
  report_md:
    type: file
    format: markdown

providers:
  - public_html_crawler

risk_level: 1
Provider manifest

Example:

name: public_html_crawler
skill: source_inventory
version: 0.1.0

description: Crawl a public website and produce a structured inventory of pages, links, titles, descriptions, and media references.

runner:
  type: python
  entrypoint: run.py

inputs:
  source_url:
    type: string
    required: true
  max_depth:
    type: integer
    default: 3
  include_media:
    type: boolean
    default: true

outputs:
  inventory_json:
    path: inventory.json
    type: file
    format: json
  report_md:
    path: report.md
    type: file
    format: markdown

tools:
  - http_fetch
  - html_parser

dependencies:
  system:
    - python3
  python:
    - requests
    - beautifulsoup4
    - pydantic

permissions:
  network_read: true
  network_write: false
  filesystem_write:
    - ./work/jobs/
  destructive: false

risk_level: 1

approval_required:
  - crawling_non_owned_domain
  - max_depth_greater_than_5
Tool manifest

Example:

name: http_fetch
version: 0.1.0
type: tool

description: Fetches public HTTP/HTTPS pages.

runtime:
  language: python
  entrypoint: run.py

dependencies:
  system:
    - python3
  python:
    - requests

permissions:
  network_read: true
  network_write: false
  filesystem_write:
    - ./work/jobs/

risk_level: 1
10. Dependency handling

Canto must inspect manifests before running a job.

Dependency result:

{
  "status": "ready",
  "missing": {
    "system": [],
    "python": []
  },
  "install_plan": []
}

If missing Python dependencies:

{
  "status": "not_ready",
  "missing": {
    "python": ["beautifulsoup4"]
  },
  "install_plan": [
    {
      "type": "python",
      "command": "pip install beautifulsoup4",
      "approval_required": false
    }
  ]
}

Policy:

Python dependencies inside project venv: allowed with low risk.
System packages via apt: require approval.
Global npm installs: require approval.
Docker pulls: require approval.
Sudo: always approval.
Database write: always approval.
Production write/deploy: always approval.

For v1, Canto may report missing dependencies without auto-installing them.

Auto-install can be v1.1.

11. Approval rules

Approval required for:

production database access
database writes
filesystem writes outside work/
deleting files
modifying registered skills/providers/tools
registering new capability
installing system packages
running sudo
network access to non-approved domains
live CMS import
deployment

Approval object:

{
  "approval_id": "approval_abc123",
  "job_id": "job_20260607_abc123",
  "reason": "Provider requires production database read access.",
  "risk_level": 3,
  "status": "pending",
  "created_at": "2026-06-07T12:00:00Z"
}
12. Runner behavior

When a job is created:

1. Validate skill exists.
2. Validate provider exists for skill.
3. Validate inputs against manifest.
4. Create artifact directory.
5. Store job in Redis as queued.
6. Check dependencies.
7. Check policy/approval requirements.
8. If approval needed, set waiting_for_approval.
9. If approved or no approval needed, run provider.
10. Capture stdout/stderr.
11. Collect declared artifacts.
12. Update Redis result.
13. Emit events throughout.

Provider runner contract:

Each provider receives a JSON file as input:

{
  "job_id": "job_20260607_abc123",
  "skill": "source_inventory",
  "provider": "public_html_crawler",
  "inputs": {
    "source_url": "https://maricoparecords.com",
    "max_depth": 3
  },
  "artifact_dir": "./work/jobs/job_20260607_abc123"
}

Provider writes artifacts to artifact_dir.

Provider returns JSON on stdout:

{
  "status": "completed",
  "summary": "Crawled 24 pages and found 42 media references.",
  "artifacts": {
    "inventory_json": "inventory.json",
    "report_md": "report.md"
  },
  "warnings": [],
  "needs_human": false
}
13. v1 built-in skills
Skill: source_inventory

Purpose:

Create a structured inventory of content from an existing website or CMS.

Initial provider:

public_html_crawler

Output:

inventory.json
report.md
Skill: check_dependencies

Purpose:

Check whether a skill/provider/tool has all required dependencies.

Provider:

manifest_dependency_checker

Output:

dependency_report.json
dependency_report.md
Skill: scaffold_tool

Purpose:

Create a new tool scaffold with manifest, runner, README, and test placeholder.

Approval:

Required before registering.

Output:

tool.yaml
run.py
README.md
test placeholder
Skill: scaffold_provider

Purpose:

Create a new provider scaffold under an existing skill.

Approval:

Required before registering.
Skill: migration_report

Purpose:

Summarize inventory artifacts into a human-readable migration assessment.

Provider:

local_markdown_report
14. v1 first useful workflow

The first real workflow should be:

Assess a public website for CMS migration.

Example Echo request:

{
  "skill": "source_inventory",
  "provider": "public_html_crawler",
  "goal": "Inventory Maricopa Records website for CMS migration",
  "inputs": {
    "source_url": "https://maricoparecords.com",
    "max_depth": 3,
    "include_media": true
  },
  "policy": {
    "mode": "dry_run",
    "allow_network": true,
    "allow_filesystem_write": true,
    "allow_destructive": false
  }
}

Expected result:

{
  "status": "completed",
  "summary": "Found pages, links, images, and probable content types.",
  "artifacts": {
    "inventory_json": "inventory.json",
    "report_md": "report.md"
  },
  "recommended_next_steps": [
    "Run extract_content once provider exists.",
    "Ask Cantor target CMS.",
    "Create CMS schema mapping provider."
  ]
}
15. Missing capability behavior

If Echo requests a missing skill/provider/tool, Canto should not fail vaguely.

Example request:

{
  "skill": "source_inventory",
  "provider": "wordpress_database"
}

If missing, response:

{
  "status": "missing_provider",
  "skill": "source_inventory",
  "provider": "wordpress_database",
  "message": "Provider wordpress_database is not installed for skill source_inventory.",
  "suggested_action": {
    "skill": "scaffold_provider",
    "inputs": {
      "skill": "source_inventory",
      "provider": "wordpress_database"
    },
    "requires_approval": true
  }
}

Echo can then propose:

“Canto does not have a WordPress database provider. I can create a scaffold for one. It would be read-only and would declare MySQL/Python dependencies. Approve?”

16. Security posture

Canto v1 should default to conservative behavior.

Rules:

No shell command should run unless it belongs to a registered provider/tool.
No provider may write outside its artifact directory unless explicitly allowed.
No production write action in v1.
No secrets in Redis events.
No secrets in artifacts.
No automatic sudo.
No automatic registration of generated capabilities.

Secrets should be passed by reference when possible:

{
  "db_credentials_ref": "env:MR_WORDPRESS_DB"
}

Instead of raw passwords.

For v1, support .env loaded locally.

17. Local model support

Model use should be optional in v1.

Add a generic model adapter later:

ollama_generate

Tool manifest:

name: ollama_generate
version: 0.1.0
description: Calls a local Ollama model with a prompt and returns text or JSON.

dependencies:
  system:
    - ollama

inputs:
  model:
    type: string
    required: true
  prompt:
    type: string
    required: true
  format:
    type: string
    default: text

permissions:
  network_read: false
  filesystem_write:
    - ./work/jobs/

risk_level: 1

This would allow future providers like:

extract_content.ollama_assisted
schema_map.local_model
report.local_model_summary

But do not make v1 dependent on LLM behavior.

18. Example provider: public HTML crawler

Minimum behavior:

- Fetch source URL.
- Parse links.
- Stay on same domain.
- Respect max_depth.
- Collect page URL, title, meta description, H1s, internal links, images.
- Write inventory.json.
- Write report.md.

Example inventory.json:

{
  "source_url": "https://maricoparecords.com",
  "crawled_at": "2026-06-07T12:00:00Z",
  "pages": [
    {
      "url": "https://maricoparecords.com/",
      "status_code": 200,
      "title": "Maricopa Records",
      "meta_description": "...",
      "h1": ["Maricopa Records"],
      "links": [],
      "images": [],
      "probable_type": "home"
    }
  ],
  "media": [],
  "warnings": []
}

Example report.md:

# Source Inventory Report

Source: https://maricoparecords.com

## Summary

- Pages crawled: 24
- Images found: 42
- Broken links: 2
- External links: 13

## Probable content groups

- Home
- Artists
- Releases
- Licensing
- Contact

## Warnings

- Some pages may require JavaScript rendering.
19. Build order

OpenAI should build in this order:

1. Repo skeleton.
2. Redis connection and job model.
3. Manifest loader.
4. Registry endpoint.
5. Job creation endpoint.
6. Dependency checker.
7. Provider runner contract.
8. Artifact collection.
9. CLI commands.
10. Built-in source_inventory.public_html_crawler provider.
11. Approval state machine.
12. Missing provider response.
13. Scaffold provider/tool skills.
14. Tests.
20. Acceptance tests
Test 1: Registry loads

Given a valid skill/provider manifest, GET /registry returns it.

Test 2: Job runs

Given source_inventory.public_html_crawler, Canto creates a job, runs it, stores status in Redis, and writes artifacts.

Test 3: Missing provider handled

Requesting source_inventory.wordpress_database returns missing_provider with scaffold suggestion.

Test 4: Dependency check

If provider declares a missing dependency, job enters failed or waiting_for_dependency with a dependency report.

Test 5: Approval gate

If a provider requires approval, job enters waiting_for_approval and does not run until approved.

Test 6: Artifact read

Completed job artifacts can be listed and read.

21. Naming decision

I recommend:

Cantor = Michael
Echo = cloud orchestrator
Canto = local skill broker