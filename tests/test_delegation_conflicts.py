from __future__ import annotations

from canto.core.delegation_conflicts import DelegationConflictService
from canto.core.delegation_queue import DelegationPromotionQueue
from canto.models.delegation import PromotionResult
from tests.test_delegation_queue import accepted_tasks, git


def test_conflict_report_identifies_overlapping_task_and_paths(tmp_path):
    service, workspaces, _ = accepted_tasks(tmp_path, ["src/app.py", "src/app.py"])
    queue = DelegationPromotionQueue(service, workspaces)
    queue.enqueue("task_1", "orchestrator")
    queue.enqueue("task_2", "orchestrator")

    report = DelegationConflictService(service, workspaces).explain("task_2")
    overlap = next(blocker for blocker in report.blockers if blocker.code == "queue_overlap")
    assert overlap.conflicting_task_id == "task_1"
    assert overlap.overlapping_paths == ["src/app.py"]
    assert "dequeue" in overlap.safe_actions


def test_conflict_report_distinguishes_stale_base(tmp_path):
    service, workspaces, repository = accepted_tasks(tmp_path, ["src/app.py"])
    (repository / "README.md").write_text("advance\n")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "advance")

    report = DelegationConflictService(service, workspaces).explain("task_1")
    stale = next(blocker for blocker in report.blockers if blocker.code == "stale_base")
    assert stale.expected_base != stale.actual_head
    assert "manual reconciliation" in stale.safe_actions


def test_conflict_report_surfaces_failed_promotion_recovery_state(tmp_path):
    service, workspaces, repository = accepted_tasks(tmp_path, ["src/app.py"])
    service.append_record(
        "task_1",
        "promotions",
        PromotionResult(
            promotion_id="promotion_failed",
            task_id="task_1",
            result_revision=1,
            status="promotion_failed",
            repository_head="head",
            rollback_attempted=True,
            rollback_succeeded=False,
            error="induced apply failure",
        ),
    )
    report = DelegationConflictService(service, workspaces).explain("task_1")
    failure = next(blocker for blocker in report.blockers if blocker.code == "promotion_failure")
    assert failure.rollback_attempted is True
    assert failure.rollback_succeeded is False
    assert "inspect partial state" in failure.safe_actions
