from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_promotion import DelegationPromotionService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import PromotionQueueEntry


class QueueError(DelegationError):
    pass


def _overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


class DelegationPromotionQueue:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.artifacts = DelegationArtifactService(delegation, workspaces)

    def enqueue(self, task_id: str, enqueued_by: str) -> PromotionQueueEntry:
        task = self.delegation.get_task(task_id)
        if task.status != "accepted" or task.accepted_result_revision is None:
            raise QueueError("Only an accepted result can enter the promotion queue")
        if self._entry(task_id):
            raise QueueError(f"Delegation task is already queued: {task_id}")
        result = self.artifacts.get(task_id, task.accepted_result_revision)
        changed_files = self._changed_files(task_id, result.revision)
        blockers = self.blockers(task_id, result.base_commit, changed_files)
        entry = PromotionQueueEntry(
            queue_id=f"queue_{uuid4().hex}",
            task_id=task_id,
            result_revision=result.revision,
            base_commit=result.base_commit,
            changed_files=changed_files,
            status="blocked" if blockers else "pending",
            blockers=blockers,
            enqueued_by=enqueued_by,
        )
        self.delegation.append_record(task_id, "promotion_queue", entry)
        return entry

    def blockers(
        self, task_id: str, base_commit: str, changed_files: list[str]
    ) -> list[str]:
        workspace = self.workspaces.get(task_id)
        repository = Path(workspace.repository.canonical_path)
        current_head = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        blockers = []
        if current_head != base_commit:
            blockers.append(
                f"canonical HEAD diverged: expected {base_commit}, found {current_head}"
            )
        for other in self.list():
            if other.task_id == task_id or other.status not in {"pending", "blocked"}:
                continue
            other_workspace = self.workspaces.get(other.task_id)
            if (
                other_workspace.repository.canonical_path
                != workspace.repository.canonical_path
            ):
                continue
            overlaps = sorted(
                {
                    left
                    for left in changed_files
                    for right in other.changed_files
                    if _overlap(left, right)
                }
            )
            if overlaps:
                blockers.append(
                    f"overlaps queued task {other.task_id}: {', '.join(overlaps)}"
                )
        return blockers

    def list(self) -> list[PromotionQueueEntry]:
        entries = []
        for task in self.delegation.list_tasks():
            records = self.delegation.get_records(task.task_id, "promotion_queue")
            if records:
                entries.append(PromotionQueueEntry.model_validate(records[-1]))
        return sorted(entries, key=lambda entry: (entry.created_at, entry.queue_id))

    def promote(self, task_id: str, decided_by: str):
        entry = self._entry(task_id)
        if not entry:
            raise QueueError(f"Delegation task is not queued: {task_id}")
        blockers = self.blockers(
            task_id, entry.base_commit, entry.changed_files
        )
        if blockers:
            raise QueueError("Promotion queue blockers: " + "; ".join(blockers))
        return DelegationPromotionService(
            self.delegation, self.workspaces
        ).promote(task_id, decided_by, "Promoted from delegation queue")

    def _entry(self, task_id: str) -> PromotionQueueEntry | None:
        records = self.delegation.get_records(task_id, "promotion_queue")
        return PromotionQueueEntry.model_validate(records[-1]) if records else None

    def _changed_files(self, task_id: str, revision: int) -> list[str]:
        result = self.artifacts.get(task_id, revision)
        artifact = next(
            (
                item
                for item in result.artifacts
                if item.name == "changed_files.json"
            ),
            None,
        )
        if artifact is None:
            raise QueueError("Accepted result is missing changed_files.json")
        workspace = self.workspaces.get(task_id)
        path = Path(workspace.path).parent / "artifacts" / artifact.relative_path
        return sorted({item["path"] for item in json.loads(path.read_text())})
