from __future__ import annotations

from pathlib import Path

import pytest

from canto.core.delegation_promotion import DelegationPromotionService, PromotionError
from canto.core.delegation_review import DelegationReviewService
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
