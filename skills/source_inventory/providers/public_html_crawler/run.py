from __future__ import annotations

import json
import sys
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def probable_type(url: str, title: str) -> str:
    path = urlparse(url).path.strip("/").lower()
    text = f"{path} {title.lower()}"
    if not path:
        return "home"
    for kind, words in {
        "contact": ("contact",),
        "news": ("news", "blog", "article"),
        "event": ("event", "calendar"),
        "product": ("product", "shop", "store"),
        "about": ("about", "history", "team"),
    }.items():
        if any(word in text for word in words):
            return kind
    return "page"


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inputs = request["inputs"]
    artifact_dir = Path(request["artifact_dir"]).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_url = normalize_url(inputs["source_url"])
    parsed_source = urlparse(source_url)
    if parsed_source.scheme not in {"http", "https"} or not parsed_source.hostname:
        raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
    max_depth = max(0, min(int(inputs.get("max_depth", 3)), 10))
    max_pages = max(1, min(int(inputs.get("max_pages", 100)), 1000))
    include_media = bool(inputs.get("include_media", True))

    session = requests.Session()
    session.headers["User-Agent"] = "Canto/0.1 source-inventory crawler"
    queue = deque([(source_url, 0)])
    queued = {source_url}
    pages = []
    media = set()
    warnings = []
    broken_links = 0
    external_links = set()

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        try:
            response = session.get(url, timeout=(5, 20), allow_redirects=True)
            content_type = response.headers.get("content-type", "")
            status_code = response.status_code
            if status_code >= 400:
                broken_links += 1
            if "text/html" not in content_type.lower():
                warnings.append(f"Skipped non-HTML response: {url} ({content_type or 'unknown type'})")
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            description_tag = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
            description = description_tag.get("content", "").strip() if description_tag else ""
            h1 = [node.get_text(" ", strip=True) for node in soup.find_all("h1")]
            internal = []
            images = []
            for anchor in soup.find_all("a", href=True):
                target = normalize_url(urljoin(response.url, anchor["href"]))
                parsed = urlparse(target)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if parsed.hostname == parsed_source.hostname:
                    internal.append(target)
                    if depth < max_depth and target not in queued:
                        queued.add(target)
                        queue.append((target, depth + 1))
                else:
                    external_links.add(target)
            if include_media:
                for image in soup.find_all("img", src=True):
                    target = normalize_url(urljoin(response.url, image["src"]))
                    images.append(target)
                    media.add(target)
            pages.append(
                {
                    "url": url,
                    "final_url": response.url,
                    "status_code": status_code,
                    "title": title,
                    "meta_description": description,
                    "h1": h1,
                    "links": sorted(set(internal)),
                    "images": sorted(set(images)),
                    "probable_type": probable_type(url, title),
                    "depth": depth,
                }
            )
        except requests.RequestException as exc:
            broken_links += 1
            warnings.append(f"Fetch failed for {url}: {exc}")

    if queue:
        warnings.append(f"Stopped at max_pages={max_pages} with {len(queue)} URLs still queued.")
    inventory = {
        "source_url": source_url,
        "crawled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pages": pages,
        "media": sorted(media),
        "external_links": sorted(external_links),
        "warnings": warnings,
    }
    (artifact_dir / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    groups = Counter(page["probable_type"] for page in pages)
    group_lines = "\n".join(f"- {name}: {count}" for name, count in groups.most_common()) or "- None"
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) or "- None"
    report = f"""# Source Inventory Report

Source: {source_url}

## Summary

- Pages crawled: {len(pages)}
- Images found: {len(media)}
- Broken or failed links: {broken_links}
- External links: {len(external_links)}

## Probable content groups

{group_lines}

## Warnings

{warning_lines}
"""
    (artifact_dir / "report.md").write_text(report, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": f"Crawled {len(pages)} pages and found {len(media)} media references.",
                "artifacts": {"inventory_json": "inventory.json", "report_md": "report.md"},
                "warnings": warnings,
                "needs_human": False,
                "recommended_next_steps": [
                    "Run extract_content once a provider exists.",
                    "Ask Cantor for the target CMS.",
                    "Create a CMS schema mapping provider.",
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

