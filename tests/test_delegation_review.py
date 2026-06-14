from __future__ import annotations

from pathlib import Path

import pytest

from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_review import DelegationReviewService, ReviewError
from tests.test_delegation_artifacts import executor_done


def capture(tmp_path, value: int = 2):
    service, workspaces, workspace = executor_done(tmp_path)
    (workspace / "src" / "app.py").write_text(f"value = {value}\n")
    result = DelegationArtifactService(service, workspaces).capture("task_1")
    return service, workspaces, workspace, result


def test_accept_binds_latest_unchanged_result_revision(tmp_path):
    service, workspaces, _, result = capture(tmp_path)

    review = DelegationReviewService(service, workspaces).accept(
        "task_1", "reviewer", "Looks correct"
    )

    task = service.get_task("task_1")
    assert review.result_revision == result.revision
    assert task.status == "accepted"
    assert task.accepted_result_revision == result.revision


def test_accept_rejects_workspace_change_after_capture(tmp_path):
    service, workspaces, workspace, _ = capture(tmp_path)
    (workspace / "src" / "app.py").write_text("value = 3\n")

    with pytest.raises(ReviewError, match="changed after result capture"):
        DelegationReviewService(service, workspaces).accept("task_1", "reviewer")


def test_revision_request_preserves_prior_result_and_accepts_new_revision(tmp_path):
    service, workspaces, workspace, first = capture(tmp_path)
    reviews = DelegationReviewService(service, workspaces)

    reviews.request_revision("task_1", "reviewer", "Use value 4")
    service.transition("task_1", "executor_working")
    (workspace / "src" / "app.py").write_text("value = 4\n")
    service.transition("task_1", "executor_done")
    second = DelegationArtifactService(service, workspaces).capture("task_1")
    reviews.accept("task_1", "reviewer")

    assert first.revision == 1
    assert second.revision == 2
    assert len(service.get_records("task_1", "results")) == 2
    assert [review.decision for review in reviews.list_reviews("task_1")] == [
        "revision_requested",
        "accepted",
    ]


def test_revision_can_be_requested_after_promotion_failure(tmp_path):
    service, workspaces, _, result = capture(tmp_path)
    reviews = DelegationReviewService(service, workspaces)
    reviews.accept("task_1", "reviewer")
    service.transition("task_1", "promoting")
    service.transition("task_1", "promotion_failed")

    review = reviews.request_revision(
        "task_1", "reviewer", "Recapture with complete promotion artifacts"
    )

    assert review.result_revision == result.revision
    assert service.get_task("task_1").status == "revision_requested"
    assert service.get_task("task_1").accepted_result_revision is None
