from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from canto.config import Settings
from canto.core.security import redact_sensitive


class RunnerError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def effective_limits(provider: dict[str, Any], settings: Settings) -> dict[str, int]:
    requested = provider.get("limits", {})

    def bounded(name: str, ceiling: int) -> int:
        value = requested.get(name, ceiling)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RunnerError(f"Provider limit {name} must be a positive integer")
        return min(value, ceiling)

    return {
        "wall_seconds": bounded("wall_seconds", settings.provider_timeout_seconds),
        "cpu_seconds": bounded("cpu_seconds", settings.max_provider_cpu_seconds),
        "memory_bytes": bounded("memory_bytes", settings.max_provider_memory_bytes),
        "artifact_bytes": bounded("artifact_bytes", settings.max_job_artifact_bytes),
        "output_bytes": settings.max_provider_output_bytes,
    }


def _validate_egress(provider: dict[str, Any], payload: dict[str, Any]) -> None:
    permissions = provider.get("permissions", {})
    if permissions.get("network_write"):
        raise RunnerError("This runtime cannot enforce network-write egress policy")
    if not permissions.get("network_read"):
        return
    enforcement = provider.get("runner", {}).get("egress_enforcement")
    approved = payload.get("policy", {}).get("approved_domains", [])
    if enforcement != "provider_allowlist":
        raise RunnerError(
            "Network provider must declare runner.egress_enforcement=provider_allowlist"
        )
    if not approved:
        raise RunnerError("Network provider has no approved egress domains")


def _artifact_usage(root: Path) -> int:
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _local_entrypoint(provider: dict[str, Any]) -> tuple[Path, Path]:
    runner = provider["runner"]
    manifest_path = Path(provider["_manifest_path"])
    provider_dir = manifest_path.parent.resolve()
    entrypoint = (provider_dir / runner["entrypoint"]).resolve()
    if entrypoint.parent != provider_dir or not entrypoint.is_file():
        raise RunnerError(
            "Provider entrypoint is missing or outside its registered directory"
        )
    return provider_dir, entrypoint


def _runtime_command(
    provider: dict[str, Any], artifact_dir: Path, limits: dict[str, int]
) -> tuple[list[str], Path, dict[str, str]]:
    runner = provider["runner"]
    runtime = runner["type"]
    env_updates = {"CANTO_ARTIFACT_DIR": str(artifact_dir.resolve())}
    if runtime in {"python", "node", "binary"}:
        provider_dir, entrypoint = _local_entrypoint(provider)
        if runtime == "python":
            command = [sys.executable, str(entrypoint), "/dev/stdin"]
        elif runtime == "node":
            node = shutil.which("node")
            if not node:
                raise RunnerError("Node runtime is unavailable")
            command = [node, str(entrypoint), "/dev/stdin"]
        else:
            if not os.access(entrypoint, os.X_OK):
                raise RunnerError("Binary provider entrypoint is not executable")
            command = [str(entrypoint), "/dev/stdin"]
        return command, provider_dir, env_updates

    requested_runtime = runner.get("runtime")
    candidates = [requested_runtime] if requested_runtime else ["docker", "podman"]
    container_runtime = next(
        (shutil.which(item) for item in candidates if item and shutil.which(item)),
        None,
    )
    if not container_runtime:
        raise RunnerError("No supported local container runtime is available")
    image = runner["image"]
    inspected = subprocess.run(
        [container_runtime, "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        raise RunnerError(
            f"Container image is not available locally: {image}. Canto does not pull images"
        )
    provider_dir = Path(provider["_manifest_path"]).parent.resolve()
    command = [
        container_runtime,
        "run",
        "--rm",
        "-i",
        "--memory",
        str(limits["memory_bytes"]),
        "--cpus",
        "1",
        "-v",
        f"{artifact_dir.resolve()}:/artifacts",
        "-v",
        f"{provider_dir}:/provider:ro",
        "-e",
        "CANTO_ARTIFACT_DIR=/artifacts",
        image,
        *runner["command"],
    ]
    return command, provider_dir, {"CANTO_ARTIFACT_DIR": "/artifacts"}


def run_provider(
    provider: dict[str, Any],
    payload: dict[str, Any],
    artifact_dir: Path,
    settings: Settings,
    sensitive_values: list[str] | None = None,
) -> dict[str, Any]:
    sensitive_values = sensitive_values or []
    limits = effective_limits(provider, settings)
    _validate_egress(provider, payload)
    command, working_dir, env_updates = _runtime_command(
        provider, artifact_dir, limits
    )
    prlimit = shutil.which("prlimit")
    if not prlimit:
        raise RunnerError("prlimit is required to enforce local runtime limits")
    command = [
        prlimit,
        f"--cpu={limits['cpu_seconds']}",
        f"--as={limits['memory_bytes']}",
        f"--fsize={max(limits['artifact_bytes'], limits['output_bytes'])}",
        "--",
        *command,
    ]
    request_payload = json.dumps(payload)
    env = os.environ.copy()
    env.update(env_updates)
    env["CANTO_APPROVED_DOMAINS"] = ",".join(
        payload.get("policy", {}).get("approved_domains", [])
    )
    stdout_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(working_dir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
        )
        try:
            process.communicate(request_payload, timeout=limits["wall_seconds"])
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RunnerError(
                f"Provider exceeded {limits['wall_seconds']}s timeout"
            ) from exc
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_raw = stdout_file.read(limits["output_bytes"] + 1)
        stderr_raw = stderr_file.read(limits["output_bytes"] + 1)
    finally:
        stdout_file.close()
        stderr_file.close()

    stdout = redact_sensitive(
        stdout_raw[-limits["output_bytes"] :], sensitive_values
    )
    stderr = redact_sensitive(
        stderr_raw[-limits["output_bytes"] :], sensitive_values
    )
    if len(stdout_raw) > limits["output_bytes"] or len(stderr_raw) > limits["output_bytes"]:
        raise RunnerError("Provider exceeded captured output limit")
    if process.returncode != 0:
        raise RunnerError(
            f"Provider exited with status {process.returncode}",
            {"returncode": process.returncode, "stdout": stdout, "stderr": stderr},
        )
    artifact_usage = _artifact_usage(artifact_dir)
    if artifact_usage > limits["artifact_bytes"]:
        raise RunnerError(
            f"Provider artifacts exceed {limits['artifact_bytes']} byte limit",
            {"artifact_bytes": artifact_usage},
        )
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RunnerError("Provider stdout was not valid JSON", {"stdout": stdout, "stderr": stderr}) from exc
    result = redact_sensitive(result, sensitive_values)
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise RunnerError("Provider returned an invalid completion result", {"result": result, "stderr": stderr})
    if stderr:
        result["stderr"] = stderr
    return result
