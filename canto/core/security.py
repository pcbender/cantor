from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class SensitiveInputError(ValueError):
    pass


REDACTED = "[REDACTED]"


SENSITIVE_PARTS = {
    "access_key",
    "api_key",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}
ENV_REFERENCE = re.compile(r"env:[A-Za-z_][A-Za-z0-9_]*")
VAULT_REFERENCE = re.compile(
    r"vault:[a-z][a-z0-9_-]{0,63}/[a-z][a-z0-9_-]{0,63}"
)


def _is_sensitive_key(key: str) -> bool:
    base = key.removesuffix("_ref")
    return base in SENSITIVE_PARTS or any(
        base.endswith(f"_{part}") for part in SENSITIVE_PARTS
    )


def validate_sensitive_inputs(value: Any, path: str = "inputs") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            normalized = str(key).lower()
            if _is_sensitive_key(normalized):
                if not normalized.endswith("_ref"):
                    raise SensitiveInputError(
                        f"Sensitive input {item_path} must be passed as an *_ref field"
                    )
                if not isinstance(item, str) or not (
                    ENV_REFERENCE.fullmatch(item) or VAULT_REFERENCE.fullmatch(item)
                ):
                    raise SensitiveInputError(
                        f"Sensitive reference {item_path} must use "
                        "env:VARIABLE_NAME or vault:scope/name"
                    )
            else:
                validate_sensitive_inputs(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_sensitive_inputs(item, f"{path}[{index}]")


def redact_sensitive(value: Any, sensitive_values: list[str]) -> Any:
    replacements = sorted(
        {item for item in sensitive_values if item}, key=len, reverse=True
    )
    if isinstance(value, str):
        for item in replacements:
            value = value.replace(item, REDACTED)
        return value
    if isinstance(value, dict):
        return {
            key: redact_sensitive(item, replacements) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item, replacements) for item in value]
    return value


def redact_artifacts(root: Any, sensitive_values: list[str]) -> None:
    path = Path(root)
    replacements = [item.encode() for item in sensitive_values if item]
    if not replacements:
        return
    for artifact in path.rglob("*"):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        content = artifact.read_bytes()
        redacted = content
        for item in replacements:
            redacted = redacted.replace(item, REDACTED.encode())
        if redacted != content:
            artifact.write_bytes(redacted)
