from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import DelegationArtifact, DelegationResult


class ArtifactCaptureError(DelegationError):
    pass


def _git(workspace: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ArtifactCaptureError(
            completed.stderr.strip() or f"Git command failed: {' '.join(args)}"
        )
    return completed.stdout


def _matches(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in roots)


def _changed_files(workspace: Path) -> list[dict[str, str]]:
    output = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        check=True,
    ).stdout
    entries = output.split(b"\0")
    changed: list[dict[str, str]] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2].decode("ascii", errors="replace")
        path = os.fsdecode(entry[3:]).replace(os.sep, "/")
        if status[0] in {"R", "C"} and index < len(entries):
            source = os.fsdecode(entries[index]).replace(os.sep, "/")
            index += 1
            changed.append({"path": source, "status": "D "})
        changed.append({"path": path, "status": status})
    return sorted(changed, key=lambda item: item["path"])


def _artifact(path: Path, root: Path) -> DelegationArtifact:
    content = path.read_bytes()
    return DelegationArtifact(
        name=path.name,
        relative_path=path.relative_to(root).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def workspace_patch(workspace: Path, base_commit: str) -> str:
    changes = _changed_files(workspace)
    untracked = [item["path"] for item in changes if item["status"] == "??"]
    if untracked:
        _git(workspace, "add", "-N", "--", *untracked)
    return _git(workspace, "diff", "--binary", "--full-index", base_commit, "--")


class DelegationArtifactService:
    REQUIRED_NAMES = (
        "proposal.diff",
        "changed_files.json",
        "commands.log",
        "summary.md",
    )

    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
    ):
        self.delegation = delegation
        self.workspaces = workspaces

    def capture(self, task_id: str) -> DelegationResult:
        task = self.delegation.get_task(task_id)
        if task.status != "executor_done":
            raise ArtifactCaptureError("Artifacts can only be captured from executor_done")
        workspace = self.workspaces.get(task_id)
        root = Path(workspace.path)
        changes = _changed_files(root)
        if not changes:
            raise ArtifactCaptureError("Delegation workspace has no changes to capture")
        for change in changes:
            path = PurePosixPath(change["path"])
            if path.is_absolute() or ".." in path.parts:
                raise ArtifactCaptureError(f"Invalid changed path: {change['path']}")
            if _matches(change["path"], workspace.denied_paths):
                raise ArtifactCaptureError(f"Denied path changed: {change['path']}")
            if not _matches(change["path"], workspace.allowed_paths):
                raise ArtifactCaptureError(f"Out-of-scope path changed: {change['path']}")
            filesystem_path = root / change["path"]
            if filesystem_path.is_symlink():
                raise ArtifactCaptureError(f"Symlink changes are not allowed: {change['path']}")

        patch = workspace_patch(root, workspace.base_commit)
        if not patch:
            raise ArtifactCaptureError("Workspace changes did not produce a reviewable patch")

        revision = task.latest_result_revision + 1
        result_id = f"result_{uuid4().hex}"
        artifact_root = root.parent / "artifacts"
        revision_root = artifact_root / f"revision-{revision}"
        try:
            revision_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ArtifactCaptureError(
                f"Artifact revision already exists: {revision}"
            ) from exc

        command_records = self.delegation.get_records(task_id, "commands")
        messages = self.delegation.get_records(task_id, "messages")
        done_messages = [message for message in messages if message.get("kind") == "done"]
        summary = done_messages[-1]["body"] if done_messages else "Executor reported completion."
        (revision_root / "proposal.diff").write_text(patch, encoding="utf-8")
        (revision_root / "changed_files.json").write_text(
            json.dumps(changes, indent=2) + "\n", encoding="utf-8"
        )
        (revision_root / "commands.log").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in command_records),
            encoding="utf-8",
        )
        (revision_root / "summary.md").write_text(
            f"# Delegation Result\n\n{summary}\n", encoding="utf-8"
        )
        artifacts = [
            _artifact(revision_root / name, artifact_root) for name in self.REQUIRED_NAMES
        ]
        for path in revision_root.iterdir():
            path.chmod(0o444)
        revision_root.chmod(0o555)
        result = DelegationResult(
            result_id=result_id,
            task_id=task_id,
            revision=revision,
            base_commit=workspace.base_commit,
            workspace_patch_sha256=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
            artifacts=artifacts,
            executor_summary=summary,
        )
        self.delegation.append_record(task_id, "results", result)
        self.delegation.transition(
            task_id,
            "reviewing",
            updates={"latest_result_revision": revision},
            details={"result_id": result_id, "revision": revision},
        )
        return result

    def get(self, task_id: str, revision: int | None = None) -> DelegationResult:
        results = [
            DelegationResult.model_validate(value)
            for value in self.delegation.get_records(task_id, "results")
        ]
        if not results:
            raise ArtifactCaptureError(f"No result captured for delegation task: {task_id}")
        if revision is None:
            return results[-1]
        for result in results:
            if result.revision == revision:
                return result
        raise ArtifactCaptureError(f"Result revision not found: {revision}")
