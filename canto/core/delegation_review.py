from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_artifacts import (
    ArtifactCaptureError,
    DelegationArtifactService,
    workspace_patch,
)
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import DelegationReview, DelegationResult


class ReviewError(DelegationError):
    pass


class DelegationReviewService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.artifacts = DelegationArtifactService(delegation, workspaces)

    def request_revision(
        self, task_id: str, reviewer: str, note: str
    ) -> DelegationReview:
        task, result = self._reviewable(task_id)
        review = self._record(task_id, result, "revision_requested", reviewer, note)
        self.delegation.transition(
            task_id,
            "revision_requested",
            updates={"accepted_result_revision": None},
            details={"review_id": review.review_id, "revision": result.revision},
        )
        return review

    def accept(self, task_id: str, reviewer: str, note: str = "") -> DelegationReview:
        task, result = self._reviewable(task_id)
        workspace = self.workspaces.get(task_id)
        current_patch = workspace_patch(Path(workspace.path), result.base_commit)
        current_checksum = hashlib.sha256(current_patch.encode("utf-8")).hexdigest()
        if current_checksum != result.workspace_patch_sha256:
            raise ReviewError(
                "Workspace changed after result capture; request a revision and recapture"
            )
        self._verify_artifacts(task_id, result)
        review = self._record(task_id, result, "accepted", reviewer, note)
        self.delegation.transition(
            task_id,
            "accepted",
            updates={"accepted_result_revision": result.revision},
            details={"review_id": review.review_id, "revision": result.revision},
        )
        return review

    def reject(self, task_id: str, reviewer: str, note: str) -> DelegationReview:
        _, result = self._reviewable(task_id)
        review = self._record(task_id, result, "rejected", reviewer, note)
        self.delegation.transition(
            task_id,
            "rejected",
            updates={"accepted_result_revision": None},
            details={"review_id": review.review_id, "revision": result.revision},
        )
        return review

    def list_reviews(self, task_id: str) -> list[DelegationReview]:
        return [
            DelegationReview.model_validate(value)
            for value in self.delegation.get_records(task_id, "reviews")
        ]

    def _reviewable(self, task_id: str):
        task = self.delegation.get_task(task_id)
        if task.status != "reviewing":
            raise ReviewError("Delegation task is not awaiting review")
        result = self.artifacts.get(task_id)
        if result.revision != task.latest_result_revision:
            raise ReviewError("Only the latest result revision can be reviewed")
        return task, result

    def _verify_artifacts(self, task_id: str, result: DelegationResult) -> None:
        workspace = self.workspaces.get(task_id)
        artifact_root = Path(workspace.path).parent / "artifacts"
        for artifact in result.artifacts:
            path = artifact_root / artifact.relative_path
            if not path.is_file():
                raise ReviewError(f"Captured artifact is missing: {artifact.name}")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum != artifact.sha256:
                raise ReviewError(f"Captured artifact checksum changed: {artifact.name}")

    def _record(
        self,
        task_id: str,
        result: DelegationResult,
        decision: str,
        reviewer: str,
        note: str,
    ) -> DelegationReview:
        review = DelegationReview(
            review_id=f"review_{uuid4().hex}",
            task_id=task_id,
            result_revision=result.revision,
            decision=decision,
            reviewer=reviewer,
            note=note,
        )
        self.delegation.append_record(task_id, "reviews", review)
        return review
