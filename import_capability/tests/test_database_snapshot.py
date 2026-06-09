import json
from pathlib import Path

from import_capability.providers.database_snapshot import (
    inventory_sql_dump,
    write_database_artifacts,
)


FIXTURES = Path(__file__).parent / "fixtures" / "database"


def test_database_snapshot_detects_wordpress_tables_without_execution():
    artifacts = inventory_sql_dump(FIXTURES / "wordpress.sql")

    assert artifacts["inventory"]["tables"] == ["wp_posts", "wp_options"]
    assert artifacts["inventory"]["detected_cms"] == "wordpress"
    assert [column["name"] for column in artifacts["schema"]["tables"][0]["columns"]] == [
        "ID",
        "post_title",
        "post_status",
    ]


def test_database_snapshot_detects_processwire_and_writes_artifacts(tmp_path):
    result = write_database_artifacts(FIXTURES / "processwire.sql", tmp_path)

    assert result == {
        "inventory.json": "inventory.json",
        "schema.json": "schema.json",
        "migration_plan.md": "migration_plan.md",
    }
    inventory = json.loads((tmp_path / "inventory.json").read_text(encoding="utf-8"))
    assert inventory["detected_cms"] == "processwire"
    assert inventory["tables"] == ["pages", "templates", "fields"]
    assert "Likely CMS: processwire" in (tmp_path / "migration_plan.md").read_text(
        encoding="utf-8"
    )
