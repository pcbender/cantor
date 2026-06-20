from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from canto.core.cli_executor import (
    CLI_HARNESSES,
    CliAdapter,
    CliExecutor,
    CliExecutorError,
    adapter_for_profile,
    available_for_profile,
)
from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import ExecutorLaunch, ExecutorProfile, ExecutorSession
from canto.models.schemas import utc_now


class ExecutorError(CliExecutorError):
    pass


class DelegationCliExecutor:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
        *,
        timeout_seconds: int = 1800,
        adapter: CliAdapter | None = None,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.timeout_seconds = timeout_seconds
        self.adapter = adapter

    @staticmethod
    def available(profile: ExecutorProfile) -> str:
        try:
            return available_for_profile(profile)
        except CliExecutorError as exc:
            raise ExecutorError(str(exc)) from exc

    def _executor_for_profile(self, profile: ExecutorProfile) -> CliExecutor:
        adapter = self.adapter or adapter_for_profile(profile)
        return CliExecutor(adapter, timeout_seconds=self.timeout_seconds)

    def command(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        try:
            return self._executor_for_profile(profile).command(profile, workspace)
        except CliExecutorError as exc:
            raise ExecutorError(str(exc)) from exc

    def prompt(
        self,
        task_id: str,
        *,
        variant_name: str | None = None,
        supplement: str | None = None,
    ) -> str:
        task = self.delegation.get_task(task_id)
        sections = [
            "You are a Canto delegated Worker.",
            "Read .canto/agents/shared.md and .canto/agents/executor.md before working.",
            "The executor.md filename is retained for compatibility; its public role is Worker.",
            "Work only in this delegated Workspace and follow the Canto assignment instructions below.",
            "Do not modify the canonical repository.",
            "Do not self-assign, broaden scope, commit, push, accept, reject, queue, or Apply a Result.",
            "When complete, leave the Workspace ready for `canto delegate capture` so Canto can record an immutable Result for Developer review.",
            "",
            f"Delegated assignment: {task.title}",
            "",
            task.instructions,
        ]
        effective_variant = variant_name or task.variant_name
        effective_supplement = supplement or task.prompt_supplement
        if effective_variant:
            sections.extend(["", f"Prompt variant: {effective_variant}"])
        if effective_supplement:
            sections.extend(["", "Supplemental instruction:", effective_supplement])
        reviews = self.delegation.get_records(task_id, "reviews")
        revision_reviews = [
            review
            for review in reviews
            if review.get("decision") == "revision_requested"
        ]
        revision_messages = [
            message
            for message in self.delegation.get_records(task_id, "messages")
            if message.get("kind") == "revision"
        ]
        revision_note = None
        if revision_reviews:
            revision_note = revision_reviews[-1].get("note")
        elif revision_messages:
            revision_note = revision_messages[-1].get("body")
        if task.status == "revision_requested" and revision_note:
            sections.extend(
                [
                    "",
                    "Revision feedback:",
                    revision_note,
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
                "Complete the assigned work in this worktree and report a concise Result summary.",
            ]
        )
        return "\n".join(sections).strip() + "\n"

    def projected_sessions(self, task_id: str) -> list[dict]:
        sessions = self.delegation.get_records(task_id, "sessions")
        launches = self.delegation.get_records(task_id, "launches")
        launches_by_session = {launch["session_id"]: launch for launch in launches}
        projected = []
        for session in sessions:
            value = dict(session)
            launch = launches_by_session.get(session["session_id"])
            if launch and launch.get("ended_at"):
                value["ended_at"] = launch["ended_at"]
                value["status"] = (
                    "completed"
                    if launch.get("exit_code") == 0 and not launch.get("timed_out")
                    else "failed"
                )
            projected.append(value)
        return projected

    def launch(
        self,
        task_id: str,
        *,
        variant_name: str | None = None,
        supplement: str | None = None,
    ) -> ExecutorLaunch:
        task = self.delegation.get_task(task_id)
        if task.status not in {"workspace_ready", "revision_requested"}:
            raise ExecutorError(
                "CLI Worker launch requires a workspace_ready or revision_requested task"
            )
        if not task.executor_id:
            raise ExecutorError("Delegation task has no assigned executor")
        profile = self.delegation.get_executor_profile(task.executor_id)
        if profile.harness not in CLI_HARNESSES or profile.launch_mode != "canto":
            raise ExecutorError("Assigned executor is not a Canto-launched CLI profile")
        workspace = self.workspaces.get(task_id)
        workspace_path = Path(workspace.path)
        artifact_dir = workspace_path.parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        launch_id = f"launch_{uuid4().hex}"
        prompt_path = artifact_dir / f"{launch_id}.prompt.md"
        stdout_path = artifact_dir / f"{launch_id}.stdout.log"
        stderr_path = artifact_dir / f"{launch_id}.stderr.log"
        effective_variant = variant_name or task.variant_name
        effective_supplement = supplement or task.prompt_supplement
        prompt = self.prompt(
            task_id,
            variant_name=effective_variant,
            supplement=effective_supplement,
        )
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
            details={"session_id": session_id, "harness": profile.harness},
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
            prompt_variant=effective_variant,
            prompt_supplement=effective_supplement,
        )
        result = self._executor_for_profile(profile).run(
            profile,
            workspace_path,
            prompt,
            base_commit=workspace.base_commit,
            allowed_paths=workspace.allowed_paths,
            denied_paths=workspace.denied_paths,
        )
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        if result.timed_out:
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
        launch = launch.model_copy(
            update={"exit_code": result.exit_code, "ended_at": utc_now()}
        )
        if result.exit_code:
            launch = launch.model_copy(
                update={
                    "outcome": "failed",
                    "outcome_detail": result.outcome_detail,
                }
            )
            self.delegation.append_record(task_id, "launches", launch)
            self.delegation.transition(
                task_id,
                "failed",
                details={"launch_id": launch.launch_id, "exit_code": result.exit_code},
            )
            return launch
        launch = launch.model_copy(
            update={
                "workspace_changed": result.workspace_changed,
                "outcome": result.outcome,
                "outcome_detail": result.outcome_detail,
            }
        )
        self.delegation.append_record(task_id, "launches", launch)
        self.delegation.transition(
            task_id,
            "executor_done",
            details={
                "launch_id": launch.launch_id,
                "exit_code": 0,
                "worker_outcome": result.outcome,
                "workspace_changed": result.workspace_changed,
            },
        )
        return launch


class CodexCliExecutor(DelegationCliExecutor):
    pass
