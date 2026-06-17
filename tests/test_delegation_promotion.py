from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from canto.core.delegation_promotion import DelegationPromotionService, PromotionError
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_review import DelegationReviewService
from tests.test_delegation_artifacts import executor_done
from tests.test_delegation_review import capture


def accepted(tmp_path):
    service, workspaces, workspace, result = capture(tmp_path)
    DelegationReviewService(service, workspaces).accept("task_1", "reviewer")
    repository = Path(workspaces.get("task_1").repository.canonical_path)
    return service, workspaces, workspace, repository, result


def test_promote_applies_exact_accepted_patch_without_commit(tmp_path):
    service, workspaces, _, repository, result = accepted(tmp_path)
    original_head = result.base_commit

    promotion = DelegationPromotionService(service, workspaces).promote(
        "task_1", "orchestrator"
    )

    assert promotion.status == "promoted"
    assert (repository / "src" / "app.py").read_text() == "value = 2\n"
    assert service.get_task("task_1").status == "promoted"
    assert promotion.repository_head == original_head


def test_promote_verifies_new_untracked_files_without_changing_index(tmp_path):
    service, workspaces, workspace = executor_done(tmp_path)
    (workspace / "src" / "new.py").write_text("")
    result = DelegationArtifactService(service, workspaces).capture("task_1")
    DelegationReviewService(service, workspaces).accept("task_1", "reviewer")
    repository = Path(workspaces.get("task_1").repository.canonical_path)

    promotion = DelegationPromotionService(service, workspaces).promote(
        "task_1", "orchestrator"
    )

    assert promotion.status == "promoted"
    assert (repository / "src" / "new.py").read_text() == ""
    status = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain", "--", "src/new.py"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    assert status == "?? src/new.py\n"
    assert result.workspace_patch_sha256


def test_promote_accepts_equivalent_patch_with_different_diff_format(tmp_path):
    service, workspaces, workspace, repository, _ = accepted(tmp_path)
    artifact_root = workspace.parent / "artifacts" / "revision-1"
    abbreviated_patch = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--binary", "HEAD", "--", "src/app.py"],
        capture_output=True,
        check=True,
    ).stdout
    assert abbreviated_patch
    proposal = artifact_root / "proposal.diff"
    proposal.chmod(0o600)
    proposal.write_bytes(abbreviated_patch)
    proposal.chmod(0o400)
    checksum = hashlib.sha256(abbreviated_patch).hexdigest()
    stored = service.store.delegation_records[("task_1", "results")][0]
    for artifact in stored["artifacts"]:
        if artifact["name"] == "proposal.diff":
            artifact["sha256"] = checksum
    stored["workspace_patch_sha256"] = checksum

    promotion = DelegationPromotionService(service, workspaces).promote(
        "task_1", "orchestrator"
    )

    assert promotion.status == "promoted"
    assert (repository / "src" / "app.py").read_text() == "value = 2\n"


def test_promote_blocks_dirty_affected_canonical_path(tmp_path):
    service, workspaces, _, repository, _ = accepted(tmp_path)
    (repository / "src" / "app.py").write_text("canonical local change\n")

    with pytest.raises(PromotionError, match="uncommitted changes"):
        DelegationPromotionService(service, workspaces).promote(
            "task_1", "orchestrator"
        )

    assert service.get_task("task_1").status == "accepted"


def test_post_apply_failure_rolls_back_and_records_failure(tmp_path, monkeypatch):
    service, workspaces, _, repository, _ = accepted(tmp_path)
    promotions = DelegationPromotionService(service, workspaces)

    def fail_verification(*args, **kwargs):
        raise PromotionError("induced verification failure")

    monkeypatch.setattr(promotions, "_verify_applied", fail_verification)
    with pytest.raises(PromotionError, match="rollback_succeeded=True"):
        promotions.promote("task_1", "orchestrator")

    assert (repository / "src" / "app.py").read_text() == "value = 1\n"
    assert service.get_task("task_1").status == "promotion_failed"
    assert service.get_records("task_1", "promotions")[0]["rollback_succeeded"] is True


def test_safely_rolled_back_promotion_can_be_retried(tmp_path, monkeypatch):
    service, workspaces, _, repository, _ = accepted(tmp_path)
    promotions = DelegationPromotionService(service, workspaces)

    monkeypatch.setattr(
        promotions,
        "_verify_applied",
        lambda *args, **kwargs: (_ for _ in ()).throw(PromotionError("induced")),
    )
    with pytest.raises(PromotionError, match="rollback_succeeded=True"):
        promotions.promote("task_1", "orchestrator")
    monkeypatch.undo()

    retry = DelegationPromotionService(service, workspaces).promote(
        "task_1", "orchestrator"
    )

    assert retry.status == "promoted"
    assert (repository / "src" / "app.py").read_text() == "value = 2\n"
