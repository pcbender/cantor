from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProcessWireProviderError(ValueError):
    """Raised when a ProcessWire JSON export cannot be inventoried."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProcessWireProviderError(f"Cannot read ProcessWire export {path}: {exc}") from exc


def load_processwire_export(source: str | Path) -> dict[str, list[dict[str, Any]]]:
    path = Path(source)
    if path.is_file():
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ProcessWireProviderError("ProcessWire export must be a JSON object")
    elif path.is_dir():
        data = {
            name: _load_json(path / f"{name}.json")
            for name in ("pages", "templates", "fields")
        }
    else:
        raise ProcessWireProviderError(f"ProcessWire export not found: {source}")

    result = {}
    for name in ("pages", "templates", "fields"):
        value = data.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ProcessWireProviderError(f"ProcessWire export {name} must be a list")
        result[name] = value
    return result


def inventory_processwire(source: str | Path) -> dict[str, dict[str, Any]]:
    exported = load_processwire_export(source)
    pages = [
        {
            "id": page.get("id"),
            "type": page.get("template", "page"),
            "title": page.get("title", ""),
            "slug": page.get("name", ""),
            "status": page.get("status", ""),
            "date": page.get("modified", page.get("created", "")),
            "link": page.get("url", ""),
            "excerpt": page.get("summary", ""),
            "content": page.get("body", ""),
        }
        for page in exported["pages"]
    ]
    return {
        "inventory": {
            "pages": [
                {
                    key: page[key]
                    for key in ("id", "type", "title", "slug", "status", "date", "link")
                }
                for page in pages
            ],
            "images": [],
            "documents": [],
        },
        "content": {"pages": pages},
        "schema": {
            "content_types": exported["templates"],
            "taxonomies": [],
            "relationships": [],
            "fields": exported["fields"],
        },
    }


def write_processwire_artifacts(
    source: str | Path, artifact_dir: str | Path
) -> dict[str, str]:
    artifacts = inventory_processwire(source)
    output = Path(artifact_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (output / f"{name}.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    return {f"{name}.json": f"{name}.json" for name in artifacts}
