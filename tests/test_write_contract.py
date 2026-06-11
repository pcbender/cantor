from __future__ import annotations

import json
from pathlib import Path

import pytest

import canto.core.jobs as jobs_module
from canto.core.registry import Registry, RegistryError
from canto.core.write_contract import WriteContractError, validate_write_contract
from canto.core.jobs import JobError
from canto.models.schemas import JobRequest, Policy


def test_write_contract_rejects_incomplete_metadata():
    with pytest.raises(WriteContractError, match="modes"):
        validate_write_contract(
            {"runner": {"type": "python", "entrypoint": "run.py"}, "write": {}}
        )


def test_registry_rejects_malformed_write_provider(tmp_path):
    provider = tmp_path / "skills" / "bad" / "providers" / "local"
    provider.mkdir(parents=True)
    (tmp_path / "skills" / "bad" / "skill.yaml").write_text(
        "name: bad\nproviders: [local]\n", encoding="utf-8"
    )
    (provider / "provider.yaml").write_text(
        "name: local\nskill: bad\nrunner: {type: python, entrypoint: run.py}\nwrite: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "tools").mkdir()

    with pytest.raises(RegistryError, match="Invalid provider"):
        Registry(tmp_path / "skills", tmp_path / "tools")


def test_reference_write_provider_dry_run_is_deterministic_and_read_only(
    runtime, tmp_path
):
    _, registry, store, service = runtime
    target = tmp_path / "target.json"
    target.write_text('{"title": "Before"}\n', encoding="utf-8")
    inputs = {
        "target_path": str(target),
        "target_id": "local:test",
        "desired": {"title": "After"},
        "idempotency_key": "demo-1",
    }

    first = service.process_job(
        service.create_job(
            JobRequest(skill="managed_json", provider="local_document", inputs=inputs)
        ).job_id
    )
    second = service.process_job(
        service.create_job(
            JobRequest(skill="managed_json", provider="local_document", inputs=inputs)
        ).job_id
    )

    first_change = json.loads(
        (tmp_path / "work" / "jobs" / first.job_id / "change_set.json").read_text()
    )
    second_change = json.loads(
        (tmp_path / "work" / "jobs" / second.job_id / "change_set.json").read_text()
    )
    assert first.status == second.status == "completed"
    assert first_change == second_change
    assert json.loads(target.read_text()) == {"title": "Before"}
    assert len(store.get_artifacts(first.job_id)) == 4
    assert registry.provider_internal("managed_json", "local_document")["write"][
        "recovery"
    ]["mode"] == "rollback"


def _dry_run(service, target):
    return service.process_job(
        service.create_job(
            JobRequest(
                skill="managed_json",
                provider="local_document",
                inputs={
                    "target_path": str(target),
                    "target_id": "local:test",
                    "desired": {"title": "After"},
                    "idempotency_key": "promotion-1",
                },
            )
        ).job_id
    )


def test_write_promotion_uses_approval_and_job_service(runtime, tmp_path):
    _, _, store, service = runtime
    target = tmp_path / "target.json"
    target.write_text('{"title": "Before"}\n', encoding="utf-8")
    dry_run = _dry_run(service, target)

    approval = service.promote(dry_run.job_id)
    live_job = service.approve(approval.approval_id, "cantor", "Reviewed")

    assert approval.status == "pending"
    assert live_job.status == "completed"
    assert live_job.policy.mode == "live"
    assert live_job.approval_id == approval.approval_id
    assert json.loads(target.read_text()) == {"title": "After"}
    verification = json.loads(
        (Path(live_job.artifact_dir) / "verification.json").read_text()
    )
    assert verification["status"] == "passed"
    assert store.get_approval(approval.approval_id)["job_id"] == live_job.job_id


def test_direct_live_write_is_rejected(runtime, tmp_path):
    _, _, _, service = runtime
    with pytest.raises(JobError, match="approved dry-run promotion"):
        service.create_job(
            JobRequest(
                skill="managed_json",
                provider="local_document",
                inputs={
                    "target_path": str(tmp_path / "target.json"),
                    "target_id": "local:test",
                    "desired": {},
                    "idempotency_key": "direct-live",
                },
                policy=Policy(mode="live"),
            )
        )


def test_promotion_rejects_tampered_change_set(runtime, tmp_path):
    _, _, _, service = runtime
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    dry_run = _dry_run(service, target)
    approval = service.promote(dry_run.job_id)
    Path(approval.promotion["change_set_path"]).write_text("{}\n")

    with pytest.raises(JobError, match="change_set_checksum changed"):
        service.approve(approval.approval_id, "cantor", "Reviewed")

    assert json.loads(target.read_text()) == {}


def test_live_retry_returns_prior_result_without_mutation(runtime, tmp_path):
    _, _, _, service = runtime
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    dry_run = _dry_run(service, target)
    approval = service.promote(dry_run.job_id)
    first = service.approve(approval.approval_id, "cantor", "Reviewed")
    target.write_text('{"external": "change"}\n', encoding="utf-8")

    retry = service.create_job(
        JobRequest(
            skill=dry_run.skill,
            provider=dry_run.provider,
            inputs=dry_run.inputs,
            policy=Policy(mode="live"),
            approval_id=approval.approval_id,
        )
    )
    replay = service.process_job(retry.job_id)

    assert first.status == "completed"
    assert replay.status == "completed"
    assert replay.result["idempotent_replay"] is True
    assert replay.result["original_job_id"] == first.job_id
    assert json.loads(target.read_text()) == {"external": "change"}


def test_recovery_requires_approval_and_rolls_back(runtime, tmp_path):
    _, _, store, service = runtime
    target = tmp_path / "target.json"
    target.write_text('{"title": "Before"}\n', encoding="utf-8")
    dry_run = _dry_run(service, target)
    promotion = service.promote(dry_run.job_id)
    live = service.approve(promotion.approval_id, "cantor", "Reviewed")

    recovery = service.recover(live.job_id)
    assert recovery.status == "pending"
    assert json.loads(target.read_text()) == {"title": "After"}
    recovered = service.approve(recovery.approval_id, "cantor", "Rollback")

    assert recovered.status == "completed"
    assert recovered.recovery["live_job_id"] == live.job_id
    assert json.loads(target.read_text()) == {"title": "Before"}
    assert store.get_approval(recovery.approval_id)["job_id"] == recovered.job_id


def test_live_write_fails_safely_when_target_changed_after_review(
    runtime, tmp_path
):
    _, _, _, service = runtime
    target = tmp_path / "target.json"
    target.write_text('{"title": "Before"}\n', encoding="utf-8")
    dry_run = _dry_run(service, target)
    approval = service.promote(dry_run.job_id)
    target.write_text('{"title": "External"}\n', encoding="utf-8")

    live = service.approve(approval.approval_id, "cantor", "Reviewed")

    assert live.status == "failed"
    assert live.error["code"] == "provider_failed"
    assert json.loads(target.read_text()) == {"title": "External"}


def test_tampered_validation_artifact_blocks_promotion(runtime, tmp_path):
    _, _, _, service = runtime
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    dry_run = _dry_run(service, target)
    approval = service.promote(dry_run.job_id)
    Path(approval.promotion["validation_path"]).write_text(
        '{"valid": false}\n', encoding="utf-8"
    )

    with pytest.raises(JobError, match="validation_checksum changed"):
        service.approve(approval.approval_id, "cantor", "Reviewed")

    assert json.loads(target.read_text()) == {}


def test_failed_post_write_verification_prevents_completion(
    runtime, tmp_path, monkeypatch
):
    _, _, _, service = runtime
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    dry_run = _dry_run(service, target)
    approval = service.promote(dry_run.job_id)

    def failed_verification(provider, payload, artifact_dir, settings, **kwargs):
        for name, value in {
            "change_set.json": {},
            "validation.json": {"valid": True},
            "verification.json": {"status": "failed"},
            "recovery.json": {"status": "available", "mode": "rollback"},
        }.items():
            Path(artifact_dir, name).write_text(json.dumps(value), encoding="utf-8")
        return {"status": "completed", "summary": "provider exited cleanly"}

    monkeypatch.setattr(jobs_module, "run_provider", failed_verification)
    live = service.approve(approval.approval_id, "cantor", "Reviewed")

    assert live.status == "failed"
    assert live.error["message"] == "Post-write verification did not pass"
