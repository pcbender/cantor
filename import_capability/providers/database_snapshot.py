from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CREATE_TABLE_PATTERN = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|([A-Za-z0-9_$]+))\s*\((.*?)\)\s*[^;]*;",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_PATTERN = re.compile(r"^\s*(?:`([^`]+)`|([A-Za-z0-9_$]+))\s+([^,]+)")


class DatabaseSnapshotError(ValueError):
    """Raised when an SQL snapshot cannot be inventoried."""


def _split_definitions(body: str) -> list[str]:
    definitions = []
    current = []
    depth = 0
    for character in body:
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        if character == "," and depth == 0:
            definitions.append("".join(current))
            current = []
        else:
            current.append(character)
    if current:
        definitions.append("".join(current))
    return definitions


def detect_cms(table_names: list[str]) -> str | None:
    lowered = {name.lower() for name in table_names}
    if {"wp_posts", "wp_options"}.issubset(lowered) or any(
        name.endswith("_posts") and name.startswith("wp_") for name in lowered
    ):
        return "wordpress"
    processwire_core = {"pages", "templates", "fields"}
    if processwire_core.issubset(lowered):
        return "processwire"
    return None


def inventory_sql_dump(dump: str | Path) -> dict[str, Any]:
    path = Path(dump)
    if not path.is_file():
        raise DatabaseSnapshotError(f"SQL dump not found: {dump}")
    try:
        sql = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DatabaseSnapshotError(f"Cannot read SQL dump {dump}: {exc}") from exc

    tables = []
    for match in CREATE_TABLE_PATTERN.finditer(sql):
        name = match.group(1) or match.group(2)
        columns = []
        for definition in _split_definitions(match.group(3)):
            column = COLUMN_PATTERN.match(definition)
            if not column:
                continue
            column_name = column.group(1) or column.group(2)
            if column_name.upper() in {
                "PRIMARY",
                "UNIQUE",
                "KEY",
                "CONSTRAINT",
                "FOREIGN",
                "CHECK",
            }:
                continue
            columns.append({"name": column_name, "definition": column.group(3).strip()})
        tables.append({"name": name, "columns": columns})

    table_names = [table["name"] for table in tables]
    cms = detect_cms(table_names)
    return {
        "inventory": {
            "pages": [],
            "images": [],
            "documents": [],
            "tables": table_names,
            "detected_cms": cms,
        },
        "schema": {
            "content_types": [],
            "taxonomies": [],
            "relationships": [],
            "tables": tables,
        },
    }


def database_migration_plan(inventory: dict[str, Any]) -> str:
    detected = inventory.get("detected_cms") or "unknown"
    return f"""# Migration Plan

Database tables discovered: {len(inventory.get("tables", []))}
Likely CMS: {detected}

Next steps:
- Review the detected schema.
- Define artifact-only crosswalk mappings.
- Do not execute this SQL dump.
"""


def write_database_artifacts(
    dump: str | Path, artifact_dir: str | Path
) -> dict[str, str]:
    artifacts = inventory_sql_dump(dump)
    output = Path(artifact_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("inventory", "schema"):
        (output / f"{name}.json").write_text(
            json.dumps(artifacts[name], indent=2) + "\n", encoding="utf-8"
        )
    (output / "migration_plan.md").write_text(
        database_migration_plan(artifacts["inventory"]), encoding="utf-8"
    )
    return {
        "inventory.json": "inventory.json",
        "schema.json": "schema.json",
        "migration_plan.md": "migration_plan.md",
    }
