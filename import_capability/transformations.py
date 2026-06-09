from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TransformationError(ValueError):
    """Raised when local artifact transformation rules are invalid."""


MISSING = object()


def _get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _set_path(value: dict[str, Any], path: str, content: Any) -> None:
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise TransformationError(f"Transformation target conflicts at: {path}")
        current = child
    current[parts[-1]] = content


def transform_content(
    content: dict[str, Any], rules: list[dict[str, str]]
) -> dict[str, Any]:
    pages = content.get("pages", [])
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise TransformationError("Content artifact pages must be a list of objects")

    normalized_rules = []
    for rule in rules:
        source = rule.get("from") if isinstance(rule, dict) else None
        target = rule.get("to") if isinstance(rule, dict) else None
        if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
            raise TransformationError("Each rule requires non-empty from and to paths")
        normalized_rules.append((source, target))

    transformed = []
    skipped = []
    for page in pages:
        output = {"id": page.get("id")}
        for source, target in normalized_rules:
            source_value = _get_path(page, source)
            if source_value is MISSING:
                skipped.append(
                    {
                        "id": page.get("id"),
                        "from": source,
                        "to": target,
                        "reason": "missing source field",
                    }
                )
                continue
            _set_path(output, target, source_value)
        transformed.append(output)
    return {"pages": transformed, "skipped": skipped}


def write_transformed_content(
    content_artifact: str | Path,
    rules: list[dict[str, str]],
    artifact_dir: str | Path,
) -> dict[str, Any]:
    path = Path(content_artifact)
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformationError(f"Cannot read content artifact {path}: {exc}") from exc
    if not isinstance(content, dict):
        raise TransformationError("Content artifact must be a JSON object")

    result = transform_content(content, rules)
    output = Path(artifact_dir) / "transformed_content.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
