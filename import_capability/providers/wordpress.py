from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

import requests


class WordPressProviderError(ValueError):
    """Raised when the public WordPress REST API cannot be inventoried."""


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class HttpSession(Protocol):
    def get(self, url: str, *, timeout: tuple[int, int]) -> HttpResponse: ...


def _endpoint(base_url: str, resource: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"wp-json/wp/v2/{resource}")


def _fetch_collection(
    base_url: str, resource: str, session: HttpSession
) -> list[dict[str, Any]]:
    url = _endpoint(base_url, resource)
    try:
        response = session.get(url, timeout=(5, 20))
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise WordPressProviderError(
            f"WordPress REST API unavailable at {url}: {exc}"
        ) from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise WordPressProviderError(
            f"WordPress REST API returned an invalid collection at {url}"
        )
    return data


def _rendered(value: Any) -> str:
    if isinstance(value, dict):
        rendered = value.get("rendered", "")
        return rendered if isinstance(rendered, str) else ""
    return ""


def _normalize_item(item: dict[str, Any], content_type: str) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "type": content_type,
        "title": _rendered(item.get("title")),
        "slug": item.get("slug", ""),
        "status": item.get("status", ""),
        "date": item.get("date", ""),
        "link": item.get("link", ""),
        "excerpt": _rendered(item.get("excerpt")),
        "content": _rendered(item.get("content")),
    }


def inventory_wordpress(
    url: str, session: HttpSession | None = None
) -> dict[str, dict[str, Any]]:
    http = session or requests.Session()
    posts = [_normalize_item(item, "post") for item in _fetch_collection(url, "posts", http)]
    pages = [_normalize_item(item, "page") for item in _fetch_collection(url, "pages", http)]
    content_items = [*posts, *pages]
    return {
        "inventory": {
            "pages": [
                {
                    "id": item["id"],
                    "type": item["type"],
                    "title": item["title"],
                    "slug": item["slug"],
                    "status": item["status"],
                    "date": item["date"],
                    "link": item["link"],
                }
                for item in content_items
            ],
            "images": [],
            "documents": [],
        },
        "content": {"pages": content_items},
        "schema": {
            "content_types": [
                {"name": "post", "source": "wordpress"},
                {"name": "page", "source": "wordpress"},
            ],
            "taxonomies": [],
            "relationships": [],
        },
    }


def write_wordpress_artifacts(
    url: str, artifact_dir: str | Path, session: HttpSession | None = None
) -> dict[str, str]:
    artifacts = inventory_wordpress(url, session)
    output = Path(artifact_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (output / f"{name}.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    return {f"{name}.json": f"{name}.json" for name in artifacts}
