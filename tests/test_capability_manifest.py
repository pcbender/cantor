from pathlib import Path

import pytest

from canto.core.capability_manifest import (
    CapabilityManifest,
    CapabilityManifestError,
    CapabilityManifestValidator,
)

FIXTURES = Path(__file__).parent / "fixtures" / "capabilities"


def test_loads_minimal_manifest_with_defaults():
    manifest = CapabilityManifest.load(FIXTURES / "minimal_valid.yaml")

    assert manifest.name == "source_inventory"
    assert manifest.version == "1.0.0"
    assert manifest.skills == []
    assert manifest.providers == []
    assert manifest.tools == []
    assert manifest.intents == []
    assert manifest.inputs == []
    assert manifest.outputs == []
    assert manifest.artifacts == []
    assert manifest.dependencies == {}
    assert manifest.risk.level == "low"
    assert manifest.risk.requires_approval is False


def test_loads_full_manifest():
    manifest = CapabilityManifest.load(FIXTURES / "full_valid.yaml")

    assert manifest.description == (
        "Inventory a website and produce migration planning artifacts."
    )
    assert manifest.skills == ["source_inventory"]
    assert manifest.providers == ["source_inventory.public_html_crawler"]
    assert manifest.tools == []
    assert manifest.intents == ["inventory_content"]
    assert manifest.inputs == ["website_url"]
    assert manifest.outputs == ["inventory.json", "report.md"]
    assert manifest.dependencies == {"python": ["requests", "beautifulsoup4"]}
    assert manifest.risk.level == "low"
    assert manifest.risk.requires_approval is False
    assert manifest.artifacts == ["inventory.json", "report.md"]


@pytest.mark.parametrize(
    ("fixture_name", "missing_field"),
    [("missing_name.yaml", "name"), ("missing_version.yaml", "version")],
)
def test_rejects_missing_required_fields(fixture_name, missing_field):
    with pytest.raises(CapabilityManifestError, match=missing_field):
        CapabilityManifest.load(FIXTURES / fixture_name)


def test_rejects_invalid_yaml():
    with pytest.raises(CapabilityManifestError, match="Invalid YAML"):
        CapabilityManifest.from_yaml("name: [unterminated")


@pytest.mark.parametrize("name", ["SourceInventory", "source inventory", "source.inventory"])
def test_validator_rejects_invalid_name(name):
    result = CapabilityManifestValidator.validate({"name": name, "version": "1.0.0"})

    assert result.valid is False
    assert any("name" in error for error in result.errors)


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.0-beta"])
def test_validator_rejects_invalid_version(version):
    result = CapabilityManifestValidator.validate(
        {"name": "source_inventory", "version": version}
    )

    assert result.valid is False
    assert any("version" in error for error in result.errors)


def test_validator_rejects_invalid_risk_level():
    result = CapabilityManifestValidator.validate_yaml(
        (FIXTURES / "invalid_risk_level.yaml").read_text(encoding="utf-8")
    )

    assert result.valid is False
    assert result.errors == ["risk.level must be one of: low, medium, high"]


@pytest.mark.parametrize("field", ["skills", "providers", "tools", "artifacts"])
def test_validator_rejects_invalid_list_fields(field):
    result = CapabilityManifestValidator.validate(
        {"name": "source_inventory", "version": "1.0.0", field: "not-a-list"}
    )

    assert result.valid is False
    assert f"{field} must be a list" in result.errors


def test_validator_rejects_invalid_python_dependencies():
    result = CapabilityManifestValidator.validate(
        {
            "name": "source_inventory",
            "version": "1.0.0",
            "dependencies": {"python": "requests"},
        }
    )

    assert result.valid is False
    assert "dependencies.python must be a list" in result.errors


def test_validator_warns_about_unknown_top_level_fields():
    manifest = CapabilityManifest.load(FIXTURES / "unknown_top_level_field.yaml")

    result = CapabilityManifestValidator.validate(manifest)

    assert result.valid is True
    assert result.errors == []
    assert result.warnings == ["Unknown top-level field: future_option"]


def test_existing_minimal_manifest_defaults_intent_metadata():
    manifest = CapabilityManifest.load(FIXTURES / "minimal_valid.yaml")

    assert manifest.intents == []
    assert manifest.inputs == []
    assert manifest.outputs == []


def test_execution_provider_bindings_are_optional():
    manifest = CapabilityManifest.load(FIXTURES / "minimal_valid.yaml")

    assert manifest.execution is None


def test_loads_and_validates_execution_provider_bindings():
    manifest = CapabilityManifest.load(FIXTURES / "execution_providers_valid.yaml")
    result = CapabilityManifestValidator.validate(manifest)

    assert result.valid is True
    binding = manifest.execution.providers[0]
    assert (binding.skill, binding.provider) == (
        "site_inventory",
        "wordpress_crawler",
    )
    assert binding.consumes == {"website_url": "website_url"}
    assert binding.produces == {"inventory.json": "inventory.json"}


@pytest.mark.parametrize(
    ("execution", "error"),
    [
        ({"providers": [{}]}, "execution.providers[0].skill"),
        (
            {"providers": [{"skill": "site_inventory"}]},
            "execution.providers[0].provider",
        ),
        ({"providers": "invalid"}, "execution.providers must be a list"),
        (
            {
                "providers": [
                    {
                        "skill": "site_inventory",
                        "provider": "local",
                        "consumes": ["inventory.json"],
                    }
                ]
            },
            "execution.providers[0].consumes must be a string mapping",
        ),
    ],
)
def test_validator_rejects_malformed_execution_provider_bindings(execution, error):
    result = CapabilityManifestValidator.validate(
        {
            "name": "site_inventory",
            "version": "1.0.0",
            "execution": execution,
        }
    )

    assert result.valid is False
    assert any(error in item for item in result.errors)


@pytest.mark.parametrize("field", ["intents", "inputs", "outputs"])
def test_validator_rejects_invalid_intent_metadata_lists(field):
    result = CapabilityManifestValidator.validate(
        {"name": "source_inventory", "version": "1.0.0", field: "invalid"}
    )

    assert result.valid is False
    assert f"{field} must be a list" in result.errors
