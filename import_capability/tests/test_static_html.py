import json

from import_capability.providers.static_html import (
    build_content_inventory,
    discover_files,
    write_content_inventory,
    write_inventory,
)


def test_static_html_provider_discovers_supported_files(tmp_path):
    source = tmp_path / "site"
    (source / "assets").mkdir(parents=True)
    (source / "docs").mkdir()
    (source / "index.html").write_text("<title>Home</title>", encoding="utf-8")
    (source / "about.htm").write_text("<title>About</title>", encoding="utf-8")
    (source / "assets" / "logo.PNG").write_bytes(b"png")
    (source / "docs" / "guide.pdf").write_bytes(b"pdf")
    (source / "ignored.bin").write_bytes(b"ignored")

    inventory = discover_files(source)

    assert inventory == {
        "pages": ["about.htm", "index.html"],
        "images": ["assets/logo.PNG"],
        "documents": ["docs/guide.pdf"],
    }


def test_static_html_provider_writes_inventory_artifact(tmp_path):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<title>Home</title>", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    inventory = write_inventory(source, artifacts)

    assert json.loads((artifacts / "inventory.json").read_text(encoding="utf-8")) == inventory


def test_content_inventory_records_page_title_path_and_size(tmp_path):
    source = tmp_path / "site"
    source.mkdir()
    html = "<html><head><title>  Example   Page </title></head><body>Text</body></html>"
    (source / "index.html").write_text(html, encoding="utf-8")

    content = build_content_inventory(source)

    assert content == {
        "pages": [
            {
                "path": "index.html",
                "title": "Example Page",
                "size": len(html.encode("utf-8")),
            }
        ]
    }


def test_content_inventory_writes_content_artifact(tmp_path):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<title>Home</title>", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    content = write_content_inventory(source, artifacts)

    assert json.loads((artifacts / "content.json").read_text(encoding="utf-8")) == content
