import json
from pathlib import Path

from import_capability.providers.processwire import (
    inventory_processwire,
    write_processwire_artifacts,
)


FIXTURES = Path(__file__).parent / "fixtures" / "processwire"


def test_processwire_provider_reads_exported_page_json():
    artifacts = inventory_processwire(FIXTURES / "export.json")

    assert artifacts["inventory"] == {
        "pages": [
            {
                "id": 101,
                "type": "article",
                "title": "Example article",
                "slug": "example-article",
                "status": "published",
                "date": "2026-01-02T03:04:05Z",
                "link": "/articles/example-article/",
            }
        ],
        "images": [],
        "documents": [],
    }
    assert artifacts["content"]["pages"][0]["content"] == "<p>Article body</p>"
    assert artifacts["schema"]["content_types"][0]["name"] == "article"
    assert [field["name"] for field in artifacts["schema"]["fields"]] == [
        "title",
        "summary",
        "body",
    ]


def test_processwire_provider_writes_shared_artifact_shape(tmp_path):
    result = write_processwire_artifacts(FIXTURES / "export.json", tmp_path)

    assert result == {
        "inventory.json": "inventory.json",
        "content.json": "content.json",
        "schema.json": "schema.json",
    }
    for name in result:
        assert isinstance(json.loads((tmp_path / name).read_text(encoding="utf-8")), dict)
