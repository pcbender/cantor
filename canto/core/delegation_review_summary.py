from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService, workspace_patch
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import DelegationReviewSummary


class ReviewSummaryError(DelegationError):
    pass


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args], text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


class DelegationReviewSummaryService:
    def __init__(self, delegation: DelegationService, workspaces: DelegationWorkspaceService):
        self.delegation = delegation
        self.workspaces = workspaces

    def summarize(self, task_id: str, revision: int | None = None) -> DelegationReviewSummary:
        task = self.delegation.get_task(task_id)
        result = DelegationArtifactService(self.delegation, self.workspaces).get(task_id, revision)
        workspace = self.workspaces.get(task_id)
        artifact_root = Path(workspace.path).parent / "artifacts"
        artifacts = {artifact.name: artifact for artifact in result.artifacts}
        blockers: list[str] = []
        checksums_valid = True
        for artifact in result.artifacts:
            path = artifact_root / artifact.relative_path
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
                checksums_valid = False
                blockers.append(f"Artifact checksum invalid: {artifact.name}")
        changed_files: list[str] = []
        changed = artifacts.get("changed_files.json")
        if changed and (artifact_root / changed.relative_path).is_file():
            changed_files = [
                item["path"]
                for item in json.loads((artifact_root / changed.relative_path).read_text(encoding="utf-8"))
            ]
        patch_text = ""
        patch = artifacts.get("proposal.diff")
        if patch and (artifact_root / patch.relative_path).is_file():
            patch_text = (artifact_root / patch.relative_path).read_text(encoding="utf-8")
        additions = sum(1 for line in patch_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in patch_text.splitlines() if line.startswith("-") and not line.startswith("---"))
        current_patch = workspace_patch(Path(workspace.path), result.base_commit)
        if hashlib.sha256(current_patch.encode("utf-8")).hexdigest() != result.workspace_patch_sha256:
            blockers.append("Workspace changed after result capture")
        records = self.delegation.get_records(task_id, "commands")
        command_groups = {
            status: [record for record in records if record.get("status") == status]
            for status in ("passed", "failed", "reported", "waived")
        }
        missing = DelegationCommandService(self.delegation, self.workspaces).unmet_required(task_id)
        if missing:
            blockers.append("Required commands are not satisfied: " + ", ".join(missing))
        repository = Path(workspace.repository.canonical_path)
        head = _git(repository, "rev-parse", "HEAD")
        if head != result.base_commit:
            blockers.append("Canonical repository HEAD no longer matches result base")
        dirty = bool(changed_files and _git(repository, "status", "--porcelain", "--", *changed_files))
        if dirty:
            blockers.append("Canonical repository has uncommitted changes in affected paths")
        acceptance_ready = task.status == "reviewing" and not blockers
        promotion_ready = (
            task.status == "accepted"
            and task.accepted_result_revision == result.revision
            and not blockers
        )
        return DelegationReviewSummary(
            task_id=task_id,
            status=task.status,
            result_revision=result.revision,
            producing_session_id=result.producing_session_id,
            producing_launch_id=result.producing_launch_id,
            executor_id=task.executor_id,
            prompt_variant=result.prompt_variant,
            changed_files=changed_files,
            patch_additions=additions,
            patch_deletions=deletions,
            commands=command_groups,
            missing_commands=missing,
            artifact_checksums_valid=checksums_valid,
            canonical_head=head or None,
            base_commit=result.base_commit,
            canonical_clean_for_changed_files=not dirty,
            acceptance_ready=acceptance_ready,
            promotion_ready=promotion_ready,
            blockers=blockers,
        )
