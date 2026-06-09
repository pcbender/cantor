import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import canto.cli as cli_module
from canto.config import Settings
from canto.core.jobs import JobService
from canto.core.local_registry import Registry
from canto.core.orchestration import (
    CapabilityMatcher,
    Orchestrator,
    PlanStore,
    WorkflowCandidate,
    WorkflowPlanner,
    OrchestrationError,
)
from canto.core.registry import Registry as RuntimeRegistry
from canto.core.state import MemoryStateStore


def install_fixture_capability(home, source, name, description, intents, inputs, outputs):
    capability = source / name
    capability.mkdir()
    (capability / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "version": "1.0.0",
                "description": description,
                "providers": [f"{name}.local"],
                "intents": intents,
                "inputs": inputs,
                "outputs": outputs,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    registry = Registry.local(home)
    registry.install_directory(capability)
    return registry


def installed_match_registry(tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "sources"
    source.mkdir()
    registry = install_fixture_capability(
        home,
        source,
        "wordpress_inventory",
        "Inventory a public WordPress website.",
        ["import_site", "inventory_content"],
        ["website_url"],
        ["inventory.json", "content.json"],
    )
    install_fixture_capability(
        home,
        source,
        "local_files",
        "Inventory a local directory.",
        ["inventory_content"],
        ["local_directory"],
        ["inventory.json"],
    )
    return registry


def test_matcher_ranks_installed_capabilities_deterministically(tmp_path):
    registry = installed_match_registry(tmp_path)

    matches = CapabilityMatcher(registry).discover("import my wordpress site")

    assert [match.name for match in matches] == ["wordpress_inventory"]
    assert matches[0].score > 0
    assert matches[0].reasons == [
        "intent matched: import, site",
        "name matched: wordpress",
        "description matched: wordpress",
    ]


def test_discover_cli_is_read_only_and_prints_ranked_matches(tmp_path, monkeypatch):
    registry = installed_match_registry(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app, ["discover", "import my wordpress site"]
    )

    assert result.exit_code == 0
    assert '"name": "wordpress_inventory"' in result.output
    assert '"score":' in result.output


def test_workflow_candidate_model_has_reviewable_steps():
    candidate = WorkflowCandidate.model_validate(
        {
            "goal": "import my wordpress site",
            "steps": [
                {
                    "capability": "wordpress_inventory",
                    "reason": "intent matched: import, site",
                    "requires": ["website_url"],
                    "produces": ["inventory.json"],
                }
            ],
        }
    )

    assert candidate.model_dump() == {
        "goal": "import my wordpress site",
        "steps": [
            {
                "capability": "wordpress_inventory",
                "reason": "intent matched: import, site",
                "requires": ["website_url"],
                "produces": ["inventory.json"],
            }
        ],
    }


def test_plan_reports_missing_inputs_and_produced_artifacts(tmp_path):
    registry = installed_match_registry(tmp_path)

    preview = WorkflowPlanner(registry).plan("import my wordpress site")

    assert preview.candidate.steps[0].capability == "wordpress_inventory"
    assert preview.missing_inputs == ["website_url"]
    assert preview.produced_artifacts == ["content.json", "inventory.json"]


def test_plan_cli_does_not_execute_and_shows_missing_values(tmp_path, monkeypatch):
    registry = installed_match_registry(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app, ["plan", "import my wordpress site"]
    )

    assert result.exit_code == 0
    assert '"plan_id": "plan_' in result.output
    assert '"status": "draft"' in result.output
    assert '"missing_inputs": [' in result.output
    assert '"website_url"' in result.output
    assert '"produced_artifacts": [' in result.output
    assert registry.store.paths.index_file.is_file()


def test_approved_plan_is_saved_locally_without_execution(tmp_path):
    registry = installed_match_registry(tmp_path)
    store = PlanStore(registry.store.paths.plans)

    plan = Orchestrator(registry, store).create_plan(
        "import my wordpress site", approve=True
    )

    assert plan.status == "approved"
    assert plan.approved_at is not None
    assert store.load(plan.plan_id) == plan


def test_plan_cli_approve_records_approval(tmp_path, monkeypatch):
    registry = installed_match_registry(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(
        cli_module.app,
        ["plan", "import my wordpress site", "--approve"],
    )

    assert result.exit_code == 0
    assert '"status": "approved"' in result.output
    assert list(registry.store.paths.plans.glob("plan_*.json"))


def test_execute_rejects_unapproved_plan(tmp_path):
    registry = installed_match_registry(tmp_path)
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site")

    with pytest.raises(OrchestrationError, match="not approved"):
        orchestrator.execute(plan.plan_id, lambda *args: {})


def test_execute_runs_approved_steps_in_order(tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "sources"
    source.mkdir()
    registry = install_fixture_capability(
        home,
        source,
        "local_demo",
        "Run a local demo task.",
        ["demo_task"],
        [],
        [],
    )
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("demo task", approve=True)
    calls = []

    result = orchestrator.execute(
        plan.plan_id,
        lambda capability, provider, inputs, produces: calls.append(
            (capability, provider, inputs, produces)
        )
        or {},
    )

    assert result.status == "completed"
    assert calls == [("local_demo", "local_demo.local", {}, [])]
    assert orchestrator.store.load(plan.plan_id).status == "completed"


def multi_step_registry(tmp_path, producer_inputs=None):
    home = tmp_path / "home"
    source = tmp_path / "sources"
    source.mkdir()
    registry = install_fixture_capability(
        home,
        source,
        "wordpress_inventory",
        "Inventory wordpress content.",
        ["inventory_content"],
        producer_inputs or [],
        ["inventory.json"],
    )
    install_fixture_capability(
        home,
        source,
        "wordpress_migration_plan",
        "Plan an import for a wordpress site.",
        ["import_site"],
        ["inventory.json"],
        ["migration_plan.md"],
    )
    return registry


def test_planner_connects_declared_artifact_dependencies(tmp_path):
    registry = multi_step_registry(tmp_path, producer_inputs=["website_url"])

    preview = WorkflowPlanner(registry).plan("import my wordpress site")

    assert [step.capability for step in preview.candidate.steps] == [
        "wordpress_inventory",
        "wordpress_migration_plan",
    ]
    assert preview.candidate.steps[0].reason == (
        "produces inventory.json required by wordpress_migration_plan"
    )
    assert preview.missing_inputs == ["website_url"]
    assert preview.produced_artifacts == ["inventory.json", "migration_plan.md"]


def test_executor_fails_when_step_does_not_produce_declared_dependency(tmp_path):
    registry = multi_step_registry(tmp_path)
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site", approve=True)

    with pytest.raises(OrchestrationError, match="did not produce inventory.json"):
        orchestrator.execute(plan.plan_id, lambda *args: {})

    assert orchestrator.store.load(plan.plan_id).status == "failed"


def test_executor_passes_artifact_to_dependent_step(tmp_path):
    registry = multi_step_registry(tmp_path)
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site", approve=True)
    calls = []

    def executor(capability, provider, inputs, produces):
        calls.append((capability, inputs))
        return {output: f"/artifacts/{output}" for output in produces}

    result = orchestrator.execute(plan.plan_id, executor)

    assert result.status == "completed"
    assert calls == [
        ("wordpress_inventory", {}),
        (
            "wordpress_migration_plan",
            {"inventory.json": "/artifacts/inventory.json"},
        ),
    ]


def test_explain_plan_shows_reasons_io_risk_and_missing_values(tmp_path):
    registry = multi_step_registry(tmp_path, producer_inputs=["website_url"])
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site")

    explanation = orchestrator.explain(plan.plan_id)

    assert explanation.status == "draft"
    assert explanation.steps[0].reason == (
        "produces inventory.json required by wordpress_migration_plan"
    )
    assert explanation.steps[0].inputs == ["website_url"]
    assert explanation.steps[0].outputs == ["inventory.json"]
    assert explanation.steps[0].risk == "low"
    assert explanation.steps[0].missing_values == ["website_url"]


def test_explain_cli_does_not_execute(tmp_path, monkeypatch):
    registry = installed_match_registry(tmp_path)
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site")
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)

    result = CliRunner().invoke(cli_module.app, ["explain", plan.plan_id])

    assert result.exit_code == 0
    assert '"reason":' in result.output
    assert '"risk": "low"' in result.output
    assert '"missing_values": [' in result.output
    assert orchestrator.store.load(plan.plan_id).status == "draft"


def executable_discovery_registry(tmp_path):
    home = tmp_path / "home"
    source = tmp_path / "wordpress_inventory"
    provider = source / "skills" / "wordpress_inventory" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "wordpress_inventory",
                "version": "1.0.0",
                "description": "Import and inventory a wordpress site.",
                "skills": ["wordpress_inventory"],
                "providers": ["wordpress_inventory.local"],
                "intents": ["import_site", "inventory_content"],
                "inputs": [],
                "outputs": [],
                "risk": {"level": "low", "requires_approval": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / "skills" / "wordpress_inventory" / "skill.yaml").write_text(
        "name: wordpress_inventory\nproviders:\n  - local\n",
        encoding="utf-8",
    )
    (provider / "provider.yaml").write_text(
        """\
name: local
skill: wordpress_inventory
runner:
  type: python
  entrypoint: run.py
inputs: {}
outputs: {}
dependencies: {}
permissions:
  network_read: false
  network_write: false
  filesystem_write: []
  destructive: false
risk_level: 1
""",
        encoding="utf-8",
    )
    (provider / "run.py").write_text(
        """\
import json
print(json.dumps({"status": "completed", "summary": "Mock capability completed."}))
""",
        encoding="utf-8",
    )
    registry = Registry.local(home)
    registry.install_directory(source)
    return registry


def test_end_to_end_local_orchestration_cli(tmp_path, monkeypatch):
    registry = executable_discovery_registry(tmp_path)
    monkeypatch.setattr(cli_module, "_capability_registry", lambda: registry)
    runner = CliRunner()

    discover_result = runner.invoke(
        cli_module.app, ["discover", "import my wordpress site"]
    )
    assert discover_result.exit_code == 0
    assert '"name": "wordpress_inventory"' in discover_result.output

    draft_result = runner.invoke(
        cli_module.app, ["plan", "import my wordpress site"]
    )
    assert draft_result.exit_code == 0
    assert json.loads(draft_result.output)["status"] == "draft"

    approved_result = runner.invoke(
        cli_module.app, ["plan", "import my wordpress site", "--approve"]
    )
    approved = json.loads(approved_result.output)
    assert approved_result.exit_code == 0
    assert approved["status"] == "approved"

    runtime_root = tmp_path / "runtime"
    (runtime_root / "skills").mkdir(parents=True)
    (runtime_root / "tools").mkdir()
    settings = Settings(
        root_dir=runtime_root,
        redis_url="redis://unused",
        host="127.0.0.1",
        port=8765,
        provider_timeout_seconds=10,
        max_provider_output_bytes=1_048_576,
    )
    runtime_registry = RuntimeRegistry(
        settings.skills_dir,
        settings.tools_dir,
        capability_roots=registry.execution_roots(),
    )
    state = MemoryStateStore()
    service = JobService(settings, runtime_registry, state)
    monkeypatch.setattr(
        cli_module,
        "_runtime",
        lambda: (settings, state, runtime_registry, service),
    )

    execute_result = runner.invoke(cli_module.app, ["execute", approved["plan_id"]])
    assert execute_result.exit_code == 0
    assert json.loads(execute_result.output)["status"] == "completed"

    explain_result = runner.invoke(cli_module.app, ["explain", approved["plan_id"]])
    assert explain_result.exit_code == 0
    explanation = json.loads(explain_result.output)
    assert explanation["status"] == "completed"
    assert explanation["steps"][0]["capability"] == "wordpress_inventory"


def test_plan_store_rejects_invalid_plan_id(tmp_path):
    store = PlanStore(tmp_path / "plans")

    with pytest.raises(OrchestrationError, match="Invalid plan ID"):
        store.load("../../outside")


def test_empty_plan_cannot_be_approved(tmp_path):
    registry = Registry.local(tmp_path / "home")
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))

    with pytest.raises(OrchestrationError, match="no capability steps"):
        orchestrator.create_plan("unknown goal", approve=True)
