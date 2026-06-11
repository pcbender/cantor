from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.repository import RepositoryConfigError, load_repository
from canto.models.delegation import DelegationWorkspace, RepositoryIdentity
from canto.models.schemas import utc_now


class WorkspaceError(DelegationError):
    pass


def _git(repository: Path, *args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise WorkspaceError(f"Git command failed ({' '.join(args)}): {message}")
    return completed.stdout.strip()


def inspect_repository(repository: str | Path) -> RepositoryIdentity:
    root = Path(repository).expanduser().resolve()
    if not root.is_dir():
        raise WorkspaceError(f"Repository does not exist: {root}")
    top_level = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top_level != root:
        raise WorkspaceError(f"Repository path must be the Git top level: {root}")
    common_dir_value = _git(root, "rev-parse", "--git-common-dir")
    common_dir = Path(common_dir_value)
    if not common_dir.is_absolute():
        common_dir = root / common_dir
    remotes: dict[str, str] = {}
    for name in _git(root, "remote").splitlines():
        if name:
            remotes[name] = _git(root, "remote", "get-url", name)
    repo_id = None
    if (root / ".canto" / "repo.toml").is_file():
        try:
            repo_id = load_repository(root).repo_id
        except RepositoryConfigError as exc:
            raise WorkspaceError(str(exc)) from exc
    return RepositoryIdentity(
        repo_id=repo_id,
        canonical_path=str(root),
        git_common_dir=str(common_dir.resolve()),
        initial_head=_git(root, "rev-parse", "HEAD"),
        remotes=remotes,
    )


def verify_repository_identity(expected: RepositoryIdentity) -> RepositoryIdentity:
    current = inspect_repository(expected.canonical_path)
    if expected.repo_id and current.repo_id != expected.repo_id:
        raise WorkspaceError("Canto repository identity changed")
    if expected.git_common_dir and current.git_common_dir != expected.git_common_dir:
        raise WorkspaceError("Repository Git common-dir identity changed")
    if expected.initial_head and current.initial_head != expected.initial_head:
        raise WorkspaceError("Repository HEAD changed from the recorded initial commit")
    if expected.remotes and current.remotes != expected.remotes:
        raise WorkspaceError("Repository remote metadata changed")
    return current


def _normalize_scope_path(repository: Path, value: str) -> str:
    candidate = PurePosixPath(value.replace(os.sep, "/"))
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceError(f"Invalid repository scope path: {value!r}")
    normalized = candidate.as_posix().lstrip("./")
    if not normalized or normalized == ".git" or normalized.startswith(".git/"):
        raise WorkspaceError(f"Invalid repository scope path: {value!r}")
    current = repository
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.is_symlink():
            raise WorkspaceError(f"Symlinks are not allowed in repository scope: {value}")
    try:
        current.resolve().relative_to(repository)
    except ValueError as exc:
        raise WorkspaceError(f"Repository scope escapes the repository: {value}") from exc
    return normalized


def _overlaps(path: str, denied: str) -> bool:
    return path == denied or path.startswith(f"{denied}/") or denied.startswith(f"{path}/")


class DelegationWorkspaceService:
    def __init__(self, delegation: DelegationService, root: str | Path):
        self.delegation = delegation
        self.root = Path(root).expanduser().resolve()

    def prepare(self, task_id: str) -> DelegationWorkspace:
        task = self.delegation.get_task(task_id)
        if task.status != "assigned":
            raise WorkspaceError("A workspace can only be prepared for an assigned task")
        repository = Path(task.repository.canonical_path).resolve()
        identity = verify_repository_identity(task.repository)
        allowed = sorted(
            {_normalize_scope_path(repository, value) for value in task.scope.allowed_paths}
        )
        denied = sorted(
            {_normalize_scope_path(repository, value) for value in task.scope.denied_paths}
        )
        if not allowed:
            raise WorkspaceError("Delegation scope requires at least one allowed path")
        overlaps = [
            f"{path} <-> {blocked}"
            for path in allowed
            for blocked in denied
            if _overlaps(path, blocked)
        ]
        if overlaps:
            raise WorkspaceError(
                "Allowed and denied repository paths overlap: " + ", ".join(overlaps)
            )

        workspace_id = f"workspace_{uuid4().hex}"
        branch = f"canto/delegation/{task_id}-{workspace_id[-8:]}"
        task_root = (self.root / task_id).resolve()
        workspace_path = (task_root / "workspace").resolve()
        if self.root not in workspace_path.parents:
            raise WorkspaceError("Managed workspace path escaped the delegation root")
        task_root.mkdir(parents=True, exist_ok=False)
        try:
            _git(repository, "worktree", "add", "-b", branch, str(workspace_path), identity.initial_head or "HEAD")
            patterns: list[str] = []
            for path in allowed:
                patterns.extend((f"/{path}", f"/{path}/**"))
            for path in denied:
                patterns.extend((f"!/{path}", f"!/{path}/**"))
            # Role manuals are read context, not task scope. Capture still rejects
            # modifications because these paths are not in allowed_paths.
            patterns.extend(
                (
                    "/AGENTS.md",
                    "/.canto/delegate.toml",
                    "/.canto/agents",
                    "/.canto/agents/**",
                )
            )
            _git(workspace_path, "sparse-checkout", "set", "--no-cone", "--stdin", input_text="\n".join(patterns) + "\n")
        except Exception:
            if workspace_path.exists():
                subprocess.run(
                    ["git", "-C", str(repository), "worktree", "remove", "--force", str(workspace_path)],
                    capture_output=True,
                    check=False,
                )
            if task_root.exists():
                task_root.rmdir()
            raise

        workspace = DelegationWorkspace(
            workspace_id=workspace_id,
            task_id=task_id,
            path=str(workspace_path),
            branch=branch,
            base_commit=identity.initial_head or "",
            repository=identity,
            allowed_paths=allowed,
            denied_paths=denied,
        )
        self.delegation.append_record(task_id, "workspaces", workspace)
        self.delegation.transition(
            task_id,
            "workspace_ready",
            updates={"workspace_id": workspace.workspace_id},
            details={"workspace_id": workspace.workspace_id},
        )
        return workspace

    def get(self, task_id: str) -> DelegationWorkspace:
        records = self.delegation.get_records(task_id, "workspaces")
        if not records:
            raise WorkspaceError(f"Workspace not found for delegation task: {task_id}")
        return DelegationWorkspace.model_validate(records[-1])

    def inspect(self, task_id: str) -> dict[str, object]:
        workspace = self.get(task_id)
        path = Path(workspace.path)
        return {
            "workspace": workspace,
            "exists": path.is_dir(),
            "head": _git(path, "rev-parse", "HEAD") if path.is_dir() else None,
            "changes": _git(path, "status", "--short").splitlines() if path.is_dir() else [],
        }

    def remove(self, task_id: str) -> DelegationWorkspace:
        workspace = self.get(task_id)
        if workspace.status == "removed":
            return workspace
        path = Path(workspace.path).resolve()
        if self.root not in path.parents:
            raise WorkspaceError("Refusing to remove a workspace outside the managed root")
        repository = Path(workspace.repository.canonical_path)
        if path.exists():
            _git(repository, "worktree", "remove", "--force", str(path))
        _git(repository, "branch", "-D", workspace.branch)
        updated = workspace.model_copy(update={"status": "removed", "removed_at": utc_now()})
        self.delegation.append_record(task_id, "workspace_lifecycle", updated)
        return updated
