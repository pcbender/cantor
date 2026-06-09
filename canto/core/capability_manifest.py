from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CapabilityManifestError(ValueError):
    """Raised when a capability manifest cannot be parsed or validated."""


class CapabilityRisk(BaseModel):
    level: str = "low"
    requires_approval: bool = False


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    risk: CapabilityRisk = Field(default_factory=CapabilityRisk)
    artifacts: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> CapabilityManifest:
        manifest_path = Path(path)
        try:
            content = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CapabilityManifestError(
                f"Cannot read capability manifest {manifest_path}: {exc}"
            ) from exc
        return cls.from_yaml(content, source=str(manifest_path))

    @classmethod
    def from_yaml(
        cls, content: str, *, source: str = "capability manifest"
    ) -> CapabilityManifest:
        try:
            data: Any = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise CapabilityManifestError(f"Invalid YAML in {source}: {exc}") from exc

        if not isinstance(data, dict):
            raise CapabilityManifestError(f"Invalid {source}: expected a YAML mapping")

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise CapabilityManifestError(f"Invalid {source}: {exc}") from exc


class CapabilityValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CapabilityManifestValidator:
    NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")
    VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    RISK_LEVELS = {"low", "medium", "high"}
    LIST_FIELDS = (
        "skills",
        "providers",
        "tools",
        "intents",
        "inputs",
        "outputs",
        "artifacts",
    )
    TOP_LEVEL_FIELDS = frozenset(CapabilityManifest.model_fields)

    @classmethod
    def validate(
        cls, manifest: CapabilityManifest | dict[str, Any]
    ) -> CapabilityValidationResult:
        if isinstance(manifest, CapabilityManifest):
            data = manifest.model_dump()
        elif isinstance(manifest, dict):
            data = manifest
        else:
            return CapabilityValidationResult(
                valid=False,
                errors=["Manifest must be a mapping"],
            )

        errors: list[str] = []
        warnings = [
            f"Unknown top-level field: {field}"
            for field in sorted(set(data) - cls.TOP_LEVEL_FIELDS)
        ]

        name = data.get("name")
        if not isinstance(name, str) or not cls.NAME_PATTERN.fullmatch(name):
            errors.append(
                "name must be a lowercase snake_case or hyphen-safe package name"
            )

        version = data.get("version")
        if not isinstance(version, str) or not cls.VERSION_PATTERN.fullmatch(version):
            errors.append("version must use semantic version format MAJOR.MINOR.PATCH")

        for field in cls.LIST_FIELDS:
            if field in data and not isinstance(data[field], list):
                errors.append(f"{field} must be a list")

        dependencies = data.get("dependencies", {})
        if not isinstance(dependencies, dict):
            errors.append("dependencies must be a mapping")
        elif "python" in dependencies and not isinstance(dependencies["python"], list):
            errors.append("dependencies.python must be a list")

        risk = data.get("risk", {})
        if not isinstance(risk, dict):
            errors.append("risk must be a mapping")
        else:
            risk_level = risk.get("level", "low")
            if risk_level not in cls.RISK_LEVELS:
                errors.append("risk.level must be one of: low, medium, high")

        return CapabilityValidationResult(
            valid=not errors,
            errors=errors,
            warnings=warnings,
        )

    @classmethod
    def validate_yaml(cls, content: str) -> CapabilityValidationResult:
        try:
            data: Any = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return CapabilityValidationResult(
                valid=False,
                errors=[f"Invalid YAML: {exc}"],
            )
        return cls.validate(data)
