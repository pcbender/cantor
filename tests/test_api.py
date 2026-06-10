from fastapi.testclient import TestClient

from canto.api.server import create_app
from canto.core.local_registry import Registry as CapabilityRegistry


def isolated_app(runtime):
    settings, _, store, _ = runtime
    registry = CapabilityRegistry.local(settings.root_dir / "registry-home")
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
