from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from uuid import uuid4

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.models.delegation import CommandRecord


class CommandError(DelegationError):
    pass


SHELL_OPERATORS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "<<"}


def parse_command(command: str) -> list[str]:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise CommandError(f"Invalid command: {exc}") from exc
    if not argv:
        raise CommandError("Command cannot be empty")
    if any(token in SHELL_OPERATORS for token in argv):
        raise CommandError("Shell control operators and redirection are not allowed")
    if any("$(" in token or "`" in token for token in argv):
        raise CommandError("Shell substitutions are not allowed")
    return argv


class DelegationCommandService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
        *,
        timeout_seconds: int = 600,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.timeout_seconds = timeout_seconds

    def run(self, task_id: str, command: str, cwd: str = ".") -> CommandRecord:
        task = self.delegation.get_task(task_id)
        if task.status not in {"executor_working", "executor_done"}:
            raise CommandError("Commands can only run while executor work is active or done")
        argv = parse_command(command)
        allowed = set(task.scope.allowed_commands) | set(task.scope.required_commands)
        if allowed and command not in allowed:
            raise CommandError(f"Command is not allowed by task scope: {command}")
        workspace = self.workspaces.get(task_id)
        workspace_root = Path(workspace.path).resolve()
        cwd_path = PurePosixPath(cwd)
        if cwd_path.is_absolute() or ".." in cwd_path.parts:
            raise CommandError(f"Command working directory escapes workspace: {cwd}")
        run_cwd = (workspace_root / cwd_path.as_posix()).resolve()
        if not run_cwd.is_relative_to(workspace_root) or not run_cwd.is_dir():
            raise CommandError(f"Invalid command working directory: {cwd}")
        executable = Path(argv[0])
        if executable.is_absolute():
            raise CommandError("Absolute executable paths are not allowed")
        if "/" in argv[0]:
            candidate = (run_cwd / executable).resolve()
            if not candidate.is_relative_to(workspace_root):
                raise CommandError("Command executable escapes workspace")

        record_id = f"command_{uuid4().hex}"
        output_root = workspace_root.parent / "artifacts" / "commands"
        output_root.mkdir(parents=True, exist_ok=True)
        stdout_path = output_root / f"{record_id}.stdout.log"
        stderr_path = output_root / f"{record_id}.stderr.log"
        environment = {
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "PATH", "TERM")
            if key in os.environ
        }
        try:
            completed = subprocess.run(
                argv,
                cwd=run_cwd,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=environment,
            )
            stdout_path.write_text(completed.stdout, encoding="utf-8")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
            record = CommandRecord(
                record_id=record_id,
                task_id=task_id,
                command=command,
                argv=argv,
                cwd=cwd,
                source="canto_observed",
                status="passed" if completed.returncode == 0 else "failed",
                exit_code=completed.returncode,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(exc.stdout or "", encoding="utf-8")
            stderr_path.write_text(exc.stderr or "", encoding="utf-8")
            record = CommandRecord(
                record_id=record_id,
                task_id=task_id,
                command=command,
                argv=argv,
                cwd=cwd,
                source="canto_observed",
                status="failed",
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )
        self.delegation.append_record(task_id, "commands", record)
        return record

    def report(self, task_id: str, command: str, passed: bool | None = None) -> CommandRecord:
        self.delegation.get_task(task_id)
        record = CommandRecord(
            record_id=f"command_{uuid4().hex}",
            task_id=task_id,
            command=command,
            argv=parse_command(command),
            source="executor_reported",
            status="reported",
            exit_code=0 if passed else None,
        )
        self.delegation.append_record(task_id, "commands", record)
        return record

    def waive(self, task_id: str, command: str, reason: str) -> CommandRecord:
        task = self.delegation.get_task(task_id)
        if command not in task.scope.required_commands:
            raise CommandError(f"Command is not required by task scope: {command}")
        if not reason.strip():
            raise CommandError("Command waiver requires a rationale")
        record = CommandRecord(
            record_id=f"command_{uuid4().hex}",
            task_id=task_id,
            command=command,
            argv=parse_command(command),
            source="canto_observed",
            status="waived",
            waiver_reason=reason.strip(),
        )
        self.delegation.append_record(task_id, "commands", record)
        return record

    def unmet_required(self, task_id: str) -> list[str]:
        task = self.delegation.get_task(task_id)
        records = self.delegation.get_records(task_id, "commands")
        satisfied = {
            record["command"]
            for record in records
            if record.get("source") == "canto_observed"
            and record.get("status") in {"passed", "waived"}
            and (
                record.get("status") != "waived"
                or bool(record.get("waiver_reason", "").strip())
            )
        }
        return [
            command for command in task.scope.required_commands if command not in satisfied
        ]
