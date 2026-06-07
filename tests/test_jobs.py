from __future__ import annotations

from pathlib import Path

from canto.models.schemas import JobRequest, Policy


def test_dependency_check_waits_when_dependency_missing(runtime):
    _, registry, store, service = runtime
    provider = registry.provider_internal("source_inventory", "public_html_crawler")
    provider["dependencies"]["python"].append("definitely-not-a-real-canto-package")
    job = service.create_job(
        JobRequest(
            skill="source_inventory",
            provider="public_html_crawler",
            inputs={"source_url": "https://example.com"},
            policy=Policy(allow_network=True),
        )
    )
    result = service.process_job(job.job_id)
    assert result.status == "waiting_for_dependency"
    assert "definitely-not-a-real-canto-package" in result.error["missing"]["python"]
    assert any(event["type"] == "dependency_check_completed" for event in store.get_events(job.job_id))


def test_approval_gate_and_scaffold_artifacts(runtime):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_provider",
            provider="local_scaffolder",
            inputs={"skill": "source_inventory", "provider": "wordpress_database"},
        )
    )
    waiting = service.process_job(job.job_id)
    assert waiting.status == "waiting_for_approval"
    assert store.get_artifacts(job.job_id) == []

    completed = service.approve(waiting.approval_id, "cantor", "Create for review")
    assert completed.status == "completed"
    artifacts = store.get_artifacts(job.job_id)
    assert {item["name"] for item in artifacts} == {
        "scaffold_manifest",
        "scaffold_runner",
        "scaffold_readme",
        "scaffold_test",
    }
    assert Path(completed.artifact_dir, "provider.yaml").is_file()


def test_scaffold_skill_requires_approval_and_writes_artifacts(runtime):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_skill",
            provider="local_scaffolder",
            inputs={"skill": "extract_content", "description": "Extract normalized content."},
        )
    )
    waiting = service.process_job(job.job_id)
    assert waiting.status == "waiting_for_approval"
    completed = service.approve(waiting.approval_id, "cantor", "Review scaffold")
    assert completed.status == "completed"
    artifacts = store.get_artifacts(job.job_id)
    assert {item["name"] for item in artifacts} == {
        "scaffold_manifest",
        "scaffold_readme",
        "scaffold_test",
    }
    assert Path(completed.artifact_dir, "skill.yaml").is_file()


def test_approval_rejection_does_not_run(runtime):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_tool",
            provider="local_scaffolder",
            inputs={"name": "database_writer"},
        )
    )
    waiting = service.process_job(job.job_id)
    rejected = service.reject(waiting.approval_id, "cantor", "Not needed")
    assert rejected.status == "rejected"
    assert store.get_artifacts(job.job_id) == []
