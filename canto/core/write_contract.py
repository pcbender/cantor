from __future__ import annotations

from typing import Any


class WriteContractError(ValueError):
    """Raised when write-provider metadata is incomplete or inconsistent."""


RECOVERY_MODES = {"rollback", "compensate", "manual"}
REQUIRED_ARTIFACTS = {"change_set", "validation", "verification", "recovery"}


def validate_write_contract(provider: dict[str, Any]) -> None:
    contract = provider.get("write")
    if contract is None:
        return
    if not isinstance(contract, dict):
        raise WriteContractError("write must be a mapping")
    if not isinstance(provider.get("runner"), dict):
        raise WriteContractError("write providers must declare a runner")
    modes = contract.get("modes")
    if not isinstance(modes, list) or not {"dry_run", "live"}.issubset(modes):
        raise WriteContractError("write.modes must include dry_run and live")

    target = contract.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("scope"), str):
        raise WriteContractError("write.target.scope is required")
    inputs = provider.get("inputs", {})
    identity_input = target.get("identity_input")
    if not isinstance(identity_input, str) or identity_input not in inputs:
        raise WriteContractError(
            "write.target.identity_input must name a declared provider input"
        )

    credential_refs = contract.get("credential_refs", [])
    if not isinstance(credential_refs, list) or any(
        not isinstance(name, str) or not name.endswith("_ref") or name not in inputs
        for name in credential_refs
    ):
        raise WriteContractError(
            "write.credential_refs must name declared *_ref inputs"
        )

    artifacts = contract.get("artifacts")
    outputs = provider.get("outputs", {})
    if not isinstance(artifacts, dict):
        raise WriteContractError("write.artifacts must be a mapping")
    missing = REQUIRED_ARTIFACTS - set(artifacts)
    if missing:
        raise WriteContractError(
            f"write.artifacts is missing required entries: {sorted(missing)}"
        )
    undeclared = [name for name in artifacts.values() if name not in outputs]
    if undeclared:
        raise WriteContractError(
            f"write.artifacts references undeclared outputs: {sorted(undeclared)}"
        )

    idempotency = contract.get("idempotency")
    if not isinstance(idempotency, dict) or idempotency.get("required") is not True:
        raise WriteContractError("write.idempotency.required must be true")
    idempotency_input = idempotency.get("input")
    if not isinstance(idempotency_input, str) or idempotency_input not in inputs:
        raise WriteContractError(
            "write.idempotency.input must name a declared provider input"
        )

    recovery = contract.get("recovery")
    if not isinstance(recovery, dict) or recovery.get("mode") not in RECOVERY_MODES:
        raise WriteContractError(
            "write.recovery.mode must be rollback, compensate, or manual"
        )
    permissions = provider.get("permissions", {})
    if "production_access" not in permissions:
        raise WriteContractError(
            "write providers must declare permissions.production_access"
        )
    if "destructive" not in permissions:
        raise WriteContractError("write providers must declare permissions.destructive")
