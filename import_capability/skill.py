from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from import_capability.providers.static_html import (
    write_content_inventory,
    write_inventory,
)


ARTIFACT_NAMES = (
    "inventory.json",
    "content.json",
    "schema.json",
    "migration_plan.md",
    "crosswalk.json",
    "transformed_content.json",
)
STATIC_ARTIFACT_NAMES = (
    "inventory.json",
    "content.json",
    "schema.json",
    "migration_plan.md",
)


def build_schema() -> dict[str, list[object]]:
    return {
        "content_types": [],
        "taxonomies": [],
        "relationships": [],
    }


def write_schema(artifact_dir: str | Path) -> dict[str, list[object]]:
    schema = build_schema()
    output_path = Path(artifact_dir) / "schema.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return schema


def build_migration_plan(inventory: dict[str, list[Any]]) -> str:
    return f"""# Migration Plan

Pages discovered: {len(inventory.get("pages", []))}
Images discovered: {len(inventory.get("images", []))}

Recommended target:
- ProcessWire
- Static Site
"""


def write_migration_plan(
    inventory: dict[str, list[Any]], artifact_dir: str | Path
) -> str:
    plan = build_migration_plan(inventory)
    output_path = Path(artifact_dir) / "migration_plan.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(plan, encoding="utf-8")
    return plan


def generate_artifacts(
    directory: str | Path, artifact_dir: str | Path
) -> dict[str, str]:
    inventory = write_inventory(directory, artifact_dir)
    write_content_inventory(directory, artifact_dir, inventory)
    write_schema(artifact_dir)
    write_migration_plan(inventory, artifact_dir)
    return {name: name for name in STATIC_ARTIFACT_NAMES}
