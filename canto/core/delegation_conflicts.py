from __future__ import annotations

from canto.core.delegation import DelegationService
from canto.core.delegation_queue import DelegationPromotionQueue
from canto.core.delegation_review_summary import DelegationReviewSummaryService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import DelegationBlocker, DelegationConflictReport


class DelegationConflictService:
    def __init__(self, delegation: DelegationService, workspaces: DelegationWorkspaceService):
        self.delegation = delegation
        self.workspaces = workspaces

    def explain(self, task_id: str) -> DelegationConflictReport:
        task = self.delegation.get_task(task_id)
        workspace = self.workspaces.get(task_id)
        repository = workspace.repository.canonical_path
        blockers: list[DelegationBlocker] = []
        results = self.delegation.get_records(task_id, "results")
        if results:
            summary = DelegationReviewSummaryService(self.delegation, self.workspaces).summarize(task_id)
            for message in summary.blockers:
                if message.startswith("Artifact checksum invalid"):
                    code, actions = "artifact_checksum", ["recapture", "reject"]
                elif message.startswith("Workspace changed"):
                    code, actions = "workspace_changed", ["revise", "recapture"]
                elif message.startswith("Canonical repository HEAD"):
                    code, actions = "stale_base", ["revise", "recapture", "manual reconciliation"]
                elif message.startswith("Canonical repository has uncommitted"):
                    code, actions = "dirty_worktree", ["manual reconciliation", "retry"]
                else:
                    continue
                blockers.append(
                    DelegationBlocker(
                        code=code,
                        message=message,
                        repository=repository,
                        task_id=task_id,
                        result_revision=summary.result_revision,
                        expected_base=summary.base_commit,
                        actual_head=summary.canonical_head,
                        safe_actions=actions,
                    )
                )
        queue_records = self.delegation.get_records(task_id, "promotion_queue")
        if queue_records:
            entry = queue_records[-1]
            current = DelegationPromotionQueue(self.delegation, self.workspaces).blockers(
                task_id, entry["base_commit"], entry["changed_files"]
            )
            for message in current:
                if not message.startswith("overlaps queued task "):
                    continue
                prefix, _, paths = message.partition(": ")
                other_id = prefix.removeprefix("overlaps queued task ")
                blockers.append(
                    DelegationBlocker(
                        code="queue_overlap",
                        message=message,
                        repository=repository,
                        task_id=task_id,
                        result_revision=entry["result_revision"],
                        conflicting_task_id=other_id,
                        overlapping_paths=paths.split(", ") if paths else [],
                        safe_actions=["dequeue", "revise", "manual reconciliation"],
                    )
                )
        promotions = self.delegation.get_records(task_id, "promotions")
        if promotions and promotions[-1].get("status") == "promotion_failed":
            promotion = promotions[-1]
            blockers.append(
                DelegationBlocker(
                    code="promotion_failure",
                    message=promotion.get("error") or "Promotion failed",
                    repository=repository,
                    task_id=task_id,
                    result_revision=promotion.get("result_revision"),
                    rollback_attempted=promotion.get("rollback_attempted", False),
                    rollback_succeeded=promotion.get("rollback_succeeded"),
                    safe_actions=["inspect partial state", "manual reconciliation", "reject"],
                )
            )
        return DelegationConflictReport(task_id=task_id, blockers=blockers)
