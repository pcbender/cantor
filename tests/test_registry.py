from canto.api.server import create_app


def test_registry_loads(runtime):
    settings, registry, store, _ = runtime
    snapshot = registry.snapshot()
    source_inventory = next(item for item in snapshot["skills"] if item["name"] == "source_inventory")
    assert source_inventory["providers"] == ["public_html_crawler"]
    dependency_check = next(item for item in snapshot["skills"] if item["name"] == "check_dependencies")
    assert dependency_check["providers"] == ["manifest_dependency_checker"]
    migration_report = next(item for item in snapshot["skills"] if item["name"] == "migration_report")
    assert migration_report["providers"] == ["local_markdown_report"]

    app = create_app(settings, store)
    registry_route = next(route for route in app.routes if route.path == "/registry")
    response = registry_route.endpoint()
    assert any(item["name"] == "source_inventory" for item in response["skills"])


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
