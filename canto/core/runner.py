from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from canto.config import Settings


class RunnerError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def run_provider(
    provider: dict[str, Any], payload: dict[str, Any], artifact_dir: Path, settings: Settings
) -> dict[str, Any]:
    runner = provider.get("runner", {})
    if runner.get("type") != "python":
        raise RunnerError(f"Unsupported runner type: {runner.get('type')}")

    manifest_path = Path(provider["_manifest_path"])
    entrypoint = (manifest_path.parent / runner.get("entrypoint", "")).resolve()
    if entrypoint.parent != manifest_path.parent.resolve() or not entrypoint.is_file():
        raise RunnerError("Provider entrypoint is missing or outside its registered directory")

    request_path = artifact_dir / "provider_request.json"
    request_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env["CANTO_ARTIFACT_DIR"] = str(artifact_dir.resolve())
    try:
        completed = subprocess.run(
            [sys.executable, str(entrypoint), str(request_path)],
            cwd=str(manifest_path.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.provider_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(f"Provider exceeded {settings.provider_timeout_seconds}s timeout") from exc

    stdout = completed.stdout[-settings.max_provider_output_bytes :]
    stderr = completed.stderr[-settings.max_provider_output_bytes :]
    if completed.returncode != 0:
        raise RunnerError(
            f"Provider exited with status {completed.returncode}",
            {"returncode": completed.returncode, "stdout": stdout, "stderr": stderr},
        )
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RunnerError("Provider stdout was not valid JSON", {"stdout": stdout, "stderr": stderr}) from exc
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise RunnerError("Provider returned an invalid completion result", {"result": result, "stderr": stderr})
    if stderr:
        result["stderr"] = stderr
    return result

