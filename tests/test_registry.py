from canto.api.server import create_app
from canto.core.capability_package import pack_capability
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.registry import Registry as RuntimeRegistry
from canto.models.schemas import JobRequest


def test_registry_loads(runtime):
    settings, registry, store, _ = runtime
    snapshot = registry.snapshot()
    source_inventory = next(item for item in snapshot["skills"] if item["name"] == "source_inventory")
    assert source_inventory["providers"] == ["public_html_crawler"]
    dependency_check = next(item for item in snapshot["skills"] if item["name"] == "check_dependencies")
    assert dependency_check["providers"] == ["manifest_dependency_checker"]
    migration_report = next(item for item in snapshot["skills"] if item["name"] == "migration_report")
    assert migration_report["providers"] == ["local_markdown_report"]

    app = create_app(
        settings,
        store,
        CapabilityRegistry.local(settings.root_dir / "registry-home"),
    )
    registry_route = next(route for route in app.routes if route.path == "/registry")
    response = registry_route.endpoint()
    assert any(item["name"] == "source_inventory" for item in response["skills"])


def test_http_registry_includes_installed_capability_and_matches_cli_runtime(runtime):
    settings, _, store, _ = runtime
    source = settings.root_dir / "http_visible"
    provider = source / "skills" / "http_visible" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: http_visible
version: 1.0.0
skills:
  - http_visible
providers:
  - http_visible.local
risk:
  level: low
""",
        encoding="utf-8",
    )
    (source / "skills" / "http_visible" / "skill.yaml").write_text(
        "name: http_visible\nproviders:\n  - local\n",
        encoding="utf-8",
    )
    (provider / "provider.yaml").write_text(
        "name: local\nskill: http_visible\nrunner:\n  type: python\n  entrypoint: run.py\n",
        encoding="utf-8",
    )
    (provider / "run.py").write_text("VALUE = 1\n", encoding="utf-8")

    package = pack_capability(source, settings.root_dir / "dist")
    capability_registry = CapabilityRegistry.local(
        settings.root_dir / "capability-home"
    )
    capability_registry.install_package(package)

    app = create_app(settings, store, capability_registry)
    response = next(
        route for route in app.routes if route.path == "/registry"
    ).endpoint()
    cli_runtime_view = RuntimeRegistry(
        settings.skills_dir,
        settings.tools_dir,
        capability_roots=capability_registry.execution_roots(),
    ).snapshot()

    assert response == cli_runtime_view
    assert any(item["name"] == "http_visible" for item in response["skills"])
    assert any(
        item["skill"] == "http_visible" and item["name"] == "local"
        for item in response["providers"]
    )


def test_http_registry_refreshes_after_install_and_remove(runtime):
    settings, _, store, _ = runtime
    capability_registry = CapabilityRegistry.local(
        settings.root_dir / "refresh-home"
    )
    app = create_app(settings, store, capability_registry)
    registry_endpoint = next(
        route for route in app.routes if route.path == "/registry"
    ).endpoint
    assert not any(
        item["name"] == "refresh_visible"
        for item in registry_endpoint()["skills"]
    )

    source = settings.root_dir / "refresh_visible"
    provider = source / "skills" / "refresh_visible" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        """\
name: refresh_visible
version: 1.0.0
skills:
  - refresh_visible
providers:
  - refresh_visible.local
risk:
  level: low
""",
        encoding="utf-8",
    )
    (source / "skills" / "refresh_visible" / "skill.yaml").write_text(
        "name: refresh_visible\nproviders:\n  - local\n", encoding="utf-8"
    )
    (provider / "provider.yaml").write_text(
        "name: local\nskill: refresh_visible\n", encoding="utf-8"
    )
    package = pack_capability(source, settings.root_dir / "refresh-dist")

    capability_registry.install_package(package)
    installed_snapshot = registry_endpoint()
    assert any(
        item["name"] == "refresh_visible"
        for item in installed_snapshot["skills"]
    )
    assert any(
        item["skill"] == "refresh_visible" and item["name"] == "local"
        for item in installed_snapshot["providers"]
    )
    assert app.state.service.missing_capability(
        JobRequest(skill="refresh_visible", provider="local")
    ) is None

    capability_registry.remove("refresh_visible")
    removed_snapshot = registry_endpoint()
    assert not any(
        item["name"] == "refresh_visible" for item in removed_snapshot["skills"]
    )
    assert app.state.service.missing_capability(
        JobRequest(skill="refresh_visible", provider="local")
    )["status"] == "missing_skill"


def test_missing_provider_returns_scaffold_suggestion(runtime):
    _, _, _, service = runtime
    from canto.models.schemas import JobRequest

    result = service.missing_capability(
        JobRequest(skill="source_inventory", provider="wordpress_database")
    )
    assert result["status"] == "missing_provider"
    assert result["suggested_action"]["skill"] == "scaffold_provider"
    assert result["suggested_action"]["requires_approval"] is True


def test_missing_skill_returns_scaffold_skill_suggestion(runtime):
    _, _, _, service = runtime
    from canto.models.schemas import JobRequest

    result = service.missing_capability(
        JobRequest(skill="extract_content", provider="readability_html")
    )
    assert result["status"] == "missing_skill"
    assert result["suggested_action"]["skill"] == "scaffold_skill"
    assert result["suggested_action"]["provider"] == "local_scaffolder"
    assert result["suggested_action"]["inputs"] == {"skill": "extract_content"}
    assert result["suggested_action"]["requires_approval"] is True
