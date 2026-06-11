from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import ExecutorLaunch, ExecutorProfile, ExecutorSession
from canto.models.schemas import utc_now


class ExecutorError(DelegationError):
    pass


class CodexCliExecutor:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
        *,
        timeout_seconds: int = 1800,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def available(profile: ExecutorProfile) -> str:
        if profile.harness != "codex_cli":
            raise ExecutorError("Executor profile is not a Codex CLI profile")
        executable = profile.executable or "codex"
        resolved = shutil.which(executable)
        if not resolved:
            raise ExecutorError(f"Codex CLI executable is unavailable: {executable}")
        return str(Path(resolved).resolve())

    def command(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        executable = self.available(profile)
        command = [
            executable,
            "exec",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(workspace.resolve()),
        ]
        if profile.model:
            command.extend(("--model", profile.model))
        command.extend(profile.configuration.get("extra_args", []))
        command.append("-")
        return command

    def prompt(self, task_id: str) -> str:
        task = self.delegation.get_task(task_id)
        sections = [
            f"Delegation task: {task.title}",
            "",
            task.instructions,
        ]
        reviews = self.delegation.get_records(task_id, "reviews")
        revision_reviews = [
            review
            for review in reviews
            if review.get("decision") == "revision_requested"
        ]
        if task.status == "revision_requested" and revision_reviews:
            sections.extend(
                [
                    "",
                    "Revision feedback:",
                    revision_reviews[-1].get("note", "Address the requested revision."),
                ]
            )
        sections.extend(
            [
                "",
                "Allowed repository paths:",
                *[f"- {path}" for path in task.scope.allowed_paths],
                "",
                "Denied repository paths:",
                *[f"- {path}" for path in task.scope.denied_paths],
                "",
                "Do not access credentials, publish changes, commit, push, or modify denied paths.",
                "Complete the requested work in this worktree and report a concise summary.",
            ]
        )
        return "\n".join(sections).strip() + "\n"

    def launch(self, task_id: str) -> ExecutorLaunch:
        task = self.delegation.get_task(task_id)
        if task.status not in {"workspace_ready", "revision_requested"}:
            raise ExecutorError(
                "Codex CLI launch requires a workspace_ready or revision_requested task"
            )
        if not task.executor_id:
            raise ExecutorError("Delegation task has no assigned executor")
        profile = self.delegation.get_executor_profile(task.executor_id)
        if profile.harness != "codex_cli" or profile.launch_mode != "canto":
            raise ExecutorError("Assigned executor is not a Canto-launched Codex CLI profile")
        workspace = self.workspaces.get(task_id)
        workspace_path = Path(workspace.path)
        artifact_dir = workspace_path.parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        launch_id = f"launch_{uuid4().hex}"
        prompt_path = artifact_dir / f"{launch_id}.prompt.md"
        stdout_path = artifact_dir / f"{launch_id}.stdout.log"
        stderr_path = artifact_dir / f"{launch_id}.stderr.log"
        prompt = self.prompt(task_id)
        prompt_path.write_text(prompt, encoding="utf-8")

        session_id = f"session_{uuid4().hex}"
        session = ExecutorSession(
            session_id=session_id,
            task_id=task_id,
            executor_id=profile.executor_id,
            status="running",
            enforcement="canto_observed",
            started_at=utc_now(),
        )
        self.delegation.append_record(task_id, "sessions", session)
        self.delegation.transition(
            task_id,
            "executor_working",
            details={"session_id": session_id, "harness": "codex_cli"},
        )
        argv = self.command(profile, workspace_path)
        launch = ExecutorLaunch(
            launch_id=launch_id,
            task_id=task_id,
            session_id=session_id,
            executor_id=profile.executor_id,
            argv=argv,
            cwd=str(workspace_path),
            prompt_path=str(prompt_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )
        environment = {
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "PATH", "TERM")
            if key in os.environ
        }
        try:
            completed = subprocess.run(
                argv,
                cwd=workspace_path,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
            )
            stdout_path.write_text(completed.stdout, encoding="utf-8")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
            launch = launch.model_copy(
                update={"exit_code": completed.returncode, "ended_at": utc_now()}
            )
            self.delegation.append_record(task_id, "launches", launch)
            if completed.returncode:
                self.delegation.transition(
                    task_id,
                    "failed",
                    details={"launch_id": launch.launch_id, "exit_code": completed.returncode},
                )
            else:
                self.delegation.transition(
                    task_id,
                    "executor_done",
                    details={"launch_id": launch.launch_id, "exit_code": 0},
                )
            return launch
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(exc.stdout or "", encoding="utf-8")
            stderr_path.write_text(exc.stderr or "", encoding="utf-8")
            launch = launch.model_copy(
                update={"timed_out": True, "ended_at": utc_now()}
            )
            self.delegation.append_record(task_id, "launches", launch)
            self.delegation.transition(
                task_id,
                "failed",
                details={"launch_id": launch.launch_id, "timed_out": True},
            )
            return launch
