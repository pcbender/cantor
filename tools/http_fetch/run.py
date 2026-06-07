from __future__ import annotations

import json
import sys
from pathlib import Path

import requests


def main() -> int:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    url = payload["url"]
    response = requests.get(url, timeout=(5, 20), allow_redirects=True)
    print(
        json.dumps(
            {
                "status": "completed",
                "url": url,
                "final_url": response.url,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "text": response.text,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

