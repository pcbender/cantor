from pathlib import Path

import json

from import_capability.skill import (
    ARTIFACT_NAMES,
    build_migration_plan,
    build_schema,
    generate_artifacts,
    write_migration_plan,
    write_schema,
)


def test_import_capability_skeleton_contains_declared_artifacts():
    root = Path(__file__).resolve().parents[1]

    assert (root / "manifest.yaml").is_file()
    assert (root / "providers").is_dir()
    assert tuple(path.name for path in sorted((root / "artifacts").iterdir())) == tuple(
        sorted(ARTIFACT_NAMES)
    )


def test_static_site_schema_is_empty():
    assert build_schema() == {
        "content_types": [],
        "taxonomies": [],
        "relationships": [],
    }


def test_schema_artifact_is_written(tmp_path):
    schema = write_schema(tmp_path)

    assert json.loads((tmp_path / "schema.json").read_text(encoding="utf-8")) == schema


def test_migration_plan_reports_inventory_counts(tmp_path):
    inventory = {
        "pages": [f"page-{index}.html" for index in range(42)],
        "images": [f"image-{index}.png" for index in range(103)],
        "documents": [],
    }

    plan = write_migration_plan(inventory, tmp_path)

    assert plan == build_migration_plan(inventory)
    assert "Pages discovered: 42" in plan
    assert "Images discovered: 103" in plan
    assert "- ProcessWire" in plan
    assert "- Static Site" in plan
    assert (tmp_path / "migration_plan.md").read_text(encoding="utf-8") == plan


def test_generate_artifacts_writes_complete_planning_set(tmp_path):
    source = tmp_path / "site"
    source.mkdir()
    (source / "index.html").write_text("<title>Home</title>", encoding="utf-8")
    (source / "logo.png").write_bytes(b"png")
    artifacts = tmp_path / "output"

    result = generate_artifacts(source, artifacts)

    generated_names = {
        "inventory.json",
        "content.json",
        "schema.json",
        "migration_plan.md",
    }
    assert result == {name: name for name in generated_names}
    assert {path.name for path in artifacts.iterdir()} == generated_names
    assert "Pages discovered: 1" in (artifacts / "migration_plan.md").read_text(
        encoding="utf-8"
    )
