from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
import yaml

import canto.core.jobs as jobs_module
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
            policy=Policy(allow_network=True, approved_domains=["example.com"]),
        )
    )
    result = service.process_job(job.job_id)
    assert result.status == "waiting_for_dependency"
    assert "definitely-not-a-real-canto-package" in result.error["missing"]["python"]
    assert any(event["type"] == "dependency_check_completed" for event in store.get_events(job.job_id))


def test_check_dependencies_skill_reports_registered_provider(runtime):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="check_dependencies",
            provider="manifest_dependency_checker",
            inputs={"skill": "source_inventory", "provider": "public_html_crawler"},
        )
    )

    completed = service.process_job(job.job_id)

    assert completed.status == "completed"
    artifacts = store.get_artifacts(job.job_id)
    assert {item["name"] for item in artifacts} == {
        "dependency_report_json",
        "dependency_report_md",
    }
    report = json.loads(Path(completed.artifact_dir, "dependency_report.json").read_text())
    assert report["target"] == "provider source_inventory.public_html_crawler"
    assert report["status"] == "ready"
    assert report["missing"] == {"system": [], "python": []}


def test_network_provider_waits_for_unapproved_domain(runtime):
    _, _, _, service = runtime
    job = service.create_job(
        JobRequest(
            skill="source_inventory",
            provider="public_html_crawler",
            inputs={"source_url": "https://example.com"},
            policy=Policy(allow_network=True),
        )
    )

    waiting = service.process_job(job.job_id)

    assert waiting.status == "waiting_for_approval"
    assert waiting.requires_approval is True


def test_raw_sensitive_input_is_rejected_before_job_storage(runtime):
    _, registry, store, service = runtime
    provider = registry.provider_internal("scaffold_tool", "local_scaffolder")
    provider["inputs"]["api_token"] = {"type": "string", "required": False}

    with pytest.raises(jobs_module.JobError, match=r"inputs.api_token must be passed as an \*_ref field"):
        service.create_job(
            JobRequest(
                skill="scaffold_tool",
                provider="local_scaffolder",
                inputs={"name": "sample_tool", "api_token": "plaintext-secret"},
            )
        )

    assert store.jobs == {}


def test_sensitive_environment_reference_is_accepted(runtime):
    _, registry, _, service = runtime
    provider = registry.provider_internal("scaffold_tool", "local_scaffolder")
    provider["inputs"]["api_token_ref"] = {"type": "string", "required": False}

    job = service.create_job(
        JobRequest(
            skill="scaffold_tool",
            provider="local_scaffolder",
            inputs={"name": "sample_tool", "api_token_ref": "env:CANTO_API_TOKEN"},
        )
    )

    assert job.inputs["api_token_ref"] == "env:CANTO_API_TOKEN"


def test_check_dependencies_skill_reports_missing_dependency(runtime):
    settings, registry, _, service = runtime
    manifest_path = settings.skills_dir / "source_inventory/providers/public_html_crawler/provider.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["dependencies"]["python"].append("definitely-not-a-real-canto-package")
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    registry.reload()

    job = service.create_job(
        JobRequest(
            skill="check_dependencies",
            provider="manifest_dependency_checker",
            inputs={"skill": "source_inventory", "provider": "public_html_crawler"},
        )
    )
    completed = service.process_job(job.job_id)

    report = json.loads(Path(completed.artifact_dir, "dependency_report.json").read_text())
    assert report["status"] == "not_ready"
    assert report["missing"]["python"] == ["definitely-not-a-real-canto-package"]
    assert report["install_plan"] == [
        {
            "type": "python",
            "command": "python -m pip install definitely-not-a-real-canto-package",
            "approval_required": False,
        }
    ]


def test_migration_report_summarizes_source_inventory(runtime):
    settings, _, store, service = runtime
    source_job_id = "job_20260608_abc123"
    source_dir = settings.jobs_dir / source_job_id
    source_dir.mkdir(parents=True)
    (source_dir / "inventory.json").write_text(
        json.dumps(
            {
                "source_url": "https://example.com",
                "pages": [
                    {
                        "url": "https://example.com/",
                        "title": "Example",
                        "meta_description": "Home page",
                        "probable_type": "home",
                    },
                    {
                        "url": "https://example.com/news/item",
                        "title": "",
                        "meta_description": "",
                        "probable_type": "news",
                    },
                ],
                "media": ["https://example.com/image.jpg"],
                "warnings": ["One page could not be fetched."],
            }
        ),
        encoding="utf-8",
    )
    job = service.create_job(
        JobRequest(
            skill="migration_report",
            provider="local_markdown_report",
            inputs={"source_job_id": source_job_id, "target_cms": "WordPress"},
        )
    )

    completed = service.process_job(job.job_id)

    assert completed.status == "completed"
    report = json.loads(Path(completed.artifact_dir, "migration_report.json").read_text())
    assert report["target_cms"] == "WordPress"
    assert report["summary"] == {
        "pages": 2,
        "media": 1,
        "warnings": 1,
        "pages_without_titles": 1,
        "pages_without_descriptions": 1,
    }
    assert report["probable_content_groups"] == {"home": 1, "news": 1}
    assert {item["name"] for item in store.get_artifacts(job.job_id)} == {
        "migration_report_json",
        "migration_report_md",
    }


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


def test_concurrent_approval_decisions_only_one_wins(runtime):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="scaffold_tool",
            provider="local_scaffolder",
            inputs={"name": "decision_test"},
        )
    )
    waiting = service.process_job(job.job_id)
    barrier = threading.Barrier(3)
    outcomes = []
    outcomes_lock = threading.Lock()

    def decide(action):
        barrier.wait()
        try:
            result = action()
            outcome = result.status
        except jobs_module.JobError as exc:
            outcome = str(exc)
        with outcomes_lock:
            outcomes.append(outcome)

    workers = [
        threading.Thread(
            target=decide,
            args=(lambda: service.approve(waiting.approval_id, "cantor", "Approved"),),
        ),
        threading.Thread(
            target=decide,
            args=(lambda: service.reject(waiting.approval_id, "cantor", "Rejected"),),
        ),
    ]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()

    approval = store.get_approval(waiting.approval_id)
    assert approval["status"] in {"approved", "rejected"}
    assert len([outcome for outcome in outcomes if outcome in {"completed", "rejected"}]) == 1
    assert len([outcome for outcome in outcomes if outcome.startswith("Approval is already")]) == 1


def test_concurrent_processing_runs_provider_once(runtime, monkeypatch):
    _, _, store, service = runtime
    job = service.create_job(
        JobRequest(
            skill="source_inventory",
            provider="public_html_crawler",
            inputs={"source_url": "https://example.com"},
            policy=Policy(allow_network=True, approved_domains=["example.com"]),
        )
    )
    calls = 0
    calls_lock = threading.Lock()

    def fake_run_provider(*args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return {"summary": "Completed once"}

    monkeypatch.setattr(jobs_module, "run_provider", fake_run_provider)
    monkeypatch.setattr(jobs_module, "collect_artifacts", lambda *args, **kwargs: [])

    barrier = threading.Barrier(3)

    def process() -> None:
        barrier.wait()
        service.process_job(job.job_id)

    workers = [threading.Thread(target=process) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()

    assert calls == 1
    assert store.get_job(job.job_id)["status"] == "completed"
    assert [event["type"] for event in store.get_events(job.job_id)].count("provider_started") == 1
