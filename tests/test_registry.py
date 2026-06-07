from canto.api.server import create_app


def test_registry_loads(runtime):
    settings, registry, store, _ = runtime
    snapshot = registry.snapshot()
    source_inventory = next(item for item in snapshot["skills"] if item["name"] == "source_inventory")
    assert source_inventory["providers"] == ["public_html_crawler"]

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

