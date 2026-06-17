from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_workspace import (
    DelegationWorkspaceService,
    verify_repository_identity,
)
from canto.core.delegation_commands import DelegationCommandService
from canto.models.delegation import PromotionDecision, PromotionResult


class PromotionError(DelegationError):
    pass


def _git(
    repository: Path,
    *args: str,
    stdin: bytes | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        input=stdin,
        capture_output=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    if completed.returncode:
        message = completed.stderr.decode(errors="replace").strip()
        raise PromotionError(message or f"Git command failed: {' '.join(args)}")
    return completed.stdout


def _matches(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in roots)


class DelegationPromotionService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.artifacts = DelegationArtifactService(delegation, workspaces)

    def promote(
        self, task_id: str, decided_by: str, note: str = ""
    ) -> PromotionResult:
        task = self.delegation.get_task(task_id)
        if task.status not in {"accepted", "promotion_failed"}:
            raise PromotionError(
                "Only an accepted or safely rolled-back delegation task can be promoted"
            )
        if task.status == "promotion_failed":
            promotions = self.delegation.get_records(task_id, "promotions")
            if not promotions or promotions[-1].get("rollback_succeeded") is not True:
                raise PromotionError(
                    "Failed promotion cannot be retried because rollback was not confirmed"
                )
        if task.accepted_result_revision != task.latest_result_revision:
            raise PromotionError("Accepted revision is not the latest result revision")
        result = self.artifacts.get(task_id, task.accepted_result_revision)
        workspace = self.workspaces.get(task_id)
        unmet_commands = DelegationCommandService(
            self.delegation, self.workspaces
        ).unmet_required(task_id)
        if unmet_commands:
            raise PromotionError(
                "Required commands are not satisfied: " + ", ".join(unmet_commands)
            )
        verify_repository_identity(workspace.repository)
        repository = Path(workspace.repository.canonical_path)
        head = _git(repository, "rev-parse", "HEAD").decode().strip()
        if head != result.base_commit:
            raise PromotionError("Canonical repository HEAD no longer matches result base")

        artifact_root = Path(workspace.path).parent / "artifacts"
        proposal = next(
            (artifact for artifact in result.artifacts if artifact.name == "proposal.diff"),
            None,
        )
        changed_artifact = next(
            (artifact for artifact in result.artifacts if artifact.name == "changed_files.json"),
            None,
        )
        if proposal is None or changed_artifact is None:
            raise PromotionError("Accepted result is missing required promotion artifacts")
        proposal_path = artifact_root / proposal.relative_path
        changed_path = artifact_root / changed_artifact.relative_path
        patch = self._verified_content(proposal_path, proposal.sha256)
        changed_content = self._verified_content(changed_path, changed_artifact.sha256)
        changed_records = json.loads(changed_content)
        changed_files = sorted({item["path"] for item in changed_records})
        for path in changed_files:
            if _matches(path, workspace.denied_paths):
                raise PromotionError(f"Accepted patch contains denied path: {path}")
            if not _matches(path, workspace.allowed_paths):
                raise PromotionError(f"Accepted patch contains out-of-scope path: {path}")
        if not changed_files:
            raise PromotionError("Accepted patch has no changed files")
        if _git(repository, "status", "--porcelain", "--", *changed_files).strip():
            raise PromotionError("Canonical repository has uncommitted changes in affected paths")
        _git(repository, "apply", "--check", "--binary", "-", stdin=patch)

        decision = PromotionDecision(
            decision_id=f"decision_{uuid4().hex}",
            task_id=task_id,
            result_revision=result.revision,
            decision="promote",
            decided_by=decided_by,
            note=note,
        )
        self.delegation.append_record(task_id, "promotion_decisions", decision)
        self.delegation.transition(
            task_id,
            "promoting",
            details={"decision_id": decision.decision_id, "revision": result.revision},
        )
        promotion_id = f"promotion_{uuid4().hex}"
        try:
            self._apply(repository, patch)
            self._verify_applied(repository, result.base_commit, patch, changed_files)
        except Exception as exc:
            rollback_succeeded = self._rollback(repository, patch)
            promotion = PromotionResult(
                promotion_id=promotion_id,
                task_id=task_id,
                result_revision=result.revision,
                status="promotion_failed",
                changed_files=changed_files,
                repository_head=head,
                rollback_attempted=True,
                rollback_succeeded=rollback_succeeded,
                error=str(exc),
            )
            self.delegation.append_record(task_id, "promotions", promotion)
            self.delegation.transition(
                task_id,
                "promotion_failed",
                details={
                    "promotion_id": promotion_id,
                    "rollback_succeeded": rollback_succeeded,
                    "error": str(exc),
                },
            )
            raise PromotionError(
                f"Promotion failed; rollback_succeeded={rollback_succeeded}: {exc}"
            ) from exc

        promotion = PromotionResult(
            promotion_id=promotion_id,
            task_id=task_id,
            result_revision=result.revision,
            status="promoted",
            changed_files=changed_files,
            repository_head=head,
        )
        self.delegation.append_record(task_id, "promotions", promotion)
        self.delegation.transition(
            task_id,
            "promoted",
            details={"promotion_id": promotion_id, "changed_files": changed_files},
        )
        return promotion

    @staticmethod
    def _verified_content(path: Path, expected_checksum: str) -> bytes:
        if not path.is_file():
            raise PromotionError(f"Promotion artifact is missing: {path.name}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_checksum:
            raise PromotionError(f"Promotion artifact checksum changed: {path.name}")
        return content

    def _apply(self, repository: Path, patch: bytes) -> None:
        _git(repository, "apply", "--binary", "-", stdin=patch)

    def _verify_applied(
        self, repository: Path, base_commit: str, patch: bytes, changed_files: list[str]
    ) -> None:
        # Compare the accepted patch and canonical worktree through isolated
        # indexes. Equivalent tree state is what matters; raw Git diff bytes can
        # differ even when the accepted paths and blobs are identical.
        with tempfile.TemporaryDirectory(prefix="canto-promotion-index-") as root:
            expected_env = {"GIT_INDEX_FILE": str(Path(root) / "expected-index")}
            actual_env = {"GIT_INDEX_FILE": str(Path(root) / "actual-index")}
            _git(repository, "read-tree", base_commit, env=expected_env)
            _git(
                repository,
                "apply",
                "--cached",
                "--binary",
                "-",
                stdin=patch,
                env=expected_env,
            )
            _git(repository, "read-tree", base_commit, env=actual_env)
            _git(repository, "add", "-A", "--", *changed_files, env=actual_env)
            expected = self._index_entries(repository, changed_files, expected_env)
            actual = self._index_entries(repository, changed_files, actual_env)
        if expected != actual:
            raise PromotionError(
                "Applied canonical content does not match accepted patch"
            )

    @staticmethod
    def _index_entries(
        repository: Path, changed_files: list[str], env: dict[str, str]
    ) -> bytes:
        return _git(repository, "ls-files", "-s", "--", *changed_files, env=env)

    @staticmethod
    def _rollback(repository: Path, patch: bytes) -> bool:
        try:
            _git(repository, "apply", "--reverse", "--binary", "-", stdin=patch)
            return True
        except PromotionError:
            return False
