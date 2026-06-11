from __future__ import annotations

import shutil
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_executor import CodexCliExecutor
from canto.core.delegation_promotion import DelegationPromotionService
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_timeline import DelegationTimelineService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.repository import initialize_repository
from canto.core.state import SqliteStateStore
from canto.models.delegation import DelegationScope, DelegationTask, ExecutorProfile


class DelegationDemoError(RuntimeError):
    def __init__(self, root: Path, cause: Exception):
        self.root = root
        super().__init__(f"Delegation demo failed; evidence preserved at {root}: {cause}")


class DelegationDemoResult(BaseModel):
    root: str
    repository: str
    workspace: str
    artifact_root: str
    state_file: str
    task_id: str
    status: str
    timeline_entries: int
    cleaned_up: bool = False


def _git(repository: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=True)


def cleanup_delegation_demo(root: str | Path) -> None:
    path = Path(root)
    if not path.exists():
        return
    for current, directories, files in os.walk(path):
        for name in directories:
            Path(current, name).chmod(0o700)
        for name in files:
            Path(current, name).chmod(0o600)
    path.chmod(0o700)
    shutil.rmtree(path)


def run_delegation_demo(
    *,
    mode: Literal["scripted", "cloud", "ollama"] = "scripted",
    model: str | None = None,
    promote: bool = False,
    keep: bool = False,
) -> DelegationDemoResult:
    root = Path(tempfile.mkdtemp(prefix="canto-delegation-demo-")).resolve()
    try:
        repository = root / "repository"
        repository.mkdir()
        _git(repository, "init")
        _git(repository, "config", "user.email", "demo@example.com")
        _git(repository, "config", "user.name", "Canto Demo")
        (repository / "src").mkdir()
        (repository / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "initial")
        initialize_repository(repository)

        state_file = root / "canto-home" / "state.sqlite"
        service = DelegationService(SqliteStateStore(state_file))
        workspaces = DelegationWorkspaceService(
            service, root / "canto-home" / "work" / "delegations"
        )
        executable = "codex"
        configuration = {}
        provider = "openai" if mode == "cloud" else None
        if mode == "scripted":
            script = root / "scripted-codex"
            script.write_text(
                "#!/bin/sh\ncat >/dev/null\nprintf 'value = 2\\n' > src/app.py\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            executable = str(script)
        elif mode == "ollama":
            provider = "ollama"
            configuration = {"extra_args": ["--oss", "--local-provider", "ollama"]}
        profile = ExecutorProfile(
            executor_id=f"demo-{mode}",
            name=f"Demo {mode}",
            harness="codex_cli",
            executable=executable,
            model_provider=provider,
            model=model,
            launch_mode="canto",
            configuration=configuration,
            permissions={"command_enforcement": "canto_observed"},
        )
        service.set_executor_profile(profile)
        task_id = "task_demo"
        service.create_task(
            DelegationTask(
                task_id=task_id,
                title="Delegated executor demo",
                instructions="Change src/app.py value from 1 to 2.",
                repository=inspect_repository(repository),
                scope=DelegationScope(
                    allowed_paths=["src"],
                    denied_paths=[".env"],
                    allowed_commands=["git diff --check"],
                    required_commands=["git diff --check"],
                ),
            )
        )
        service.transition(task_id, "assigned", updates={"executor_id": profile.executor_id})
        workspace = workspaces.prepare(task_id)
        launch = CodexCliExecutor(service, workspaces, timeout_seconds=1800).launch(task_id)
        if launch.exit_code != 0:
            raise RuntimeError(f"Demo executor failed with exit code {launch.exit_code}")
        DelegationCommandService(service, workspaces).run(task_id, "git diff --check")
        result = DelegationArtifactService(service, workspaces).capture(task_id)
        if promote:
            DelegationReviewService(service, workspaces).accept(task_id, "demo-reviewer")
            DelegationPromotionService(service, workspaces).promote(task_id, "demo-reviewer")
        timeline = DelegationTimelineService(service).timeline(task_id)
        value = DelegationDemoResult(
            root=str(root),
            repository=str(repository),
            workspace=workspace.path,
            artifact_root=str(Path(workspace.path).parent / "artifacts" / f"revision-{result.revision}"),
            state_file=str(state_file),
            task_id=task_id,
            status=service.get_task(task_id).status,
            timeline_entries=len(timeline),
        )
        if not keep:
            cleanup_delegation_demo(root)
            value = value.model_copy(update={"cleaned_up": True})
        return value
    except Exception as exc:
        # Preserve failed demos for diagnosis; the caller prints the root path.
        raise DelegationDemoError(root, exc) from exc
