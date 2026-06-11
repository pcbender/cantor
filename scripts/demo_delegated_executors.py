from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from canto.core.delegation import DelegationService
from canto.core.delegation_artifacts import DelegationArtifactService
from canto.core.delegation_commands import DelegationCommandService
from canto.core.delegation_executor import CodexCliExecutor
from canto.core.delegation_promotion import DelegationPromotionService
from canto.core.delegation_queue import DelegationPromotionQueue
from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_timeline import DelegationTimelineService
from canto.core.delegation_workspace import DelegationWorkspaceService, inspect_repository
from canto.core.state import SqliteStateStore
from canto.models.delegation import DelegationScope, DelegationTask, ExecutorProfile


def git(repository: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        check=True,
    )


def repository(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.email", "demo@example.com")
    git(path, "config", "user.name", "Canto Demo")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    return path


def create_task(
    service: DelegationService, repository_path: Path, task_id: str, executor_id: str
) -> None:
    service.create_task(
        DelegationTask(
            task_id=task_id,
            title=f"Update {task_id}",
            instructions="Change src/app.py value from 1 to 2.",
            repository=inspect_repository(repository_path),
            scope=DelegationScope(
                allowed_paths=["src"],
                denied_paths=[".env"],
                allowed_commands=["git diff --check"],
                required_commands=["git diff --check"],
            ),
        )
    )
    service.transition(task_id, "assigned", updates={"executor_id": executor_id})


def review_and_promote(
    service: DelegationService,
    workspaces: DelegationWorkspaceService,
    task_id: str,
) -> None:
    DelegationArtifactService(service, workspaces).capture(task_id)
    DelegationReviewService(service, workspaces).accept(task_id, "demo-reviewer")
    queue = DelegationPromotionQueue(service, workspaces)
    queue.enqueue(task_id, "demo-reviewer")
    queue.promote(task_id, "demo-reviewer")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="canto-delegation-demo-") as temporary:
        root = Path(temporary)
        service = DelegationService(SqliteStateStore(root / "state" / "canto.db"))
        workspaces = DelegationWorkspaceService(service, root / "delegations")

        service.set_executor_profile(
            ExecutorProfile(executor_id="manual-demo", name="Manual demo", harness="manual")
        )
        manual_repository = repository(root, "manual-repository")
        create_task(service, manual_repository, "task_manual", "manual-demo")
        manual_workspace = workspaces.prepare("task_manual")
        service.transition("task_manual", "executor_working")
        (Path(manual_workspace.path) / "src" / "app.py").write_text(
            "value = 2\n", encoding="utf-8"
        )
        DelegationCommandService(service, workspaces).run(
            "task_manual", "git diff --check"
        )
        service.transition("task_manual", "executor_done")
        review_and_promote(service, workspaces, "task_manual")

        executable = root / "codex"
        executable.write_text(
            "#!/bin/sh\ncat >/dev/null\nprintf 'value = 2\\n' > src/app.py\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        service.set_executor_profile(
            ExecutorProfile(
                executor_id="codex-demo",
                name="Scripted Codex demo",
                harness="codex_cli",
                executable=str(executable),
                launch_mode="canto",
                permissions={"command_enforcement": "canto_observed"},
            )
        )
        codex_repository = repository(root, "codex-repository")
        create_task(service, codex_repository, "task_codex", "codex-demo")
        workspaces.prepare("task_codex")
        launch = CodexCliExecutor(service, workspaces, timeout_seconds=10).launch(
            "task_codex"
        )
        if launch.exit_code != 0:
            raise RuntimeError("Scripted Codex launch failed")
        DelegationCommandService(service, workspaces).run(
            "task_codex", "git diff --check"
        )
        review_and_promote(service, workspaces, "task_codex")

        reopened = DelegationService(
            SqliteStateStore(root / "state" / "canto.db")
        )
        timeline = DelegationTimelineService(reopened).timeline("task_codex")
        assert timeline
        assert (manual_repository / "src" / "app.py").read_text() == "value = 2\n"
        assert (codex_repository / "src" / "app.py").read_text() == "value = 2\n"
        print("Manual delegated executor workflow: promoted")
        print("Scripted Codex CLI workflow: promoted")
        print(f"Restart-safe timeline entries: {len(timeline)}")
        print("Canto delegated executor demo passed.")


if __name__ == "__main__":
    main()
