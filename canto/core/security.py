from __future__ import annotations

import re
from typing import Any


class SensitiveInputError(ValueError):
    pass


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
                if not isinstance(item, str) or not ENV_REFERENCE.fullmatch(item):
                    raise SensitiveInputError(
                        f"Sensitive reference {item_path} must use env:VARIABLE_NAME"
                    )
            else:
                validate_sensitive_inputs(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_sensitive_inputs(item, f"{path}[{index}]")
