from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WORDPRESS_TO_PROCESSWIRE = {
    "post": "page/article",
    "page": "page",
    "category": "taxonomy",
    "tag": "taxonomy",
    "media": "asset",
}


class CrosswalkError(ValueError):
    """Raised when artifact-only crosswalk planning cannot be completed."""


def _concept_names(schema: dict[str, Any]) -> list[str]:
    concepts = []
    for section in ("content_types", "taxonomies", "fields"):
        values = schema.get(section, [])
        if not isinstance(values, list):
            raise CrosswalkError(f"Schema artifact {section} must be a list")
        for value in values:
            if isinstance(value, str):
                concepts.append(value)
            elif isinstance(value, dict) and isinstance(value.get("name"), str):
                concepts.append(value["name"])
    return concepts


def build_crosswalk(
    source_type: str, target_type: str, schema: dict[str, Any]
) -> dict[str, Any]:
    if (source_type, target_type) != ("wordpress", "processwire"):
        raise CrosswalkError(
            f"Unsupported crosswalk: {source_type} -> {target_type}"
        )

    concepts = _concept_names(schema)
    mappings = [
        {"source": source, "target": target}
        for source, target in WORDPRESS_TO_PROCESSWIRE.items()
    ]
    return {
        "source_type": source_type,
        "target_type": target_type,
        "mappings": mappings,
        "unmapped_fields": sorted(
            {concept for concept in concepts if concept not in WORDPRESS_TO_PROCESSWIRE}
        ),
    }


def write_crosswalk(
    source_type: str,
    target_type: str,
    schema_artifact: str | Path,
    artifact_dir: str | Path,
) -> dict[str, Any]:
    path = Path(schema_artifact)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrosswalkError(f"Cannot read schema artifact {path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise CrosswalkError("Schema artifact must be a JSON object")

    crosswalk = build_crosswalk(source_type, target_type, schema)
    output = Path(artifact_dir) / "crosswalk.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(crosswalk, indent=2) + "\n", encoding="utf-8")
    return crosswalk
