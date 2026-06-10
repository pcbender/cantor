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
    resolve_artifact_inputs,
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


def test_discovery_and_planner_read_new_installed_state(tmp_path):
    home = tmp_path / "home"
    registry = Registry.local(home)
    matcher = CapabilityMatcher(registry)
    planner = WorkflowPlanner(registry)
    assert matcher.discover("import wordpress site") == []

    source = tmp_path / "sources"
    source.mkdir()
    install_fixture_capability(
        home,
        source,
        "wordpress_inventory",
        "Inventory a public WordPress website.",
        ["import_site"],
        [],
        [],
    )

    assert matcher.discover("import wordpress site")[0].name == "wordpress_inventory"
    assert planner.plan("import wordpress site").candidate.steps[0].capability == (
        "wordpress_inventory"
    )


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
                "version": "",
                "skill": "",
                "provider": "",
                "consumes": {},
                "artifact_outputs": {},
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
    assert preview.candidate.steps[0].version == "1.0.0"
    assert preview.candidate.steps[0].skill == "wordpress_inventory"
    assert preview.candidate.steps[0].provider == "local"
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
    assert '"skill": "wordpress_inventory"' in result.output
    assert '"provider": "local"' in result.output
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
        orchestrator._execute(plan.plan_id, lambda *args: {})


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

    result = orchestrator._execute(
        plan.plan_id,
        lambda step, inputs, approval_id: calls.append(
            (
                step.capability,
                f"{step.skill}.{step.provider}",
                inputs,
                step.produces,
            )
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
        orchestrator._execute(plan.plan_id, lambda *args: {})

    assert orchestrator.store.load(plan.plan_id).status == "failed"


def test_executor_passes_artifact_to_dependent_step(tmp_path):
    registry = multi_step_registry(tmp_path)
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))
    plan = orchestrator.create_plan("import my wordpress site", approve=True)
    calls = []

    def executor(step, inputs, approval_id):
        calls.append((step.capability, inputs))
        return {output: f"/artifacts/{output}" for output in step.produces}

    result = orchestrator._execute(plan.plan_id, executor)

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
    assert explanation.steps[0].skill == "wordpress_inventory"
    assert explanation.steps[0].provider == "local"
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
    assert '"skill": "wordpress_inventory"' in result.output
    assert '"provider": "local"' in result.output
    assert '"missing_values": [' in result.output
    assert orchestrator.store.load(plan.plan_id).status == "draft"


def test_planner_prefers_explicit_execution_provider_binding(tmp_path):
    source = tmp_path / "source"
    provider = source / "skills" / "site_inventory" / "providers" / "wordpress"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "wordpress_package",
                "version": "2.0.0",
                "description": "Inventory a wordpress site.",
                "providers": ["legacy_skill.legacy_provider"],
                "intents": ["inventory_site"],
                "execution": {
                    "providers": [
                        {"skill": "site_inventory", "provider": "wordpress"}
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / "skills" / "site_inventory" / "skill.yaml").write_text(
        "name: site_inventory\nproviders:\n  - wordpress\n",
        encoding="utf-8",
    )
    (provider / "provider.yaml").write_text(
        "name: wordpress\nskill: site_inventory\n",
        encoding="utf-8",
    )
    registry = Registry.local(tmp_path / "home")
    registry.install_directory(source)

    plan = Orchestrator(
        registry, PlanStore(registry.store.paths.plans)
    ).create_plan("inventory wordpress site")

    step = plan.candidate.steps[0]
    assert (step.capability, step.version) == ("wordpress_package", "2.0.0")
    assert (step.skill, step.provider) == ("site_inventory", "wordpress")
    assert step.consumes == {}
    assert step.artifact_outputs == {}
    assert plan.capability_providers == {
        "wordpress_package": "site_inventory.wordpress"
    }


def test_artifact_resolver_maps_logical_artifacts_to_provider_inputs():
    step = WorkflowCandidate.model_validate(
        {
            "goal": "report",
            "steps": [
                {
                    "capability": "migration_report",
                    "reason": "test binding",
                    "skill": "migration_report",
                    "provider": "local_markdown_report",
                    "consumes": {"inventory_path": "inventory.json"},
                    "requires": ["inventory.json"],
                    "produces": ["report.md"],
                }
            ],
        }
    ).steps[0]

    resolved = resolve_artifact_inputs(
        step, {"inventory.json": "/artifacts/inventory.json"}
    )

    assert resolved == {"inventory_path": "/artifacts/inventory.json"}


def test_artifact_resolver_reports_missing_artifact():
    step = WorkflowCandidate.model_validate(
        {
            "goal": "report",
            "steps": [
                {
                    "capability": "migration_report",
                    "reason": "test binding",
                    "consumes": {"inventory_path": "inventory.json"},
                }
            ],
        }
    ).steps[0]

    with pytest.raises(
        OrchestrationError,
        match="missing artifact inventory.json for provider input inventory_path",
    ):
        resolve_artifact_inputs(step, {})


def test_planner_rejects_ambiguous_execution_provider_bindings(tmp_path):
    source = tmp_path / "source"
    provider = source / "skills" / "inventory" / "providers" / "local"
    provider.mkdir(parents=True)
    (source / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "inventory_package",
                "version": "1.0.0",
                "description": "Inventory a site.",
                "intents": ["inventory_site"],
                "execution": {
                    "providers": [
                        {"skill": "inventory", "provider": "local"},
                        {"skill": "inventory", "provider": "local"},
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (source / "skills" / "inventory" / "skill.yaml").write_text(
        "name: inventory\nproviders:\n  - local\n", encoding="utf-8"
    )
    (provider / "provider.yaml").write_text(
        "name: local\nskill: inventory\n", encoding="utf-8"
    )
    registry = Registry.local(tmp_path / "home")
    registry.install_directory(source)

    with pytest.raises(OrchestrationError, match="Ambiguous execution provider"):
        WorkflowPlanner(registry).plan("inventory site")


def executable_discovery_registry(tmp_path, approval_required=False):
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
    approval_yaml = "approval_required:\n  - always\n" if approval_required else ""
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
"""
        + approval_yaml,
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


def test_orchestrator_executes_multistep_plan_through_job_service(tmp_path):
    registry = Registry.local(tmp_path / "home")
    sources = tmp_path / "sources"
    sources.mkdir()

    producer = sources / "inventory_package"
    producer_provider = (
        producer / "skills" / "site_inventory" / "providers" / "local"
    )
    producer_provider.mkdir(parents=True)
    (producer / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "inventory_package",
                "version": "1.0.0",
                "description": "Inventory wordpress content.",
                "intents": ["inventory_content"],
                "outputs": ["inventory.json"],
                "execution": {
                    "providers": [
                        {
                            "skill": "site_inventory",
                            "provider": "local",
                            "produces": {"inventory_file": "inventory.json"},
                        }
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (producer / "skills" / "site_inventory" / "skill.yaml").write_text(
        "name: site_inventory\nproviders:\n  - local\n", encoding="utf-8"
    )
    (producer_provider / "provider.yaml").write_text(
        """\
name: local
skill: site_inventory
runner:
  type: python
  entrypoint: run.py
inputs: {}
outputs:
  inventory_file:
    path: inventory.json
    type: file
    format: json
permissions:
  network_read: false
  network_write: false
  filesystem_write: []
  destructive: false
risk_level: 1
""",
        encoding="utf-8",
    )
    (producer_provider / "run.py").write_text(
        """\
import json
import sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
(Path(request["artifact_dir"]) / "inventory.json").write_text("{}", encoding="utf-8")
print(json.dumps({"status": "completed", "summary": "Inventory ready."}))
""",
        encoding="utf-8",
    )
    registry.install_directory(producer)

    consumer = sources / "report_package"
    consumer_provider = (
        consumer / "skills" / "migration_report" / "providers" / "local"
    )
    consumer_provider.mkdir(parents=True)
    (consumer / "canto.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "report_package",
                "version": "1.0.0",
                "description": "Plan a wordpress import.",
                "intents": ["import_site"],
                "inputs": ["inventory.json"],
                "outputs": ["report.md"],
                "execution": {
                    "providers": [
                        {
                            "skill": "migration_report",
                            "provider": "local",
                            "consumes": {"inventory_path": "inventory.json"},
                            "produces": {"report_file": "report.md"},
                        }
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (consumer / "skills" / "migration_report" / "skill.yaml").write_text(
        "name: migration_report\nproviders:\n  - local\n", encoding="utf-8"
    )
    (consumer_provider / "provider.yaml").write_text(
        """\
name: local
skill: migration_report
runner:
  type: python
  entrypoint: run.py
inputs:
  inventory_path:
    type: string
    required: true
outputs:
  report_file:
    path: report.md
    type: file
    format: markdown
permissions:
  network_read: false
  network_write: false
  filesystem_write: []
  destructive: false
risk_level: 1
""",
        encoding="utf-8",
    )
    (consumer_provider / "run.py").write_text(
        """\
import json
import sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
inventory = Path(request["inputs"]["inventory_path"])
(Path(request["artifact_dir"]) / "report.md").write_text(
    f"Inventory: {inventory.name}\\n", encoding="utf-8"
)
print(json.dumps({"status": "completed", "summary": "Report ready."}))
""",
        encoding="utf-8",
    )
    registry.install_directory(consumer)

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
    state = MemoryStateStore()
    service = JobService(
        settings,
        RuntimeRegistry(
            settings.skills_dir,
            settings.tools_dir,
            capability_roots=registry.execution_roots(),
        ),
        state,
    )
    orchestrator = Orchestrator(
        registry,
        PlanStore(registry.store.paths.plans),
        job_service=service,
    )
    plan = orchestrator.create_plan("import my wordpress site", approve=True)

    result = orchestrator.execute(plan.plan_id)

    assert result.status == "completed"
    assert sorted(result.artifacts) == ["inventory.json", "report.md"]
    assert len(state.jobs) == 2
    assert all(
        Path(job["artifact_dir"]).is_relative_to(settings.jobs_dir)
        for job in state.jobs.values()
    )
    assert Path(result.artifacts["report.md"]).read_text(encoding="utf-8") == (
        "Inventory: inventory.json\n"
    )


def test_plan_approval_uses_existing_approval_objects(tmp_path):
    registry = executable_discovery_registry(tmp_path, approval_required=True)
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
    state = MemoryStateStore()
    service = JobService(
        settings,
        RuntimeRegistry(
            settings.skills_dir,
            settings.tools_dir,
            capability_roots=registry.execution_roots(),
        ),
        state,
    )
    orchestrator = Orchestrator(
        registry,
        PlanStore(registry.store.paths.plans),
        job_service=service,
    )

    rejected_plan = orchestrator.create_plan(
        "import my wordpress site", approve=True
    )
    rejected_approval_id = rejected_plan.step_approval_ids["0"]
    pending = state.get_approval(rejected_approval_id)
    assert rejected_plan.status == "waiting_for_approval"
    assert pending["plan_id"] == rejected_plan.plan_id
    assert pending["job_id"] is None
    service.reject(rejected_approval_id, "cantor", "Not approved")

    with pytest.raises(OrchestrationError, match="not approved"):
        orchestrator.execute(rejected_plan.plan_id)
    assert orchestrator.store.load(rejected_plan.plan_id).status == "rejected"

    approved_plan = orchestrator.create_plan(
        "import my wordpress site", approve=True
    )
    approved_approval_id = approved_plan.step_approval_ids["0"]
    service.approve(approved_approval_id, "cantor", "Approved")

    result = orchestrator.execute(approved_plan.plan_id)

    assert result.status == "completed"
    assert len(state.approvals) == 2
    completed_job = next(iter(state.jobs.values()))
    assert completed_job["approval_id"] == approved_approval_id
    assert state.get_approval(approved_approval_id)["job_id"] == completed_job["job_id"]


def test_plan_store_rejects_invalid_plan_id(tmp_path):
    store = PlanStore(tmp_path / "plans")

    with pytest.raises(OrchestrationError, match="Invalid plan ID"):
        store.load("../../outside")


def test_empty_plan_cannot_be_approved(tmp_path):
    registry = Registry.local(tmp_path / "home")
    orchestrator = Orchestrator(registry, PlanStore(registry.store.paths.plans))

    with pytest.raises(OrchestrationError, match="no capability steps"):
        orchestrator.create_plan("unknown goal", approve=True)
