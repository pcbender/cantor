from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from canto.core.cli_executor import (
    WorkerAuthError,
    adapter_for_profile,
    available_for_profile,
)
from canto.core.delegation import DelegationError, DelegationService
from canto.models.delegation import ExecutorProfile


class ExecutorProfileError(DelegationError):
    pass


BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "manual": {
        "name": "Manual executor",
        "harness": "manual",
        "launch_mode": "manual",
        "permissions": {"command_enforcement": "manual_unverified"},
    },
    "codex-cloud": {
        "name": "Codex cloud executor",
        "harness": "codex_cli",
        "executable": "codex",
        "launch_mode": "canto",
        "model_provider": "openai",
        "permissions": {"command_enforcement": "canto_observed"},
    },
    "codex-ollama": {
        "name": "Codex local Ollama executor",
        "harness": "codex_cli",
        "executable": "codex",
        "launch_mode": "canto",
        "model_provider": "ollama",
        "configuration": {"extra_args": ["--oss", "--local-provider", "ollama"]},
        "permissions": {"command_enforcement": "canto_observed"},
    },
    "claude-subscription": {
        "name": "Claude subscription executor",
        "harness": "claude_cli",
        "executable": "claude",
        "launch_mode": "canto",
        "model_provider": "anthropic",
        "permissions": {"command_enforcement": "canto_observed"},
    },
    "gemini-subscription": {
        "name": "Gemini subscription executor",
        "harness": "gemini_cli",
        "executable": "gemini",
        "launch_mode": "canto",
        "model_provider": "google",
        "permissions": {"command_enforcement": "canto_observed"},
    },
}

SECRET_KEYS = {"api_key", "authorization", "credential", "password", "secret", "token"}


def _merge(*values: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if not value:
            continue
        for key, item in value.items():
            if isinstance(item, dict) and isinstance(result.get(key), dict):
                result[key] = _merge(result[key], item)
            elif item is not None:
                result[key] = item
    return result


def _reject_secrets(value: Any, path: str = "profile") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SECRET_KEYS:
                raise ExecutorProfileError(f"Credentials are not allowed in executor profiles: {path}.{key}")
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")


class ExecutorProfileManager:
    def __init__(self, delegation: DelegationService, config_file: Path):
        self.delegation = delegation
        self.config_file = Path(config_file)

    def _load_config(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return {}
        try:
            loaded = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ExecutorProfileError(f"Cannot load executor presets {self.config_file}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ExecutorProfileError("Executor preset file must contain a mapping")
        return loaded

    def _write_config(self, value: dict[str, Any]) -> None:
        _reject_secrets(value)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            yaml.safe_dump(value, sort_keys=True),
            encoding="utf-8",
        )

    def presets(self) -> dict[str, dict[str, Any]]:
        values = {key: dict(value) for key, value in BUILTIN_PRESETS.items()}
        loaded = self._load_config()
        if not isinstance(loaded, dict) or not isinstance(loaded.get("presets", {}), dict):
            raise ExecutorProfileError("Executor preset file must contain a presets mapping")
        for key, value in loaded.get("presets", {}).items():
            if not isinstance(value, dict):
                raise ExecutorProfileError(f"Executor preset must be a mapping: {key}")
            _reject_secrets(value, f"presets.{key}")
            values[key] = _merge(values.get(key), value)
        return values

    def profile_pools(self) -> dict[str, list[str]]:
        loaded = self._load_config()
        raw_pools = loaded.get("profile_pools", {})
        if not isinstance(raw_pools, dict):
            raise ExecutorProfileError("Executor preset file profile_pools must be a mapping")
        pools: dict[str, list[str]] = {}
        for key, value in raw_pools.items():
            if isinstance(value, list):
                profiles = value
            elif isinstance(value, dict):
                _reject_secrets(value, f"profile_pools.{key}")
                profiles = value.get("profiles", [])
            else:
                raise ExecutorProfileError(f"Profile pool must be a mapping or list: {key}")
            if not isinstance(profiles, list) or not all(
                isinstance(item, str) and item for item in profiles
            ):
                raise ExecutorProfileError(
                    f"Profile pool must contain a profiles list of strings: {key}"
                )
            pools[key] = list(dict.fromkeys(profiles))
        return pools

    def resolve_profile_pool(self, pool_id: str) -> list[str]:
        try:
            return self.profile_pools()[pool_id]
        except KeyError as exc:
            raise ExecutorProfileError(f"Executor profile pool not found: {pool_id}") from exc

    def save_profile_pool(self, pool_id: str, profiles: list[str]) -> dict[str, list[str]]:
        if not pool_id:
            raise ExecutorProfileError("Executor profile pool name is required")
        if not profiles:
            raise ExecutorProfileError("Executor profile pool requires at least one profile")
        for profile in profiles:
            try:
                self.delegation.get_executor_profile(profile)
            except DelegationError as exc:
                raise ExecutorProfileError(
                    f"Executor profile not found for pool {pool_id}: {profile}"
                ) from exc
        loaded = self._load_config()
        pools = loaded.get("profile_pools", {})
        if not isinstance(pools, dict):
            raise ExecutorProfileError("Executor preset file profile_pools must be a mapping")
        pools[pool_id] = {"profiles": list(dict.fromkeys(profiles))}
        loaded["profile_pools"] = pools
        self._write_config(loaded)
        return self.profile_pools()

    def resolve(
        self,
        executor_id: str,
        *,
        preset: str | None = None,
        task_override: dict[str, Any] | None = None,
        cli_override: dict[str, Any] | None = None,
    ) -> ExecutorProfile:
        preset_values = self.presets().get(preset or "", {})
        try:
            saved = self.delegation.get_executor_profile(executor_id).model_dump(mode="json")
        except DelegationError:
            saved = {}
        values = _merge(
            {"executor_id": executor_id, "name": executor_id, "harness": "manual", "launch_mode": "manual"},
            preset_values,
            saved,
            task_override,
            cli_override,
            {"executor_id": executor_id},
        )
        _reject_secrets(values)
        try:
            return ExecutorProfile.model_validate(values)
        except ValidationError as exc:
            raise ExecutorProfileError(f"Invalid executor profile: {exc}") from exc

    def save(self, profile: ExecutorProfile) -> ExecutorProfile:
        _reject_secrets(profile.model_dump(mode="json"))
        return self.delegation.set_executor_profile(profile)

    def check(
        self, profile: ExecutorProfile, *, subscription_auth: bool = False
    ) -> dict[str, Any]:
        if profile.harness == "manual":
            return {"available": True, "detail": "Manual executor requires no executable."}
        try:
            resolved = available_for_profile(profile)
        except WorkerAuthError as exc:
            return {"available": False, "detail": str(exc)}
        except DelegationError as exc:
            return {"available": False, "detail": str(exc)}
        if subscription_auth:
            try:
                adapter_for_profile(profile).assert_auth(profile)
            except WorkerAuthError as exc:
                return {"available": False, "detail": str(exc)}
        if profile.model_provider != "ollama":
            return {"available": True, "detail": str(Path(resolved).resolve())}
        ollama = shutil.which("ollama")
        if not ollama:
            return {"available": False, "detail": "Ollama executable is unavailable; install and start Ollama locally."}
        try:
            completed = subprocess.run(
                [ollama, "list"], text=True, capture_output=True, check=False, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "detail": f"Cannot query local Ollama runtime: {exc}"}
        if completed.returncode:
            detail = completed.stderr.strip() or "ollama list failed"
            return {"available": False, "detail": f"Local Ollama runtime unavailable: {detail}"}
        if profile.model:
            installed = {
                line.split()[0].split(":latest")[0]
                for line in completed.stdout.splitlines()[1:]
                if line.split()
            }
            requested = profile.model.split(":latest")[0]
            if requested not in installed:
                return {
                    "available": False,
                    "detail": f"Ollama model is not installed locally: {profile.model}. Canto will not pull it automatically.",
                }
        return {
            "available": True,
            "detail": f"Codex CLI and local Ollama are available ({Path(ollama).resolve()}).",
        }
