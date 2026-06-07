from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self, skills_dir: Path, tools_dir: Path):
        self.skills_dir = skills_dir.resolve()
        self.tools_dir = tools_dir.resolve()
        self.skills: dict[str, dict[str, Any]] = {}
        self.providers: dict[tuple[str, str], dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.reload()

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RegistryError(f"Cannot load manifest {path}: {exc}") from exc
        if not isinstance(data, dict) or not data.get("name"):
            raise RegistryError(f"Manifest {path} must be a mapping with a name")
        data["_manifest_path"] = str(path.resolve())
        return data

    def reload(self) -> None:
        skills: dict[str, dict[str, Any]] = {}
        providers: dict[tuple[str, str], dict[str, Any]] = {}
        tools: dict[str, dict[str, Any]] = {}

        if self.skills_dir.exists():
            for path in sorted(self.skills_dir.glob("*/skill.yaml")):
                manifest = self._load_yaml(path)
                skills[manifest["name"]] = manifest
            for path in sorted(self.skills_dir.glob("*/providers/*/provider.yaml")):
                manifest = self._load_yaml(path)
                key = (manifest.get("skill", ""), manifest["name"])
                if key[0] not in skills:
                    raise RegistryError(f"Provider {path} refers to unknown skill {key[0]}")
                providers[key] = manifest

        if self.tools_dir.exists():
            for path in sorted(self.tools_dir.glob("*/tool.yaml")):
                manifest = self._load_yaml(path)
                tools[manifest["name"]] = manifest

        for skill_name, manifest in skills.items():
            declared = set(manifest.get("providers", []))
            installed = {provider for skill, provider in providers if skill == skill_name}
            missing = declared - installed
            if missing:
                raise RegistryError(f"Skill {skill_name} declares missing providers: {sorted(missing)}")

        self.skills, self.providers, self.tools = skills, providers, tools

    @staticmethod
    def _public(manifest: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(manifest)
        result.pop("_manifest_path", None)
        return result

    def snapshot(self) -> dict[str, Any]:
        skill_items = []
        for name, manifest in sorted(self.skills.items()):
            item = self._public(manifest)
            item["providers"] = sorted(provider for skill, provider in self.providers if skill == name)
            skill_items.append(item)
        return {
            "skills": skill_items,
            "providers": [self._public(value) for _, value in sorted(self.providers.items())],
            "tools": [self._public(value) for _, value in sorted(self.tools.items())],
        }

    def get_skill(self, name: str) -> dict[str, Any] | None:
        manifest = self.skills.get(name)
        if not manifest:
            return None
        result = self._public(manifest)
        result["provider_manifests"] = [
            self._public(value)
            for (skill, _), value in sorted(self.providers.items())
            if skill == name
        ]
        return result

    def get_provider(self, skill: str, provider: str) -> dict[str, Any] | None:
        manifest = self.providers.get((skill, provider))
        return self._public(manifest) if manifest else None

    def provider_internal(self, skill: str, provider: str) -> dict[str, Any] | None:
        return self.providers.get((skill, provider))

