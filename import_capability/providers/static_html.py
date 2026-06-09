from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PAGE_EXTENSIONS = {".htm", ".html"}
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".pdf", ".rtf", ".txt"}


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())


def discover_files(directory: str | Path) -> dict[str, list[str]]:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Static HTML source must be a directory: {directory}")

    inventory: dict[str, list[str]] = {
        "pages": [],
        "images": [],
        "documents": [],
    }
    categories = {
        "pages": PAGE_EXTENSIONS,
        "images": IMAGE_EXTENSIONS,
        "documents": DOCUMENT_EXTENSIONS,
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative_path = path.relative_to(root).as_posix()
        extension = path.suffix.lower()
        for category, extensions in categories.items():
            if extension in extensions:
                inventory[category].append(relative_path)
                break
    return inventory


def write_inventory(directory: str | Path, artifact_dir: str | Path) -> dict[str, Any]:
    inventory = discover_files(directory)
    output_path = Path(artifact_dir) / "inventory.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def build_content_inventory(
    directory: str | Path, inventory: dict[str, list[str]] | None = None
) -> dict[str, list[dict[str, str | int]]]:
    root = Path(directory).resolve()
    discovered = inventory or discover_files(root)
    pages = []
    for relative_path in discovered["pages"]:
        page_path = root / relative_path
        parser = TitleParser()
        parser.feed(page_path.read_text(encoding="utf-8", errors="replace"))
        pages.append(
            {
                "path": relative_path,
                "title": parser.title,
                "size": page_path.stat().st_size,
            }
        )
    return {"pages": pages}


def write_content_inventory(
    directory: str | Path,
    artifact_dir: str | Path,
    inventory: dict[str, list[str]] | None = None,
) -> dict[str, list[dict[str, str | int]]]:
    content = build_content_inventory(directory, inventory)
    output_path = Path(artifact_dir) / "content.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return content
