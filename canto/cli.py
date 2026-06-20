from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
import uvicorn

from canto.api.server import create_app
from canto.config import get_settings
from canto.core.capability_manifest import CapabilityManifestValidator
from canto.core.capability_package import (
    CapabilityPackageError,
    pack_capability,
    validate_package,
)
from canto.core.capability_scaffold import (
    CapabilityScaffoldError,
    scaffold_capability_structure,
)
from canto.core.credentials import CredentialError, CredentialVault
from canto.core.ai_endpoints import AIEndpointError, AIEndpointService
from canto.core.ai_discovery import ModelCatalogService, ModelDiscoveryError
from canto.core.ai_reconciliation import (
    LocalModelReconciliationService,
    ModelCatalogMaintenanceError,
    ModelCatalogMaintenanceService,
    ModelReconciliationError,
)
from canto.core.ai_selection import (
    WorkerSelectionError,
    WorkerSelectionService,
    compose_worker_policy,
)
from canto.core.cli_worker_selection import (
    CliWorkerSelectionError,
    CliWorkerSelectionService,
    http_transport_allowed,
)
from canto.core.ai_assignment import AIWorkerAssignmentService, WorkerAssignmentError
from canto.core.ai_worker import APIWorkerHarness
from canto.core.ai_probe import (
    APIWorkerProbeRunner,
    CodingWorkerProbeService,
    LocalModelProbeQueue,
    WorkerProbeError,
)
from canto.core.ai_metadata import ModelMetadataError, ModelMetadataService
from canto.core.ai_readiness import ai_worker_readiness_checks
from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import (
    DelegationWorkspaceService,
    WorkspaceError,
    inspect_repository,
)
from canto.core.delegation_executor import DelegationCliExecutor, ExecutorError
from canto.core.delegation_artifacts import (
    ArtifactCaptureError,
    DelegationArtifactService,
)
from canto.core.delegation_review import DelegationReviewService, ReviewError
from canto.core.delegation_promotion import DelegationPromotionService, PromotionError
from canto.core.delegation_commands import CommandError, DelegationCommandService
from canto.core.delegation_pool import DelegationPoolService
from canto.core.delegation_queue import DelegationPromotionQueue, QueueError
from canto.core.delegation_timeline import DelegationTimelineService
from canto.core.delegation_dashboard import DelegationDashboardService
from canto.core.delegation_comparison import (
    ComparisonError,
    DelegationComparisonService,
)
from canto.core.executor_profiles import ExecutorProfileError, ExecutorProfileManager
from canto.core.delegation_review_summary import (
    DelegationReviewSummaryService,
    ReviewSummaryError,
)
from canto.core.delegation_conflicts import DelegationConflictService
from canto.core.delegation_demo import DelegationDemoError, run_delegation_demo
from canto.core.ai_worker_demo import run_ai_worker_pool_demo
from canto.core.jobs import JobError, JobService
from canto.core.memory import MemoryService, MemoryServiceError
from canto.core.local_registry import (
    LocalRegistryError,
    Registry as CapabilityRegistry,
)
from canto.core.orchestration import (
    CapabilityMatcher,
    OrchestrationError,
    Orchestrator,
    PlanStore,
)
from canto.core.registry import Registry
from canto.core.repository import (
    RepositoryConfigError,
    RepositoryDoctorCheck,
    doctor_repository,
    initialize_repository,
    load_repository,
    load_repository_policy,
    load_repository_worker_policy,
)
from canto.core.seed_capabilities import SeedCapabilityError, audit_seed_capabilities
from canto.core.state import SqliteStateStore
from canto.core.state import RedisStateStore
from canto.core.state_migration import StateMigrationError, migrate_legacy_state
from canto.models.schemas import JobRequest, Policy
from canto.models.delegation import (
    DelegationMessage,
    DelegationScope,
    DelegationTask,
    ExecutorProfile,
    ExecutorSession,
    DelegationVariant,
)

app = typer.Typer(help="Canto local orchestration broker")
skill_app = typer.Typer(help="Inspect skills")
provider_app = typer.Typer(help="Inspect providers")
job_app = typer.Typer(help="Inspect jobs")
capability_app = typer.Typer(help="Manage capability manifests")
credential_app = typer.Typer(help="Manage local encrypted credentials")
delegate_app = typer.Typer(help="Coordinate delegated executor workspaces")
repo_app = typer.Typer(help="Bootstrap and inspect repository-local Canto intent")
demo_app = typer.Typer(help="Run isolated local Canto demonstrations")
ai_app = typer.Typer(help="Configure and inspect governed AI Workers")
ai_endpoint_app = typer.Typer(help="Manage AI provider endpoints")
ai_model_app = typer.Typer(help="Discover and inspect exact provider models")
ai_pool_app = typer.Typer(help="Select and explain governed AI Workers")
ai_usage_app = typer.Typer(help="Inspect AI Worker usage and endpoint health")
delegate_compare_app = typer.Typer(help="Create and inspect prompt comparisons")
delegate_profile_app = typer.Typer(help="Manage local executor profiles")
memory_app = typer.Typer(help="Manage governed Canto memory")
memory_project_app = typer.Typer(help="Manage memory project identity")
app.add_typer(skill_app, name="skill")
app.add_typer(provider_app, name="provider")
app.add_typer(job_app, name="job")
app.add_typer(capability_app, name="capability")
app.add_typer(credential_app, name="credential")
app.add_typer(delegate_app, name="delegate")
app.add_typer(repo_app, name="repo")
app.add_typer(demo_app, name="demo")
app.add_typer(ai_app, name="ai")
ai_app.add_typer(ai_endpoint_app, name="endpoint")
ai_app.add_typer(ai_model_app, name="model")
ai_app.add_typer(ai_pool_app, name="pool")
ai_app.add_typer(ai_usage_app, name="usage")
delegate_app.add_typer(delegate_compare_app, name="compare")
delegate_app.add_typer(delegate_profile_app, name="profile")
app.add_typer(memory_app, name="memory")
memory_app.add_typer(memory_project_app, name="project")


def _credential_vault() -> CredentialVault:
    return CredentialVault.local()


def _memory_service(*, read_only: bool = False) -> MemoryService:
    registry = _capability_registry()
    return MemoryService(
        SqliteStateStore(registry.store.paths.state_file, read_only=read_only)
    )


def _memory_error(exc: Exception) -> None:
    raise typer.BadParameter(str(exc)) from exc


def _ai_endpoint_service() -> AIEndpointService:
    registry = _capability_registry()
    return AIEndpointService(
        SqliteStateStore(registry.store.paths.state_file),
        _credential_vault(),
        registry.store.paths.config / "ai-endpoints.yaml",
    )


def _ai_catalog_service() -> ModelCatalogService:
    endpoint_service = _ai_endpoint_service()
    return ModelCatalogService(endpoint_service.store, endpoint_service)


def _ai_readiness_store() -> SqliteStateStore:
    registry = _capability_registry()
    return SqliteStateStore(registry.store.paths.state_file, read_only=True)


def _ai_reconciliation_service() -> LocalModelReconciliationService:
    endpoint_service = _ai_endpoint_service()
    return LocalModelReconciliationService(endpoint_service.store, endpoint_service)


def _ai_catalog_maintenance_service() -> ModelCatalogMaintenanceService:
    return ModelCatalogMaintenanceService(_ai_endpoint_service().store)


def _ai_probe_service() -> CodingWorkerProbeService:
    endpoints = _ai_endpoint_service()
    catalog = ModelCatalogService(endpoints.store, endpoints)
    return CodingWorkerProbeService(
        endpoints.store,
        catalog,
        APIWorkerProbeRunner(catalog, endpoints),
        _capability_registry().store.paths.root / "work" / "ai-probes",
    )


def _ai_metadata_service() -> ModelMetadataService:
    endpoints = _ai_endpoint_service()
    return ModelMetadataService(
        endpoints.store, ModelCatalogService(endpoints.store, endpoints)
    )


def _ai_selection_service() -> WorkerSelectionService:
    return WorkerSelectionService(_ai_endpoint_service().store)


def _ai_assignment_service() -> AIWorkerAssignmentService:
    delegation, workspaces = _delegation_runtime()
    endpoints = _ai_endpoint_service()
    return AIWorkerAssignmentService(
        delegation,
        workspaces,
        endpoints,
        ModelCatalogService(delegation.store, endpoints),
        WorkerSelectionService(delegation.store),
        APIWorkerHarness(),
    )


def _runtime() -> tuple:
    settings = get_settings()
    capability_registry = _capability_registry()
    store = SqliteStateStore(
        capability_registry.store.paths.state_file
    )
    registry = Registry(
        settings.skills_dir,
        settings.tools_dir,
        capability_registry=capability_registry,
    )
    return settings, store, registry, JobService(settings, registry, store)


def _capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry.local()


def _delegation_runtime(
    *, read_only: bool = False
) -> tuple[DelegationService, DelegationWorkspaceService]:
    registry = _capability_registry()
    store = SqliteStateStore(
        registry.store.paths.state_file,
        read_only=read_only,
    )
    service = DelegationService(store)
    workspaces = DelegationWorkspaceService(
        service, registry.store.paths.root / "work" / "delegations"
    )
    return service, workspaces


def _orchestrator(job_service: JobService | None = None) -> Orchestrator:
    registry = _capability_registry()
    store = (
        job_service.store
        if job_service is not None
        else SqliteStateStore(registry.store.paths.state_file)
    )
    return Orchestrator(
        registry,
        PlanStore(store),
        job_service=job_service,
    )


def _print(value: Any) -> None:
    typer.echo(json.dumps(value, indent=2))


def _parse_inputs(items: list[str]) -> dict[str, Any]:
    result = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"Input must use key=value: {item}")
        key, value = item.split("=", 1)
        try:
            result[key] = json.loads(value)
        except json.JSONDecodeError:
            result[key] = value
    return result


def _delegation_error(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(1) from exc


def _profile_manager() -> ExecutorProfileManager:
    service, _ = _delegation_runtime()
    return ExecutorProfileManager(
        service, _capability_registry().store.paths.config / "executors.yaml"
    )


@repo_app.command("init")
def repo_init(
    repository: Path = typer.Option(Path("."), "--repository", "--repo"),
) -> None:
    """Bootstrap non-secret Canto intent in a canonical Git repository."""
    try:
        config = initialize_repository(repository)
    except RepositoryConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(config.model_dump(mode="json"))


@repo_app.command("show")
def repo_show(
    repository: Path = typer.Option(Path("."), "--repository", "--repo"),
) -> None:
    """Inspect repository-local Canto identity from this directory or a child."""
    try:
        config = load_repository(repository)
    except RepositoryConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(config.model_dump(mode="json"))


@repo_app.command("doctor")
def repo_doctor(
    repository: Path = typer.Option(Path("."), "--repository", "--repo"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Verify repository identity, agent instructions, and Git readiness."""
    try:
        result = doctor_repository(repository)
        worker_policy = load_repository_worker_policy(repository)
        try:
            ai_checks = ai_worker_readiness_checks(
                _ai_readiness_store(), worker_policy
            )
        except (OSError, sqlite3.Error) as exc:
            required = bool(
                worker_policy.allowed_endpoints
                or worker_policy.allowed_models
                or worker_policy.allowed_providers
            )
            ai_checks = [
                RepositoryDoctorCheck(
                    name="ai_worker_state",
                    valid=False,
                    detail=f"global AI state is unavailable: {exc}",
                    severity="error" if required else "warning",
                )
            ]
        result = result.model_copy(
            update={
                "checks": result.checks + ai_checks,
                "valid": result.valid
                and all(check.valid or check.severity == "warning" for check in ai_checks),
            }
        )
    except RepositoryConfigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_output:
        _print(result.model_dump(mode="json"))
    else:
        typer.echo(f"Repository: {result.repository}")
        for check in result.checks:
            label = "OK" if check.valid else "WARN" if check.severity == "warning" else "FAIL"
            typer.echo(f"{label} {check.name}: {check.detail}")
    if not result.valid:
        raise typer.Exit(1)


@demo_app.command("delegation")
def demo_delegation(
    mode: str = typer.Option("scripted", "--mode"),
    model: str | None = typer.Option(None, "--model"),
    promote: bool = typer.Option(False, "--promote"),
    keep: bool = typer.Option(False, "--keep"),
) -> None:
    """Run an isolated delegated-executor workflow; scripted mode is offline."""
    if mode not in {"scripted", "cloud", "ollama"}:
        raise typer.BadParameter("Mode must be scripted, cloud, or ollama")
    if mode != "scripted":
        typer.echo(
            f"Warning: {mode} mode invokes a configured external model runtime and may consume quota/resources.",
            err=True,
        )
    try:
        result = run_delegation_demo(
            mode=mode, model=model, promote=promote, keep=keep
        )
    except DelegationDemoError as exc:
        _delegation_error(exc)
    _print(result.model_dump(mode="json"))


@delegate_app.command("create")
def delegate_create(
    title: str,
    repository: Path = typer.Option(Path("."), "--repository", "--repo"),
    allow: list[str] = typer.Option(..., "--allow"),
    deny: list[str] = typer.Option([], "--deny"),
    instruction: str = typer.Option("", "--instruction"),
) -> None:
    """Create a draft delegation task for a bounded Git repository scope."""
    try:
        service, _ = _delegation_runtime()
        repo_config = load_repository(repository)
        policy = load_repository_policy(repository)
        if policy.allowed_paths:
            outside_policy = [
                path
                for path in allow
                if not any(
                    path == root or path.startswith(f"{root}/")
                    for root in policy.allowed_paths
                )
            ]
            if outside_policy:
                raise RepositoryConfigError(
                    "Task paths are outside repository policy: "
                    + ", ".join(outside_policy)
                )
        task = DelegationTask(
            task_id=f"task_{uuid4().hex}",
            title=title,
            repository=inspect_repository(repo_config.canonical_path),
            scope=DelegationScope(
                allowed_paths=allow,
                denied_paths=sorted(set(policy.denied_paths) | set(deny)),
                allowed_commands=policy.allowed_commands,
                required_commands=policy.required_commands,
                allow_network=False,
                allow_secrets=False,
            ),
            instructions=instruction,
            created_by="cli",
        )
        service.create_task(task)
    except (DelegationError, WorkspaceError, RepositoryConfigError) as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("assign")
def delegate_assign(
    task_id: str,
    executor_id: str = typer.Option("manual", "--executor"),
) -> None:
    """Assign a task to a registered executor profile."""
    try:
        service, _ = _delegation_runtime()
        try:
            profile = service.get_executor_profile(executor_id)
        except DelegationError:
            profile = service.set_executor_profile(
                ExecutorProfile(
                    executor_id=executor_id,
                    name=executor_id,
                    harness="manual",
                    launch_mode="manual",
                )
            )
        task = service.transition(
            task_id, "assigned", updates={"executor_id": executor_id}
        )
        service.append_record(
            task_id,
            "messages",
            DelegationMessage(
                message_id=f"message_{uuid4().hex}",
                task_id=task_id,
                sender="orchestrator",
                kind="assignment",
                body=task.instructions or task.title,
            ),
        )
    except DelegationError as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("prepare")
def delegate_prepare(task_id: str) -> None:
    """Create the assigned task's bounded sparse Git worktree."""
    try:
        _, workspaces = _delegation_runtime()
        workspace = workspaces.prepare(task_id)
    except (DelegationError, WorkspaceError) as exc:
        _delegation_error(exc)
    _print(workspace.model_dump(mode="json"))


@delegate_app.command("start")
def delegate_start(task_id: str) -> None:
    """Mark a prepared manual executor session as working."""
    try:
        service, _ = _delegation_runtime()
        task = service.get_task(task_id)
        if not task.executor_id:
            raise DelegationError("Delegation task has no assigned executor")
        session = ExecutorSession(
            session_id=f"session_{uuid4().hex}",
            task_id=task_id,
            executor_id=task.executor_id,
            status="running",
            enforcement="manual_unverified",
            started_at=task.updated_at,
        )
        service.append_record(task_id, "sessions", session)
        task = service.transition(
            task_id,
            "executor_working",
            details={"session_id": session.session_id, "enforcement": session.enforcement},
        )
    except DelegationError as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


def _executor_message(task_id: str, kind: str, body: str) -> None:
    service, _ = _delegation_runtime()
    service.append_record(
        task_id,
        "messages",
        DelegationMessage(
            message_id=f"message_{uuid4().hex}",
            task_id=task_id,
            sender="executor",
            kind=kind,
            body=body,
        ),
    )


@delegate_app.command("message")
def delegate_message(task_id: str, body: str) -> None:
    """Record executor-reported progress without treating it as observed evidence."""
    try:
        _executor_message(task_id, "progress", body)
    except DelegationError as exc:
        _delegation_error(exc)
    typer.echo("Message recorded.")


@delegate_app.command("block")
def delegate_block(task_id: str, reason: str) -> None:
    """Record a blocker and pause a working manual executor."""
    try:
        _executor_message(task_id, "blocker", reason)
        task = _delegation_runtime()[0].transition(task_id, "executor_blocked")
    except DelegationError as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("resume")
def delegate_resume(task_id: str) -> None:
    """Return a blocked or revision-requested task to executor work."""
    try:
        task = _delegation_runtime()[0].transition(task_id, "executor_working")
    except DelegationError as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("done")
def delegate_done(
    task_id: str,
    summary: str = typer.Option("Ready for review", "--summary"),
) -> None:
    """Record the executor's unverified done-for-review assertion."""
    try:
        _executor_message(task_id, "done", summary)
        task = _delegation_runtime()[0].transition(task_id, "executor_done")
    except DelegationError as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("show")
def delegate_show(task_id: str) -> None:
    """Show a delegation task and its durable manual workflow records."""
    try:
        service, workspaces = _delegation_runtime()
        task = service.get_task(task_id)
        value = task.model_dump(mode="json")
        value["messages"] = service.get_records(task_id, "messages")
        value["sessions"] = DelegationCliExecutor(
            service, workspaces
        ).projected_sessions(task_id)
    except DelegationError as exc:
        _delegation_error(exc)
    _print(value)


@delegate_app.command("list")
def delegate_list() -> None:
    """List local delegation tasks."""
    try:
        tasks = _delegation_runtime()[0].list_tasks()
    except DelegationError as exc:
        _delegation_error(exc)
    _print([task.model_dump(mode="json") for task in tasks])


@delegate_app.command("add-codex")
def delegate_add_codex(
    executor_id: str,
    executable: str = typer.Option("codex", "--executable"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Register a local Codex CLI executor profile without credentials."""
    try:
        service, workspaces = _delegation_runtime()
        profile = ExecutorProfile(
            executor_id=executor_id,
            name=executor_id,
            harness="codex_cli",
            executable=executable,
            model=model,
            launch_mode="canto",
            permissions={"command_enforcement": "canto_observed"},
        )
        DelegationCliExecutor(service, workspaces).available(profile)
        service.set_executor_profile(profile)
    except (DelegationError, ExecutorError) as exc:
        _delegation_error(exc)
    _print(profile.model_dump(mode="json"))


@delegate_profile_app.command("list")
def delegate_profile_list() -> None:
    """List saved profiles and available preset names."""
    try:
        manager = _profile_manager()
        value = {
            "presets": sorted(manager.presets()),
            "profiles": [
                profile.model_dump(mode="json")
                for profile in manager.delegation.list_executor_profiles()
            ],
        }
    except ExecutorProfileError as exc:
        _delegation_error(exc)
    _print(value)


@delegate_profile_app.command("show")
def delegate_profile_show(executor_id: str) -> None:
    """Show one saved executor profile."""
    try:
        profile = _profile_manager().delegation.get_executor_profile(executor_id)
    except DelegationError as exc:
        _delegation_error(exc)
    _print(profile.model_dump(mode="json"))


@delegate_profile_app.command("save")
def delegate_profile_save(
    executor_id: str,
    preset: str = typer.Option("manual", "--preset"),
    executable: str | None = typer.Option(None, "--executable"),
    model: str | None = typer.Option(None, "--model"),
    extra_args: list[str] = typer.Option([], "--extra-arg"),
) -> None:
    """Resolve and save a credential-free named executor profile."""
    try:
        manager = _profile_manager()
        if preset not in manager.presets():
            raise ExecutorProfileError(f"Executor preset not found: {preset}")
        override: dict[str, Any] = {"executable": executable, "model": model}
        if extra_args:
            override["configuration"] = {"extra_args": extra_args}
        profile = manager.resolve(executor_id, preset=preset, cli_override=override)
        check = manager.check(profile)
        if not check["available"]:
            raise ExecutorProfileError(check["detail"])
        manager.save(profile)
    except (DelegationError, ExecutorProfileError) as exc:
        _delegation_error(exc)
    _print(profile.model_dump(mode="json"))


@delegate_profile_app.command("check")
def delegate_profile_check(
    executor_id: str,
    subscription_auth: bool = typer.Option(False, "--subscription-auth"),
) -> None:
    """Check a saved profile without mutating task state."""
    try:
        manager = _profile_manager()
        profile = manager.delegation.get_executor_profile(executor_id)
        value = {
            "profile": profile.model_dump(mode="json"),
            **manager.check(profile, subscription_auth=subscription_auth),
        }
    except (DelegationError, ExecutorProfileError) as exc:
        _delegation_error(exc)
    _print(value)


@delegate_app.command("launch")
def delegate_launch(
    task_id: str,
    variant: str | None = typer.Option(None, "--variant"),
    instruction: str | None = typer.Option(None, "--instruction"),
) -> None:
    """Launch the assigned Canto CLI profile in its prepared worktree."""
    try:
        service, workspaces = _delegation_runtime()
        launch = DelegationCliExecutor(service, workspaces).launch(
            task_id, variant_name=variant, supplement=instruction
        )
    except (DelegationError, ExecutorError) as exc:
        _delegation_error(exc)
    _print(launch.model_dump(mode="json"))


@delegate_compare_app.command("create")
def delegate_compare_create(
    task_id: str,
    variants: list[str] = typer.Option(..., "--variant"),
) -> None:
    """Create isolated sibling tasks from NAME=SUPPLEMENT variant values."""
    try:
        parsed = []
        for value in variants:
            name, separator, supplement = value.partition("=")
            if not separator:
                raise ComparisonError("Variant must use NAME=SUPPLEMENT syntax")
            parsed.append(DelegationVariant(name=name, prompt_supplement=supplement))
        service, _ = _delegation_runtime()
        tasks = DelegationComparisonService(service).create_variants(task_id, parsed)
    except (DelegationError, ComparisonError) as exc:
        _delegation_error(exc)
    _print([task.model_dump(mode="json") for task in tasks])


@delegate_compare_app.command("show")
def delegate_compare_show(comparison_id: str) -> None:
    """Compare immutable evidence from sibling task variants."""
    try:
        service, _ = _delegation_runtime()
        comparison = DelegationComparisonService(service).compare(comparison_id)
    except (DelegationError, ComparisonError) as exc:
        _delegation_error(exc)
    _print(comparison.model_dump(mode="json"))


@delegate_app.command("capture")
def delegate_capture(task_id: str) -> None:
    """Capture an immutable review artifact revision from executor changes."""
    try:
        service, workspaces = _delegation_runtime()
        result = DelegationArtifactService(service, workspaces).capture(task_id)
    except (DelegationError, ArtifactCaptureError) as exc:
        _delegation_error(exc)
    _print(result.model_dump(mode="json"))


@delegate_app.command("accept")
def delegate_accept(
    task_id: str,
    reviewer: str = typer.Option("cantor", "--reviewer"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Accept the latest checksum-bound result revision."""
    try:
        service, workspaces = _delegation_runtime()
        review = DelegationReviewService(service, workspaces).accept(
            task_id, reviewer, note
        )
    except (DelegationError, ReviewError) as exc:
        _delegation_error(exc)
    _print(review.model_dump(mode="json"))


@delegate_app.command("review-summary")
def delegate_review_summary(
    task_id: str,
    revision: int | None = typer.Option(None, "--revision"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show immutable review evidence and readiness without changing state."""
    try:
        service, workspaces = _delegation_runtime()
        summary = DelegationReviewSummaryService(service, workspaces).summarize(
            task_id, revision
        )
    except (DelegationError, ReviewSummaryError) as exc:
        _delegation_error(exc)
    if json_output:
        _print(summary.model_dump(mode="json"))
        return
    typer.echo(f"Task: {summary.task_id} ({summary.status})")
    typer.echo(f"Result: revision {summary.result_revision}")
    typer.echo(f"Executor: {summary.executor_id or '-'}; variant: {summary.prompt_variant or '-'}")
    typer.echo(f"Patch: +{summary.patch_additions} -{summary.patch_deletions}")
    typer.echo("Changed: " + (", ".join(summary.changed_files) or "none"))
    typer.echo(f"Checksums: {'valid' if summary.artifact_checksums_valid else 'invalid'}")
    typer.echo(f"Acceptance ready: {str(summary.acceptance_ready).lower()}")
    typer.echo(f"Promotion ready: {str(summary.promotion_ready).lower()}")
    for blocker in summary.blockers:
        typer.echo(f"BLOCKED: {blocker}")


@delegate_app.command("conflict")
def delegate_conflict(
    task_id: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Explain delegation conflicts and safe recovery options without acting."""
    try:
        service, workspaces = _delegation_runtime()
        report = DelegationConflictService(service, workspaces).explain(task_id)
    except DelegationError as exc:
        _delegation_error(exc)
    if json_output:
        _print(report.model_dump(mode="json"))
        return
    if not report.blockers:
        typer.echo(f"No active conflicts for {task_id}.")
        return
    for blocker in report.blockers:
        typer.echo(f"{blocker.code}: {blocker.message}")
        typer.echo("Safe actions: " + ", ".join(blocker.safe_actions))


@delegate_app.command("revise")
def delegate_revise(
    task_id: str,
    note: str = typer.Option(..., "--note"),
    reviewer: str = typer.Option("cantor", "--reviewer"),
) -> None:
    """Request another executor revision while preserving prior evidence."""
    try:
        service, workspaces = _delegation_runtime()
        review = DelegationReviewService(service, workspaces).request_revision(
            task_id, reviewer, note
        )
    except (DelegationError, ReviewError) as exc:
        _delegation_error(exc)
    if review is None:
        _print(
            {
                "task_id": task_id,
                "status": "revision_requested",
                "result_revision": None,
                "note": note,
            }
        )
    else:
        _print(review.model_dump(mode="json"))


@delegate_app.command("reject")
def delegate_reject(
    task_id: str,
    note: str = typer.Option(..., "--note"),
    reviewer: str = typer.Option("cantor", "--reviewer"),
) -> None:
    """Reject the latest result revision."""
    try:
        service, workspaces = _delegation_runtime()
        review = DelegationReviewService(service, workspaces).reject(
            task_id, reviewer, note
        )
    except (DelegationError, ReviewError) as exc:
        _delegation_error(exc)
    _print(review.model_dump(mode="json"))


@delegate_app.command("promote")
def delegate_promote(
    task_id: str,
    decided_by: str = typer.Option("cantor", "--decided-by"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Apply the exact accepted patch to the clean canonical repository."""
    try:
        service, workspaces = _delegation_runtime()
        result = DelegationPromotionService(service, workspaces).promote(
            task_id, decided_by, note
        )
    except (DelegationError, PromotionError) as exc:
        _delegation_error(exc)
    _print(result.model_dump(mode="json"))


@delegate_app.command("run-command")
def delegate_run_command(
    task_id: str,
    command: str,
    cwd: str = typer.Option(".", "--cwd"),
) -> None:
    """Run and record an allowed command in the delegation workspace."""
    try:
        service, workspaces = _delegation_runtime()
        record = DelegationCommandService(service, workspaces).run(
            task_id, command, cwd
        )
    except (DelegationError, CommandError) as exc:
        _delegation_error(exc)
    _print(record.model_dump(mode="json"))


@delegate_app.command("report-command")
def delegate_report_command(task_id: str, command: str) -> None:
    """Record a manual executor command assertion as unverified."""
    try:
        service, workspaces = _delegation_runtime()
        record = DelegationCommandService(service, workspaces).report(
            task_id, command
        )
    except (DelegationError, CommandError) as exc:
        _delegation_error(exc)
    _print(record.model_dump(mode="json"))


@delegate_app.command("waive-command")
def delegate_waive_command(
    task_id: str,
    command: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    """Waive a required command with an explicit orchestrator rationale."""
    try:
        service, workspaces = _delegation_runtime()
        record = DelegationCommandService(service, workspaces).waive(
            task_id, command, reason
        )
    except (DelegationError, CommandError) as exc:
        _delegation_error(exc)
    _print(record.model_dump(mode="json"))


@delegate_app.command("pool")
def delegate_pool() -> None:
    """Show executor availability and active assignments without scheduling."""
    try:
        service, _ = _delegation_runtime(read_only=True)
        _print(
            [
                entry.model_dump(mode="json")
                for entry in DelegationPoolService(service).executors()
            ]
        )
    except (OSError, sqlite3.Error) as exc:
        _delegation_error(
            RuntimeError(f"Cannot read Canto state for delegate pool: {exc}")
        )


@delegate_app.command("status")
def delegate_status(active: bool = typer.Option(False, "--active")) -> None:
    """Show durable delegation task status across parallel workspaces."""
    try:
        service, _ = _delegation_runtime(read_only=True)
        _print(
            [
                item.model_dump(mode="json")
                for item in DelegationPoolService(service).tasks(active_only=active)
            ]
        )
    except (OSError, sqlite3.Error) as exc:
        _delegation_error(
            RuntimeError(f"Cannot read Canto state for delegate status: {exc}")
        )


@delegate_app.command("wait")
def delegate_wait(
    task_id: str,
    timeout: float = typer.Option(1800.0, "--timeout", min=0.1),
    interval: float = typer.Option(2.0, "--interval", min=0.1),
) -> None:
    """Wait for a working Worker task to reach completion or need attention."""
    deadline = time.monotonic() + timeout
    waiting_statuses = {"executor_working", "promoting"}
    try:
        service, _ = _delegation_runtime(read_only=True)
        while True:
            task = service.get_task(task_id)
            if task.status not in waiting_statuses:
                _print(task.model_dump(mode="json"))
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                typer.echo(
                    f"Error: Timed out waiting for {task_id}; current status is {task.status}",
                    err=True,
                )
                raise typer.Exit(1)
            time.sleep(min(interval, remaining))
    except (DelegationError, OSError, sqlite3.Error) as exc:
        _delegation_error(RuntimeError(f"Cannot wait for delegation task: {exc}"))


@delegate_app.command("queue-add")
def delegate_queue_add(
    task_id: str,
    enqueued_by: str = typer.Option("cantor", "--enqueued-by"),
) -> None:
    """Add an accepted result to the explicit local promotion queue."""
    try:
        service, workspaces = _delegation_runtime()
        entry = DelegationPromotionQueue(service, workspaces).enqueue(
            task_id, enqueued_by
        )
    except (DelegationError, QueueError) as exc:
        _delegation_error(exc)
    _print(entry.model_dump(mode="json"))


@delegate_app.command("queue")
def delegate_queue() -> None:
    """Show pending promotion order and detected blockers."""
    service, workspaces = _delegation_runtime()
    _print(
        [
            entry.model_dump(mode="json")
            for entry in DelegationPromotionQueue(service, workspaces).list()
        ]
    )


@delegate_app.command("queue-promote")
def delegate_queue_promote(
    task_id: str,
    decided_by: str = typer.Option("cantor", "--decided-by"),
) -> None:
    """Explicitly promote one unblocked queued result; never runs automatically."""
    try:
        service, workspaces = _delegation_runtime()
        result = DelegationPromotionQueue(service, workspaces).promote(
            task_id, decided_by
        )
    except (DelegationError, QueueError, PromotionError) as exc:
        _delegation_error(exc)
    _print(result.model_dump(mode="json"))


@delegate_app.command("timeline")
def delegate_timeline(task_id: str) -> None:
    """Show the restart-safe durable delegation timeline."""
    try:
        service, _ = _delegation_runtime()
        items = DelegationTimelineService(service).timeline(task_id)
    except DelegationError as exc:
        _delegation_error(exc)
    _print([item.model_dump(mode="json") for item in items])


@delegate_app.command("dashboard")
def delegate_dashboard(
    task_id: str | None = typer.Argument(None),
    active: bool = typer.Option(False, "--active"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show a human-readable delegation dashboard or one task detail view."""
    try:
        service, workspaces = _delegation_runtime()
        dashboard = DelegationDashboardService(service, workspaces)
        if task_id:
            detail = dashboard.detail(task_id)
            if json_output:
                _print(detail.model_dump(mode="json"))
                return
            typer.echo(f"{detail.task.task_id}  {detail.task.status}  {detail.task.title}")
            typer.echo(
                f"Attention: {detail.task.attention} | Executor: "
                f"{detail.task.executor_id or '-'} | Repository: {detail.task.repository}"
            )
            typer.echo(
                f"Revision: {detail.task.latest_result_revision} | Accepted: "
                f"{detail.task.accepted_result_revision or '-'}"
            )
            if detail.task.worker_outcome:
                typer.echo(f"Worker outcome: {detail.task.worker_outcome}")
            if detail.outcome_detail:
                typer.echo(f"Outcome detail: {detail.outcome_detail}")
            if detail.task.worker_outcome in {"advisory", "no_work"} and detail.launches:
                typer.echo(f"Worker output: {detail.launches[-1].get('stdout_path')}")
            typer.echo("Next: " + (", ".join(detail.next_actions) or "none"))
            if detail.queue and detail.queue.get("blockers"):
                typer.echo("Blockers: " + "; ".join(detail.queue["blockers"]))
            if detail.artifact_root:
                typer.echo(f"Artifacts: {detail.artifact_root}")
            return
        rows = dashboard.list(active_only=active)
        if json_output:
            _print([row.model_dump(mode="json") for row in rows])
            return
        if not rows:
            typer.echo("No delegation tasks.")
            return
        typer.echo("ATTENTION\tSTATUS\tTASK\tEXECUTOR\tREV\tNEXT\tTITLE")
        for row in rows:
            typer.echo(
                f"{row.attention}\t{row.status}\t{row.task_id}\t"
                f"{row.executor_id or '-'}\t{row.latest_result_revision}\t"
                f"{row.next_action}\t{row.title}"
            )
    except DelegationError as exc:
        _delegation_error(exc)


@app.command()
def serve() -> None:
    """Run the local FastAPI server."""
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


@app.command()
def health() -> None:
    settings, store, _, _ = _runtime()
    try:
        state_status = "ok" if store.ping() else "error"
    except Exception:
        state_status = "error"
    _print(
        {
            "status": "ok" if state_status == "ok" else "degraded",
            "state": state_status,
            "redis": "not_required",
            "version": "0.1.0",
        }
    )


@credential_app.command("set")
def credential_set(
    name: str,
    scope: str = typer.Option("default", "--scope"),
    value: str | None = typer.Option(None, "--value", hidden=True),
) -> None:
    """Create or replace an encrypted local credential."""
    secret = value if value is not None else typer.prompt("Credential", hide_input=True)
    try:
        reference = _credential_vault().set(scope, name, secret)
    except CredentialError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Stored {reference}")


@credential_app.command("list")
def credential_list() -> None:
    """List references without decrypting credential values."""
    for reference in _credential_vault().list():
        typer.echo(reference)


@credential_app.command("rotate")
def credential_rotate(
    name: str,
    scope: str = typer.Option("default", "--scope"),
    value: str | None = typer.Option(None, "--value", hidden=True),
) -> None:
    """Replace a credential value while preserving its reference."""
    secret = value if value is not None else typer.prompt("Credential", hide_input=True)
    try:
        reference = _credential_vault().rotate(scope, name, secret)
    except CredentialError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Rotated {reference}")


@credential_app.command("delete")
def credential_delete(
    name: str, scope: str = typer.Option("default", "--scope")
) -> None:
    """Delete a local credential."""
    try:
        _credential_vault().delete(scope, name)
    except CredentialError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Deleted vault:{scope}/{name}")


@ai_endpoint_app.command("add")
def ai_endpoint_add(
    endpoint_id: str,
    provider: str = typer.Option(..., "--provider"),
    base_url: str = typer.Option(..., "--base-url"),
    api_key: str | None = typer.Option(None, "--api-key", hidden=True),
    credential_ref: str | None = typer.Option(None, "--credential-ref"),
) -> None:
    """Add an endpoint; cloud API keys are encrypted in the local vault."""
    if provider not in {
        "openai",
        "anthropic",
        "google",
        "openai_compatible",
        "ollama",
    }:
        raise typer.BadParameter(f"Unsupported AI provider: {provider}")
    if not api_key and not credential_ref and provider != "ollama":
        api_key = typer.prompt("API key", hide_input=True)
    try:
        endpoint = _ai_endpoint_service().add(
            endpoint_id,
            provider,  # type: ignore[arg-type]
            base_url,
            api_key=api_key,
            credential_ref=credential_ref,
        )
    except AIEndpointError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(endpoint.model_dump(mode="json"))


@ai_endpoint_app.command("list")
def ai_endpoint_list() -> None:
    """List configured endpoints without decrypting credentials."""
    _print(
        [
            endpoint.model_dump(mode="json")
            for endpoint in _ai_endpoint_service().list()
        ]
    )


@ai_endpoint_app.command("show")
def ai_endpoint_show(endpoint_id: str) -> None:
    try:
        endpoint = _ai_endpoint_service().get(endpoint_id)
    except AIEndpointError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(endpoint.model_dump(mode="json"))


@ai_endpoint_app.command("disable")
def ai_endpoint_disable(endpoint_id: str) -> None:
    try:
        endpoint = _ai_endpoint_service().disable(endpoint_id)
    except AIEndpointError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(endpoint.model_dump(mode="json"))


@ai_model_app.command("discover")
def ai_model_discover(endpoint_id: str) -> None:
    """Validate an endpoint by discovering its exact model catalog."""
    try:
        snapshot = _ai_catalog_service().discover(endpoint_id)
    except (AIEndpointError, ModelDiscoveryError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(snapshot.model_dump(mode="json"))


@ai_model_app.command("refresh")
def ai_model_refresh(
    endpoint_id: str,
    json_output: bool = typer.Option(False, "--json"),
    probe_new: bool = typer.Option(False, "--probe-new"),
    probe_stale: bool = typer.Option(False, "--probe-stale"),
) -> None:
    """Reconcile a configured local Ollama endpoint with its saved catalog."""
    try:
        record = _ai_reconciliation_service().refresh(endpoint_id)
    except (AIEndpointError, ModelReconciliationError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    probe_results = []
    if probe_new or probe_stale:
        probe_service = _ai_probe_service()
        queue = LocalModelProbeQueue(probe_service.catalog, probe_service)
        model_keys = (record.added if probe_new else []) + (
            record.changed if probe_stale else []
        )
        try:
            probe_results = queue.run(model_keys)
        except WorkerProbeError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if json_output:
        if probe_new or probe_stale:
            _print(
                {
                    "reconciliation": record.model_dump(mode="json"),
                    "probes": [item.model_dump(mode="json") for item in probe_results],
                }
            )
        else:
            _print(record.model_dump(mode="json"))
        return
    typer.echo(f"Endpoint: {record.endpoint_id}")
    typer.echo(f"Added: {len(record.added)}")
    typer.echo(f"Changed: {len(record.changed)}")
    typer.echo(f"Missing: {len(record.missing)}")
    typer.echo(f"Unchanged: {len(record.unchanged)}")
    for label, values in (
        ("added", record.added),
        ("changed", record.changed),
        ("missing", record.missing),
    ):
        for model_key in values:
            typer.echo(f"{label}: {model_key}")
    for result in probe_results:
        typer.echo(f"probe: {result.model_key} -> {result.classification}")


@ai_model_app.command("list")
def ai_model_list(endpoint_id: str | None = typer.Option(None, "--endpoint")) -> None:
    _print(
        [
            model.model_dump(mode="json")
            for model in _ai_catalog_service().list(endpoint_id)
        ]
    )


@ai_model_app.command("status")
def ai_model_status(
    endpoint_id: str = typer.Option(..., "--endpoint"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    status = _ai_catalog_maintenance_service().status(endpoint_id)
    if json_output:
        _print(status)
        return
    typer.echo(f"Endpoint: {endpoint_id}")
    typer.echo(f"Last successful refresh: {status['last_successful_refresh'] or '-'}")
    for group_name in ("availability", "classification", "probe_state"):
        typer.echo(f"{group_name}:")
        groups = status[group_name]
        if not groups:
            typer.echo("  -")
        for key, values in groups.items():
            typer.echo(f"  {key}: {len(values)}")


@ai_model_app.command("show")
def ai_model_show(model_key: str) -> None:
    try:
        _print(_ai_catalog_maintenance_service().show(model_key))
    except ModelCatalogMaintenanceError as exc:
        raise typer.BadParameter(str(exc)) from exc


@ai_model_app.command("forget")
def ai_model_forget(model_key: str) -> None:
    try:
        _ai_catalog_maintenance_service().forget(model_key)
    except ModelCatalogMaintenanceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Forgot {model_key}")


@ai_model_app.command("probe")
def ai_model_probe(model_key: str) -> None:
    probe = _ai_probe_service().probe(model_key)
    _print(probe.model_dump(mode="json"))


@ai_model_app.command("metadata-add")
def ai_model_metadata_add(
    model_key: str,
    path: Path,
    source_kind: str = typer.Option(..., "--source-kind"),
    source_uri: str | None = typer.Option(None, "--source-uri"),
    confidence: str = typer.Option("medium", "--confidence"),
    reviewed: bool = typer.Option(False, "--reviewed"),
) -> None:
    if confidence not in {"low", "medium", "high"}:
        raise typer.BadParameter(f"Unsupported confidence: {confidence}")
    try:
        record = _ai_metadata_service().add_file(
            model_key,
            path,
            source_kind=source_kind,
            source_uri=source_uri,
            confidence=confidence,
            reviewed=reviewed,
        )
    except (ModelDiscoveryError, ModelMetadataError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(record.model_dump(mode="json"))


@ai_pool_app.command("select")
def ai_pool_select(
    task_id: str,
    priority: str = typer.Option("balanced", "--priority"),
    allow_cloud: bool = typer.Option(False, "--allow-cloud"),
) -> None:
    from canto.models.ai_workers import WorkerSelectionPolicy

    if priority not in {"economy", "balanced", "quality", "urgent"}:
        raise typer.BadParameter(f"Unsupported priority: {priority}")
    endpoints_service = _ai_endpoint_service()
    decision = _ai_selection_service().select(
        task_id,
        _ai_catalog_service().list(),
        {endpoint.endpoint_id: endpoint for endpoint in endpoints_service.list()},
        WorkerSelectionPolicy(
            priority=priority,  # type: ignore[arg-type]
            cloud_allowed=allow_cloud,
        ),
    )
    _print(decision.model_dump(mode="json"))
    if not decision.selected_model_key:
        raise typer.Exit(2)


@ai_pool_app.command("explain")
def ai_pool_explain(decision_id: str) -> None:
    try:
        value = _ai_selection_service().explain(decision_id)
    except WorkerSelectionError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(value)


@ai_usage_app.command("list")
def ai_usage_list(task_id: str | None = typer.Option(None, "--task")) -> None:
    values = _ai_endpoint_service().store.list_ai_records("usage")
    _print([value for value in values if task_id is None or value["task_id"] == task_id])


@ai_usage_app.command("health")
def ai_usage_health(endpoint_id: str | None = typer.Option(None, "--endpoint")) -> None:
    values = _ai_endpoint_service().store.list_ai_records("endpoint_health")
    _print(
        [
            value
            for value in values
            if endpoint_id is None or value["endpoint_id"] == endpoint_id
        ]
    )


@delegate_app.command("launch-ai")
def delegate_launch_ai(
    task_id: str,
    priority: str | None = typer.Option(None, "--priority"),
    allow_cloud: bool = typer.Option(False, "--allow-cloud"),
    allow_cloud_fallback: bool = typer.Option(False, "--allow-cloud-fallback"),
) -> None:
    """Automatically select and launch a validated Worker."""
    from canto.models.ai_workers import WorkerSelectionPolicy

    if priority is not None and priority not in {"economy", "balanced", "quality", "urgent"}:
        raise typer.BadParameter(f"Unsupported priority: {priority}")
    if allow_cloud_fallback and not allow_cloud:
        raise typer.BadParameter("Cloud fallback requires --allow-cloud")
    try:
        task = _delegation_runtime()[0].get_task(task_id)
        repository_policy = load_repository_worker_policy(
            task.repository.canonical_path
        )
        command_policy = WorkerSelectionPolicy(
            priority=priority or repository_policy.priority,  # type: ignore[arg-type]
            cloud_allowed=allow_cloud,
            cloud_fallback_allowed=allow_cloud_fallback,
        )
        effective_policy = compose_worker_policy(repository_policy, command_policy)
        cli_selection = CliWorkerSelectionService(
            *_delegation_runtime(), _profile_manager()
        ).launch_first_allowed(task_id, effective_policy)
        launch = cli_selection.launch
        if launch is None:
            if cli_selection.state == "api_requires_approval":
                detail = "; ".join(cli_selection.failures) or cli_selection.detail
                raise WorkerAssignmentError(
                    "API Worker fallback requires approval before spending API credits"
                    + (f": {detail}" if detail else "")
                )
            if cli_selection.state == "api_blocked" or not http_transport_allowed(
                effective_policy
            ):
                detail = "; ".join(cli_selection.failures) or cli_selection.detail
                raise WorkerAssignmentError(
                    "HTTP Worker transport is not allowed"
                    + (f": {detail}" if detail else "")
                )
            launch = _ai_assignment_service().launch(task_id, effective_policy)
    except (
        CliWorkerSelectionError,
        DelegationError,
        WorkerAssignmentError,
        RepositoryConfigError,
    ) as exc:
        _delegation_error(exc)
    _print(launch.model_dump(mode="json"))


@demo_app.command("ai-worker-pool")
def demo_ai_worker_pool(
    apply: bool = typer.Option(False, "--apply"),
    keep: bool = typer.Option(False, "--keep"),
) -> None:
    """Run the offline governed AI Worker selection and review demo."""
    _print(run_ai_worker_pool_demo(apply=apply, keep=keep).model_dump(mode="json"))


@app.command("migrate-state")
def migrate_state(
    redis_url: str | None = typer.Option(None, "--redis-url"),
    sqlite_path: Path | None = typer.Option(None, "--sqlite-path"),
    plans_dir: Path | None = typer.Option(None, "--plans-dir"),
) -> None:
    """Copy legacy Redis and filesystem-plan state into SQLite."""
    settings = get_settings()
    registry = _capability_registry()
    target_path = sqlite_path or registry.store.paths.state_file
    legacy_plans = plans_dir or registry.store.paths.plans
    try:
        result = migrate_legacy_state(
            RedisStateStore(redis_url or settings.redis_url),
            SqliteStateStore(target_path),
            legacy_plans,
        )
    except StateMigrationError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(result.model_dump(mode="json"))


@app.command()
def registry() -> None:
    _, _, registry_value, _ = _runtime()
    _print(registry_value.snapshot())


@app.command("seed-capabilities")
def seed_capabilities() -> None:
    """List the reviewed built-in MVP capability set."""
    _, _, registry_value, _ = _runtime()
    try:
        _print(audit_seed_capabilities(registry_value))
    except SeedCapabilityError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("list")
def list_capabilities() -> None:
    """List installed capabilities."""
    try:
        capabilities = _capability_registry().list_installed()
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not capabilities:
        typer.echo("No capabilities installed.")
        return

    typer.echo("NAME\tVERSION\tRISK\tPATH")
    for capability in capabilities:
        typer.echo(
            f"{capability.name}\t{capability.version}\t"
            f"{capability.risk}\t{capability.path}"
        )


@app.command()
def search(query: str) -> None:
    """Search capabilities in the local registry."""
    try:
        capabilities = _capability_registry().search(query)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not capabilities:
        typer.echo(f"No local capabilities found matching: {query}")
        return

    typer.echo("NAME\tVERSION\tINSTALLED\tRISK\tPATH")
    for capability in capabilities:
        installed = "yes" if capability.installed else "no"
        typer.echo(
            f"{capability.name}\t{capability.version}\t{installed}\t"
            f"{capability.risk}\t{capability.path}"
        )


@app.command()
def discover(goal: str) -> None:
    """Rank installed local capabilities for a goal without executing them."""
    try:
        matches = CapabilityMatcher(_capability_registry()).discover(goal)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print([match.model_dump(mode="json") for match in matches])


@app.command()
def plan(goal: str, approve: bool = typer.Option(False, "--approve")) -> None:
    """Build a local workflow candidate without executing it."""
    try:
        service = _runtime()[3] if approve else None
        execution_plan = _orchestrator(service).create_plan(goal, approve=approve)
    except (LocalRegistryError, OrchestrationError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(execution_plan.model_dump(mode="json"))


@app.command()
def execute(plan_id: str) -> None:
    """Execute an approved local orchestration plan."""
    _, _, _, service = _runtime()
    orchestrator = _orchestrator(service)

    try:
        result = orchestrator.execute(plan_id)
    except (LocalRegistryError, OrchestrationError, JobError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(result.model_dump(mode="json"))


@app.command()
def explain(plan_id: str) -> None:
    """Explain a saved orchestration plan without executing it."""
    try:
        explanation = _orchestrator().explain(plan_id)
    except (LocalRegistryError, OrchestrationError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(explanation.model_dump(mode="json"))


@app.command()
def inspect(name: str, version: str | None = typer.Option(None, "--version")) -> None:
    """Inspect an installed capability."""
    try:
        capability = _capability_registry().inspect(name, version)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print(capability.model_dump(mode="json"))


@app.command()
def remove(name: str, version: str | None = typer.Option(None, "--version")) -> None:
    """Remove an installed capability."""
    try:
        entry = _capability_registry().remove(name, version)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Removed {entry.name} {entry.version}")


@app.command("validate-installed")
def validate_installed(
    name: str, version: str | None = typer.Option(None, "--version")
) -> None:
    """Validate an installed capability and registry metadata."""
    try:
        result = _capability_registry().validate_installed(name, version)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    if not result.valid:
        for error in result.errors:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Installed capability is valid: {name}")


@app.command()
def install(source: Path) -> None:
    """Install a capability from a local .canto archive."""
    try:
        result = _capability_registry().install_package(source)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    if result.dependencies:
        typer.echo(
            "Dependencies declared but not installed: "
            + json.dumps(result.dependencies, sort_keys=True)
        )
    typer.echo(f"Installed {result.entry.name} {result.entry.version}")


@app.command()
def pack(
    capability_dir: Path,
    output: Path = typer.Option(Path("."), "--output", "-o"),
) -> None:
    """Pack a capability directory into a deterministic .canto archive."""
    try:
        package_path = pack_capability(capability_dir, output)
    except CapabilityPackageError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created {package_path}")


@app.command("validate-package")
def validate_capability_package(package: Path) -> None:
    """Validate a .canto archive and its checksums."""
    result = validate_package(package)
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    if not result.valid:
        for error in result.errors:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Capability package is valid: {package}")


@app.command()
def export(
    name: str,
    version: str | None = typer.Option(None, "--version"),
    output: Path = typer.Option(Path("."), "--output", "-o"),
) -> None:
    """Export an installed capability as a .canto archive."""
    try:
        package_path = _capability_registry().export(name, version, output)
    except LocalRegistryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Exported {package_path}")


@app.command()
def scaffold(
    name: str,
    output: Path = typer.Option(Path("."), "--output", "-o"),
) -> None:
    """Create a local capability scaffold."""
    try:
        destination = scaffold_capability_structure(name, output)
    except CapabilityScaffoldError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Created scaffold {destination}")


@capability_app.command("validate")
def capability_validate(path: Path) -> None:
    """Validate a capability manifest."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Error: cannot read capability manifest {path}: {exc}", err=True)
        raise typer.Exit(1) from exc

    result = CapabilityManifestValidator.validate_yaml(content)
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    if not result.valid:
        for error in result.errors:
            typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Capability manifest is valid: {path}")


@skill_app.command("show")
def skill_show(name: str) -> None:
    _, _, registry_value, _ = _runtime()
    value = registry_value.get_skill(name)
    if not value:
        raise typer.BadParameter(f"Unknown skill: {name}")
    _print(value)


@provider_app.command("show")
def provider_show(skill: str, provider: str) -> None:
    _, _, registry_value, _ = _runtime()
    value = registry_value.get_provider(skill, provider)
    if not value:
        raise typer.BadParameter(f"Unknown provider: {skill}.{provider}")
    _print(value)


@app.command()
def run(
    skill: str,
    provider: str = typer.Option(..., "--provider"),
    input_value: list[str] = typer.Option([], "--input"),
    allow_network: bool = typer.Option(False, "--allow-network"),
    approved_domain: list[str] = typer.Option([], "--approved-domain"),
) -> None:
    _, _, _, service = _runtime()
    request = JobRequest(
        skill=skill,
        provider=provider,
        inputs=_parse_inputs(input_value),
        policy=Policy(allow_network=allow_network, approved_domains=approved_domain),
        requested_by="cli",
    )
    missing = service.missing_capability(request)
    if missing:
        _print(missing)
        raise typer.Exit(2)
    try:
        job = service.create_job(request)
        typer.echo(f"Created {job.job_id} ({job.status}); processing...", err=True)
        job = service.process_job(job.job_id)
    except JobError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(job.model_dump(mode="json"))


@app.command()
def promote(job_id: str) -> None:
    """Request approval to promote a completed write-provider dry run."""
    _, _, _, service = _runtime()
    try:
        approval = service.promote(job_id)
    except JobError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(approval.model_dump(mode="json"))


@app.command()
def recover(job_id: str) -> None:
    """Request approval to recover a completed live write job."""
    _, _, _, service = _runtime()
    try:
        approval = service.recover(job_id)
    except JobError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _print(approval.model_dump(mode="json"))


@job_app.command("show")
def job_show(job_id: str) -> None:
    _, store, _, _ = _runtime()
    _print(store.get_job(job_id) or {"error": "not_found"})


@job_app.command("events")
def job_events(job_id: str) -> None:
    _, store, _, _ = _runtime()
    _print(store.get_events(job_id))


@job_app.command("artifacts")
def job_artifacts(job_id: str) -> None:
    _, store, _, _ = _runtime()
    _print(store.get_artifacts(job_id))


@memory_app.command("status")
def memory_status() -> None:
    try:
        _print(_memory_service(read_only=True).status())
    except (MemoryServiceError, sqlite3.Error, RuntimeError) as exc:
        _memory_error(exc)


@memory_project_app.command("create")
def memory_project_create(label: str) -> None:
    try:
        _print(_memory_service().create_project(label, "cli").model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_project_app.command("list")
def memory_project_list() -> None:
    try:
        _print([item.model_dump(mode="json") for item in _memory_service(read_only=True).list_projects()])
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_project_app.command("show")
def memory_project_show(project_id: str) -> None:
    try:
        _print(_memory_service(read_only=True).get_project(project_id).model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_project_app.command("link-repository")
def memory_project_link_repository(project_id: str, repository: Path = Path(".")) -> None:
    try:
        config = load_repository(repository)
        _print(_memory_service().link_repository(project_id, config.repo_id, "cli").model_dump(mode="json"))
    except (MemoryServiceError, RepositoryConfigError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_project_app.command("unlink-repository")
def memory_project_unlink_repository(project_id: str, repository: Path = Path(".")) -> None:
    try:
        config = load_repository(repository)
        _print(_memory_service().unlink_repository(project_id, config.repo_id, "cli").model_dump(mode="json"))
    except (MemoryServiceError, RepositoryConfigError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("propose")
def memory_propose(
    scope: str = typer.Option(..., "--scope"),
    type: str = typer.Option(..., "--type"),
    title: str = typer.Option(..., "--title"),
    body: str = typer.Option(..., "--body"),
    source_kind: str = typer.Option("documentation", "--source-kind"),
    source_ref: str = typer.Option("cli", "--source-ref"),
    confidence: str = typer.Option("uncertain", "--confidence"),
    alias: list[str] = typer.Option([], "--alias"),
    tag: list[str] = typer.Option([], "--tag"),
) -> None:
    try:
        item = _memory_service().propose(
            scope=scope, type=type, title=title, body=body,
            source_kind=source_kind, source_ref=source_ref,
            author_kind="developer", author_id="cli", confidence=confidence,
            aliases=alias, tags=tag,
        )
        _print(item.model_dump(mode="json"))
    except (MemoryServiceError, ValueError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("list")
def memory_list(status: list[str] = typer.Option([], "--status")) -> None:
    try:
        values = _memory_service(read_only=True).list(set(status) or None)
        _print([item.model_dump(mode="json") for item in values])
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("show")
def memory_show(memory_id: str) -> None:
    try:
        _print(_memory_service(read_only=True).get(memory_id).model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("request-approval")
def memory_request_approval(memory_id: str) -> None:
    try:
        _print(_memory_service().request_approval(memory_id, "cli").model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("supersede")
def memory_supersede(memory_id: str, replacement_id: str) -> None:
    try:
        _print(_memory_service().supersede(memory_id, replacement_id, "cli").model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("expire")
def memory_expire(memory_id: str, reason: str = "") -> None:
    try:
        _print(_memory_service().transition(memory_id, "expired", "cli", reason).model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("delete")
def memory_delete(memory_id: str, reason: str = "") -> None:
    try:
        _print(_memory_service().transition(memory_id, "deleted", "cli", reason).model_dump(mode="json"))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("purge")
def memory_purge(memory_id: str, reason: str = typer.Option(..., "--reason")) -> None:
    try:
        _memory_service().purge(memory_id, "cli", reason)
        _print({"memory_id": memory_id, "purged": True})
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


def _memory_scopes(repository: Path, project: list[str]) -> tuple[MemoryService, list[str]]:
    config = load_repository(repository)
    service = _memory_service(read_only=True)
    requested = ["global:terminology", f"repo:{config.repo_id}", *[f"project:{value}" for value in project]]
    return service, service.allowed_scopes(config.repo_id, requested)


@memory_app.command("recall")
def memory_recall(
    query: str,
    repository: Path = typer.Option(Path("."), "--repo"),
    project: list[str] = typer.Option([], "--project"),
    type: list[str] = typer.Option([], "--type"),
    max_items: int = typer.Option(12, "--max-items"),
    max_tokens: int = typer.Option(2500, "--max-tokens"),
) -> None:
    try:
        service, scopes = _memory_scopes(repository, project)
        _print(service.recall(query, scopes, types=set(type) or None, max_items=max_items, max_tokens=max_tokens).model_dump(mode="json"))
    except (MemoryServiceError, RepositoryConfigError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("resolve")
def memory_resolve(reference: str, repository: Path = typer.Option(Path("."), "--repo"), project: list[str] = typer.Option([], "--project")) -> None:
    try:
        service, scopes = _memory_scopes(repository, project)
        _print(service.resolve(reference, scopes).model_dump(mode="json"))
    except (MemoryServiceError, RepositoryConfigError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("context-pack")
def memory_context_pack(
    repository: Path = typer.Option(Path("."), "--repo"),
    profile: str = typer.Option("startup", "--profile"),
    query: str = typer.Option("", "--query"),
    project: list[str] = typer.Option([], "--project"),
) -> None:
    try:
        service, scopes = _memory_scopes(repository, project)
        _print(service.context_pack(profile, scopes, query).model_dump(mode="json"))
    except (MemoryServiceError, RepositoryConfigError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("attach-observation")
def memory_attach_observation(
    source_kind: str = typer.Option(..., "--source-kind"),
    source_ref: str = typer.Option(..., "--source-ref"),
    scope: str = typer.Option(..., "--scope"),
    title: str = typer.Option(..., "--title"),
    body: str = typer.Option(..., "--body"),
) -> None:
    try:
        item = _memory_service().propose(scope=scope, type="observation", title=title, body=body, source_kind=source_kind, source_ref=source_ref, author_kind="worker", author_id="cli", confidence="observed", observed=True)
        _print(item.model_dump(mode="json"))
    except (MemoryServiceError, ValueError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("attach-outcome")
def memory_attach_outcome(
    source_kind: str = typer.Option(..., "--source-kind"),
    source_ref: str = typer.Option(..., "--source-ref"),
    scope: str = typer.Option(..., "--scope"),
    title: str = typer.Option(..., "--title"),
    body: str = typer.Option(..., "--body"),
) -> None:
    try:
        item = _memory_service().propose(scope=scope, type="outcome", title=title, body=body, source_kind=source_kind, source_ref=source_ref, author_kind="worker", author_id="cli", confidence="supported")
        _print(item.model_dump(mode="json"))
    except (MemoryServiceError, ValueError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("retain")
def memory_retain() -> None:
    try:
        _print({"expired": _memory_service().run_retention()})
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("export")
def memory_export(include_deleted: bool = typer.Option(False, "--include-deleted")) -> None:
    try:
        _print(_memory_service(read_only=True).export(include_deleted=include_deleted))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@memory_app.command("audit")
def memory_audit(memory_id: str | None = typer.Option(None, "--memory-id")) -> None:
    try:
        _print(_memory_service(read_only=True).audit(memory_id))
    except (MemoryServiceError, sqlite3.Error) as exc:
        _memory_error(exc)


@app.command()
def approve(approval_id: str, note: str = "") -> None:
    _, _, _, service = _runtime()
    _print(service.approve(approval_id, "cantor", note).model_dump(mode="json"))


@app.command()
def reject(approval_id: str, reason: str = typer.Option(..., "--reason")) -> None:
    _, _, _, service = _runtime()
    _print(service.reject(approval_id, "cantor", reason).model_dump(mode="json"))


if __name__ == "__main__":
    app()
