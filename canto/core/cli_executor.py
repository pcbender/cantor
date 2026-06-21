from __future__ import annotations

import json
import os
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
    harness: str

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


class AgentCliAdapter:
    provider = ""
    harness = ""
    default_executable = ""
    unavailable_label = "CLI executable"

    @classmethod
    def available(cls, profile: ExecutorProfile) -> str:
        if profile.harness != cls.harness:
            raise CliExecutorError(f"Executor profile is not a {cls.provider} CLI profile")
        executable = profile.executable or cls.default_executable
        resolved = shutil.which(executable)
        if not resolved:
            raise CliExecutorError(f"{cls.unavailable_label} is unavailable: {executable}")
        return str(Path(resolved).resolve())

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
        return None

    def map_quota(self, completed: subprocess.CompletedProcess[str]) -> bool:
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        return "rate limit" in text or "quota" in text or "usage limit" in text


class CodexCliAdapter(AgentCliAdapter):
    provider = "codex"
    harness = "codex_cli"
    default_executable = "codex"
    unavailable_label = "Codex CLI executable"

    def build_argv(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        executable = self.available(profile)
        command = [
            executable,
            "exec",
            "--sandbox",
            "workspace-write",
            "--add-dir",
            str(canto_state_root().resolve()),
        ]
        if codex_needs_network(profile):
            command.extend(("-c", "sandbox_workspace_write.network_access=true"))
        command.extend(
            [
                "--cd",
                str(workspace.resolve()),
            ]
        )
        if profile.model:
            command.extend(("--model", profile.model))
        command.extend(profile.configuration.get("extra_args", []))
        command.append("-")
        return command

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


def canto_state_root() -> Path:
    configured = os.getenv("CANTO_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".canto"


def codex_needs_network(profile: ExecutorProfile) -> bool:
    if profile.permissions.allow_network:
        return True
    if profile.model_provider == "ollama":
        return True
    extra_args = profile.configuration.get("extra_args", [])
    if "--local-provider" in extra_args and "ollama" in extra_args:
        return True
    return bool(profile.model_provider and profile.model_provider != "ollama")


class ClaudeCliAdapter(AgentCliAdapter):
    provider = "claude"
    harness = "claude_cli"
    default_executable = "claude"
    unavailable_label = "Claude CLI executable"

    def build_argv(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        executable = self.available(profile)
        command = [
            executable,
            "--print",
            "--input-format",
            "text",
            "--output-format",
            "text",
            "--permission-mode",
            "acceptEdits",
            "--add-dir",
            str(workspace.resolve()),
            "--no-session-persistence",
        ]
        if profile.model:
            command.extend(("--model", profile.model))
        command.extend(profile.configuration.get("extra_args", []))
        return command

    def assert_auth(self, profile: ExecutorProfile | None = None) -> None:
        if profile and profile.model_provider == "ollama":
            return
        executable = self.available(
            profile
            or ExecutorProfile(
                executor_id="claude",
                name="Claude",
                harness="claude_cli",
                launch_mode="canto",
            )
        )
        try:
            completed = subprocess.run(
                [executable, "auth", "status"],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
                env=build_subprocess_env(self.provider),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkerAuthError(f"Cannot inspect Claude auth state: {exc}") from exc
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise WorkerAuthError(
                "Claude subscription auth is unavailable"
                + (f": {detail}" if detail else "")
            )
        text = f"{completed.stdout}\n{completed.stderr}".lower()
        if '"authmethod": "claude.ai"' not in text and "claude.ai" not in text:
            raise WorkerAuthError("Claude CLI is not using claude.ai subscription auth")
        if "apikey" in text or "api key" in text:
            raise WorkerAuthError("Claude CLI appears to be using API key auth")


class GeminiCliAdapter(AgentCliAdapter):
    provider = "gemini"
    harness = "gemini_cli"
    default_executable = "gemini"
    unavailable_label = "Gemini CLI executable"

    def build_argv(self, profile: ExecutorProfile, workspace: Path) -> list[str]:
        executable = self.available(profile)
        command = [
            executable,
            "--prompt",
            "",
            "--skip-trust",
            "--sandbox",
            "--approval-mode",
            "auto_edit",
            "--output-format",
            "text",
        ]
        if profile.model:
            command.extend(("--model", profile.model))
        command.extend(profile.configuration.get("extra_args", []))
        return command


CLI_ADAPTERS: dict[str, type[AgentCliAdapter]] = {
    "codex_cli": CodexCliAdapter,
    "claude_cli": ClaudeCliAdapter,
    "gemini_cli": GeminiCliAdapter,
}

CLI_HARNESSES = frozenset(CLI_ADAPTERS)


def adapter_for_profile(profile: ExecutorProfile) -> AgentCliAdapter:
    adapter_class = CLI_ADAPTERS.get(profile.harness)
    if adapter_class is None:
        raise CliExecutorError(f"Unsupported Canto CLI harness: {profile.harness}")
    return adapter_class()


def available_for_profile(profile: ExecutorProfile) -> str:
    return adapter_for_profile(profile).available(profile)


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
