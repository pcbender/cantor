from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


class ArtifactError(ValueError):
    pass


def contained_path(base: Path, relative: str) -> Path:
    base = base.resolve()
    candidate = (base / relative).resolve()
    if candidate != base and base not in candidate.parents:
        raise ArtifactError(f"Artifact path escapes job directory: {relative}")
    return candidate


def collect_artifacts(artifact_dir: Path, outputs: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = []
    for name, declaration in outputs.items():
        relative = declaration.get("path")
        if not relative:
            continue
        path = contained_path(artifact_dir, relative)
        if not path.is_file():
            raise ArtifactError(f"Declared artifact was not produced: {name} ({relative})")
        mime_type = _mime_type(path)
        artifacts.append(
            {
                "name": name,
                "path": str(path),
                "relative_path": relative,
                "mime_type": mime_type,
                "size_bytes": path.stat().st_size,
            }
        )
    return artifacts


def read_artifact(artifact: dict[str, Any], max_bytes: int = 2_000_000) -> dict[str, Any]:
    path = Path(artifact["path"])
    if not path.is_file():
        raise ArtifactError("Artifact file no longer exists")
    if path.stat().st_size > max_bytes:
        return {**artifact, "content": None, "message": "Artifact is too large to read through the v1 API"}
    mime_type = artifact.get("mime_type", "")
    if not (
        mime_type.startswith("text/")
        or mime_type in {"application/json", "application/yaml", "text/x-python"}
    ):
        return {**artifact, "content": None, "message": "Binary artifact content is not returned in v1"}
    return {**artifact, "content": path.read_text(encoding="utf-8")}


def _mime_type(path: Path) -> str:
    suffix_map = {
        ".json": "application/json",
        ".md": "text/markdown",
        ".py": "text/x-python",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".txt": "text/plain",
    }
    return suffix_map.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
