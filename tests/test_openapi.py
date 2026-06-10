import json
from pathlib import Path

from canto.api.server import app


def test_checked_in_openapi_matches_fastapi_app():
    checked_in = json.loads(
        (Path(__file__).parents[1] / "docs" / "openapi.json").read_text(
            encoding="utf-8"
        )
    )

    assert checked_in == app.openapi()
