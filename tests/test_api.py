from fastapi.testclient import TestClient

from canto.api.server import create_app
from canto.core.capability_package import pack_capability
from canto.core.local_registry import Registry as CapabilityRegistry


def isolated_app(runtime):
    settings, _, store, _ = runtime
    registry = CapabilityRegistry.local(settings.root_dir / "registry-home")
    return create_app(settings, store, registry)


def orchestration_app(runtime):
    settings, _, store, _ = runtime
    source = settings.root_dir / "api_demo"
    provider = source / "skills" / "api_demo" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: api_demo
version: 1.0.0
description: Run an HTTP orchestration demo.
skills:
  - api_demo
providers:
  - api_demo.local
intents:
  - orchestration_demo
outputs:
  - result.json
execution:
  providers:
    - skill: api_demo
      provider: local
      produces:
        result_file: result.json
risk:
  level: low
""",
        encoding="utf-8",
    )
    (source / "skills" / "api_demo" / "skill.yaml").write_text(
        "name: api_demo\nproviders:\n  - local\n", encoding="utf-8"
    )
    (provider / "provider.yaml").write_text(
        """\
name: local
skill: api_demo
runner:
  type: python
  entrypoint: run.py
inputs: {}
outputs:
  result_file:
    path: result.json
    type: file
    format: json
permissions:
  network_read: false
  network_write: false
  filesystem_write: []
  destructive: false
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider / "run.py").write_text(
        """\
import json
import sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
(Path(request["artifact_dir"]) / "result.json").write_text(
    json.dumps({"ok": True}), encoding="utf-8"
)
print(json.dumps({"status": "completed", "summary": "API demo complete."}))
""",
        encoding="utf-8",
    )
    registry = CapabilityRegistry.local(settings.root_dir / "api-home")
    registry.install_package(pack_capability(source, settings.root_dir / "api-dist"))
    return create_app(settings, store, registry)


def test_api_approval_and_artifact_read(runtime):
    client = TestClient(isolated_app(runtime))
    created = client.post(
        "/jobs",
        json={
            "skill": "scaffold_tool",
            "provider": "local_scaffolder",
            "inputs": {"name": "sample_tool"},
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    waiting = client.get(f"/jobs/{job_id}").json()
    assert waiting["status"] == "waiting_for_approval"

    approved = client.post(
        f"/approvals/{waiting['approval_id']}/approve",
        json={"approved_by": "cantor", "note": "Review scaffold"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"

    listed = client.get(f"/jobs/{job_id}/artifacts").json()["artifacts"]
    assert len(listed) == 4
    manifest = client.get(f"/jobs/{job_id}/artifacts/scaffold_manifest").json()
    assert "name: sample_tool" in manifest["content"]


def test_api_missing_provider_is_structured(runtime):
    client = TestClient(isolated_app(runtime))
    response = client.post(
        "/jobs",
        json={
            "skill": "source_inventory",
            "provider": "wordpress_database",
            "inputs": {},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "missing_provider"


def test_api_missing_skill_is_structured(runtime):
    client = TestClient(isolated_app(runtime))
    response = client.post(
        "/jobs",
        json={
            "skill": "extract_content",
            "provider": "readability_html",
            "inputs": {},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "missing_skill"
    assert body["suggested_action"]["skill"] == "scaffold_skill"


def test_orchestration_http_resources(runtime):
    client = TestClient(orchestration_app(runtime))

    discovered = client.post(
        "/discover", json={"goal": "run orchestration demo", "limit": 5}
    )
    assert discovered.status_code == 200
    assert discovered.json()["contract_version"] == "1.0"
    assert discovered.json()["matches"][0]["name"] == "api_demo"

    created = client.post("/plans", json={"goal": "run orchestration demo"})
    assert created.status_code == 200
    plan = created.json()
    plan_id = plan["plan_id"]
    assert plan["status"] == "draft"
    assert plan["candidate"]["steps"][0]["skill"] == "api_demo"

    fetched = client.get(f"/plans/{plan_id}")
    explained = client.get(f"/plans/{plan_id}/explain")
    assert fetched.status_code == 200
    assert fetched.json()["plan_id"] == plan_id
    assert explained.status_code == 200
    assert explained.json()["steps"][0]["provider"] == "local"

    approved = client.post(
        f"/plans/{plan_id}/approve",
        json={"approved_by": "cantor", "note": "Reviewed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    events = client.get(f"/plans/{plan_id}/events")
    assert events.status_code == 200
    assert [event["type"] for event in events.json()["events"]] == [
        "plan_created",
        "plan_approved",
    ]


def test_plan_execute_returns_202_and_is_pollable(runtime):
    client = TestClient(orchestration_app(runtime))
    plan_id = client.post(
        "/plans", json={"goal": "run orchestration demo"}
    ).json()["plan_id"]
    client.post(
        f"/plans/{plan_id}/approve",
        json={"approved_by": "cantor", "note": "Reviewed"},
    )

    accepted = client.post(f"/plans/{plan_id}/execute")

    assert accepted.status_code == 202
    assert accepted.json()["status"] == "running"
    observed = client.get(f"/plans/{plan_id}")
    assert observed.status_code == 200
    assert observed.json()["status"] == "completed"
    assert observed.json()["step_jobs"][0]["status"] == "completed"
    assert "result.json" in observed.json()["artifacts"]
    assert client.get(f"/plans/{plan_id}/events").json()["events"][-1][
        "type"
    ] == "plan_completed"


def test_frozen_orchestration_http_contract_loop(runtime):
    client = TestClient(orchestration_app(runtime))

    discovery = client.post(
        "/discover", json={"goal": "run orchestration demo"}
    )
    assert discovery.status_code == 200
    assert discovery.json()["contract_version"] == "1.0"
    assert discovery.json()["matches"][0]["name"] == "api_demo"

    planning = client.post(
        "/plans",
        json={"goal": "run orchestration demo", "inputs": {}},
    )
    assert planning.status_code == 200
    plan_id = planning.json()["plan_id"]
    assert planning.json()["contract_version"] == "1.0"
    assert planning.json()["status"] == "draft"

    approval = client.post(
        f"/plans/{plan_id}/approve",
        json={"approved_by": "cantor", "note": "Contract review"},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"

    execution = client.post(f"/plans/{plan_id}/execute")
    assert execution.status_code == 202
    assert execution.json() == {
        "contract_version": "1.0",
        "plan_id": plan_id,
        "status": "running",
        "step_jobs": [],
    }

    observed = client.get(f"/plans/{plan_id}")
    assert observed.status_code == 200
    assert observed.json()["status"] == "completed"
    assert observed.json()["step_jobs"][0]["status"] == "completed"
    assert observed.json()["artifacts"]["result.json"].endswith("/result.json")

    explanation = client.get(f"/plans/{plan_id}/explain")
    assert explanation.status_code == 200
    assert explanation.json()["contract_version"] == "1.0"
    assert explanation.json()["status"] == "completed"
    assert explanation.json()["steps"][0]["skill"] == "api_demo"

    events = client.get(f"/plans/{plan_id}/events")
    assert events.status_code == 200
    assert events.json()["contract_version"] == "1.0"
    event_types = {event["type"] for event in events.json()["events"]}
    assert {
        "plan_created",
        "plan_approved",
        "plan_started",
        "job_created",
        "provider_started",
        "job_completed",
        "plan_completed",
    } <= event_types
