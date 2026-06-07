from __future__ import annotations

import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup


def main() -> int:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    soup = BeautifulSoup(payload["html"], "html.parser")
    description = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    print(
        json.dumps(
            {
                "status": "completed",
                "title": soup.title.get_text(" ", strip=True) if soup.title else "",
                "meta_description": description.get("content", "").strip() if description else "",
                "h1": [node.get_text(" ", strip=True) for node in soup.find_all("h1")],
                "links": [node["href"] for node in soup.find_all("a", href=True)],
                "images": [node["src"] for node in soup.find_all("img", src=True)],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

