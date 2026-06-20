from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from canto.core.cli_env import build_subprocess_env
from canto.core.delegation import DelegationError
from canto.core.delegation_artifacts import classify_worker_outcome
from canto.models.delegation import ExecutorProfile


class CliExecutorError(DelegationError):
    pass


class WorkerAuthError(CliExecutorError):
    pass


@dataclass(frozen=True)
class CliExecutionResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    workspace_changed: bool | None = None
    outcome: str | None = None
    outcome_detail: str | None = None


class CliAdapter(Protocol):
    provider: str

    def build_argv(self, profile: ExecutorProfile, workspace: Path) -> list[str]: ...

    def parse(
        self,
        completed: subprocess.CompletedProcess[str],
        workspace: Path,
        *,
        base_commit: str,
        allowed_paths: list[str],
        denied_paths: list[str],
    ) -> CliExecutionResult: ...

    def assert_auth(self, profile: ExecutorProfile | None = None) -> None: ...

    def map_quota(self, completed: subprocess.CompletedProcess[str]) -> bool: ...


class CodexCliAdapter:
    provider = "codex"

    @staticmethod
    def available(profile: ExecutorProfile) -> str:
        if profile.harness != "codex_cli":
            raise CliExecutorError("Executor profile is not a Codex CLI profile")
        executable = profile.executable or "codex"
        resolved = shutil.which(executable)
        if not resolved:
            raise CliExecutorError(f"Codex CLI executable is unavailable: {executable}")
        return str(Path(resolved).resolve())

    def build_argv(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
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

    def parse(
        self,
        completed: subprocess.CompletedProcess[str],
        workspace: Path,
        *,
        base_commit: str,
        allowed_paths: list[str],
        denied_paths: list[str],
    ) -> CliExecutionResult:
        if completed.returncode:
            return CliExecutionResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                outcome="failed",
                outcome_detail=(
                    f"Worker process exited with code {completed.returncode}"
                ),
            )
        workspace_changed, outcome, outcome_detail = classify_worker_outcome(
            workspace,
            base_commit,
            completed.stdout,
            allowed_paths=allowed_paths,
            denied_paths=denied_paths,
        )
        return CliExecutionResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            workspace_changed=workspace_changed,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )

    def assert_auth(self, profile: ExecutorProfile | None = None) -> None:
        if profile and profile.model_provider == "ollama":
            return
        auth_path = Path.home() / ".codex" / "auth.json"
        if not auth_path.is_file():
            raise WorkerAuthError("Codex subscription auth is unavailable")
        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerAuthError(f"Cannot read Codex auth state: {exc}") from exc
        if payload.get("auth_mode") != "chatgpt":
            raise WorkerAuthError("Codex CLI is not using ChatGPT subscription auth")
        if payload.get("OPENAI_API_KEY") is not None:
            raise WorkerAuthError("Codex auth state contains an API key")

    def map_quota(self, completed: subprocess.CompletedProcess[str]) -> bool:
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        return "rate limit" in text or "quota" in text or "usage limit" in text


class CliExecutor:
    def __init__(self, adapter: CliAdapter, *, timeout_seconds: int = 1800):
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds

    def command(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        return self.adapter.build_argv(profile, workspace)

    def run(
        self,
        profile: ExecutorProfile,
        workspace: Path,
        prompt: str,
        *,
        base_commit: str,
        allowed_paths: list[str],
        denied_paths: list[str],
    ) -> CliExecutionResult:
        argv = self.command(profile, workspace)
        try:
            completed = subprocess.run(
                argv,
                cwd=workspace,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=build_subprocess_env(self.adapter.provider),
            )
        except subprocess.TimeoutExpired as exc:
            return CliExecutionResult(
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
            )
        return self.adapter.parse(
            completed,
            workspace,
            base_commit=base_commit,
            allowed_paths=allowed_paths,
            denied_paths=denied_paths,
        )
