from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from canto.core.registry import Registry


class SeedCapabilityError(ValueError):
    """Raised when the checked-in trusted seed catalogue is invalid."""


class SeedCapability(BaseModel):
    skill: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    access: str = Field(min_length=1)
    reviewed: bool


def load_seed_capabilities(
    path: str | Path | None = None,
) -> list[SeedCapability]:
    source = Path(path) if path else Path(__file__).parents[1] / "seed-capabilities.yaml"
    try:
        value = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise SeedCapabilityError("Seed catalogue must use version 1")
        capabilities = [
            SeedCapability.model_validate(item)
            for item in value.get("capabilities", [])
        ]
    except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
        raise SeedCapabilityError(f"Cannot load seed capability catalogue: {exc}") from exc
    if not capabilities:
        raise SeedCapabilityError("Seed capability catalogue cannot be empty")
    identities = [(item.skill, item.provider) for item in capabilities]
    if len(identities) != len(set(identities)):
        raise SeedCapabilityError("Seed capability identities must be unique")
    if any(not item.reviewed for item in capabilities):
        raise SeedCapabilityError("Seed capabilities must be explicitly reviewed")
    return capabilities


def audit_seed_capabilities(registry: Registry) -> list[dict[str, Any]]:
    result = []
    for item in load_seed_capabilities():
        provider = registry.provider_internal(item.skill, item.provider)
        if provider is None:
            raise SeedCapabilityError(
                f"Seed capability is not registered: {item.skill}.{item.provider}"
            )
        result.append(
            {
                **item.model_dump(mode="json"),
                "version": provider.get("version", "0.0.0"),
                "risk_level": int(provider.get("risk_level", 1)),
                "runner": provider.get("runner", {}).get("type"),
                "write_capable": "write" in provider,
            }
        )
    return result
