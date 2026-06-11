from __future__ import annotations

from typing import Any


class RunnerContractError(ValueError):
    """Raised when provider runner metadata is not executable."""


RUNNER_TYPES = {"python", "node", "binary", "container"}


def validate_runner_contract(provider: dict[str, Any]) -> None:
    runner = provider.get("runner")
    if runner is None:
        return
    if not isinstance(runner, dict):
        raise RunnerContractError("runner must be a mapping")
    runtime = runner.get("type")
    if runtime not in RUNNER_TYPES:
        raise RunnerContractError(
            f"runner.type must be one of: {', '.join(sorted(RUNNER_TYPES))}"
        )
    if runtime in {"python", "node", "binary"}:
        if not isinstance(runner.get("entrypoint"), str) or not runner["entrypoint"]:
            raise RunnerContractError(f"{runtime} runner requires entrypoint")
        return
    if not isinstance(runner.get("image"), str) or not runner["image"]:
        raise RunnerContractError("container runner requires image")
    command = runner.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise RunnerContractError("container runner requires a string command list")
