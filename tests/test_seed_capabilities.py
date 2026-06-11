from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import canto.cli as cli_module
from canto.core.seed_capabilities import audit_seed_capabilities, load_seed_capabilities


def test_seed_catalogue_is_reviewed_and_registered(runtime):
    _, registry, _, _ = runtime

    catalogue = load_seed_capabilities()
    audited = audit_seed_capabilities(registry)

    assert len(catalogue) == 4
    assert {(item.skill, item.provider) for item in catalogue} == {
        ("check_dependencies", "manifest_dependency_checker"),
        ("source_inventory", "public_html_crawler"),
        ("migration_report", "local_markdown_report"),
        ("managed_json", "local_document"),
    }
    managed_json = next(item for item in audited if item["skill"] == "managed_json")
    assert managed_json["write_capable"] is True
    assert managed_json["access"] == "governed_local_write"
    assert all(item["reviewed"] for item in audited)


def test_seed_capabilities_cli(runtime, monkeypatch):
    settings, registry, store, service = runtime
    monkeypatch.setattr(
        cli_module, "_runtime", lambda: (settings, store, registry, service)
    )

    result = CliRunner().invoke(cli_module.app, ["seed-capabilities"])

    assert result.exit_code == 0
    value = json.loads(result.output)
    assert [item["skill"] for item in value] == [
        "check_dependencies",
        "source_inventory",
        "migration_report",
        "managed_json",
    ]


def test_seed_catalogue_is_in_wheel_source_tree():
    assert (Path(__file__).parents[1] / "canto" / "seed-capabilities.yaml").is_file()
