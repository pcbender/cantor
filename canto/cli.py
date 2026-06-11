from __future__ import annotations

import json
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
from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_workspace import (
    DelegationWorkspaceService,
    WorkspaceError,
    inspect_repository,
)
from canto.core.delegation_executor import CodexCliExecutor, ExecutorError
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
from canto.core.jobs import JobError, JobService
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
)

app = typer.Typer(help="Canto local orchestration broker")
skill_app = typer.Typer(help="Inspect skills")
provider_app = typer.Typer(help="Inspect providers")
job_app = typer.Typer(help="Inspect jobs")
capability_app = typer.Typer(help="Manage capability manifests")
credential_app = typer.Typer(help="Manage local encrypted credentials")
delegate_app = typer.Typer(help="Coordinate delegated executor workspaces")
app.add_typer(skill_app, name="skill")
app.add_typer(provider_app, name="provider")
app.add_typer(job_app, name="job")
app.add_typer(capability_app, name="capability")
app.add_typer(credential_app, name="credential")
app.add_typer(delegate_app, name="delegate")


def _credential_vault() -> CredentialVault:
    return CredentialVault.local()


def _runtime() -> tuple:
    settings = get_settings()
    capability_registry = _capability_registry()
    store = SqliteStateStore(
        capability_registry.store.paths.root / "state" / "canto.db"
    )
    registry = Registry(
        settings.skills_dir,
        settings.tools_dir,
        capability_registry=capability_registry,
    )
    return settings, store, registry, JobService(settings, registry, store)


def _capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry.local()


def _delegation_runtime() -> tuple[DelegationService, DelegationWorkspaceService]:
    registry = _capability_registry()
    store = SqliteStateStore(registry.store.paths.root / "state" / "canto.db")
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
        else SqliteStateStore(registry.store.paths.root / "state" / "canto.db")
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
        task = DelegationTask(
            task_id=f"task_{uuid4().hex}",
            title=title,
            repository=inspect_repository(repository),
            scope=DelegationScope(allowed_paths=allow, denied_paths=deny),
            instructions=instruction,
            created_by="cli",
        )
        service.create_task(task)
    except (DelegationError, WorkspaceError) as exc:
        _delegation_error(exc)
    _print(task.model_dump(mode="json"))


@delegate_app.command("assign")
def delegate_assign(
    task_id: str,
    executor_id: str = typer.Option("manual", "--executor"),
) -> None:
    """Assign a task to a manual executor profile."""
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
        if profile.harness != "manual":
            raise DelegationError("The manual workflow requires a manual executor profile")
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
        service, _ = _delegation_runtime()
        task = service.get_task(task_id)
        value = task.model_dump(mode="json")
        value["messages"] = service.get_records(task_id, "messages")
        value["sessions"] = service.get_records(task_id, "sessions")
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
        CodexCliExecutor(service, workspaces).available(profile)
        service.set_executor_profile(profile)
    except (DelegationError, ExecutorError) as exc:
        _delegation_error(exc)
    _print(profile.model_dump(mode="json"))


@delegate_app.command("launch")
def delegate_launch(task_id: str) -> None:
    """Launch the assigned Codex CLI profile in its prepared worktree."""
    try:
        service, workspaces = _delegation_runtime()
        launch = CodexCliExecutor(service, workspaces).launch(task_id)
    except (DelegationError, ExecutorError) as exc:
        _delegation_error(exc)
    _print(launch.model_dump(mode="json"))


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
    service, _ = _delegation_runtime()
    _print(
        [
            entry.model_dump(mode="json")
            for entry in DelegationPoolService(service).executors()
        ]
    )


@delegate_app.command("status")
def delegate_status(active: bool = typer.Option(False, "--active")) -> None:
    """Show durable delegation task status across parallel workspaces."""
    service, _ = _delegation_runtime()
    _print(
        [
            item.model_dump(mode="json")
            for item in DelegationPoolService(service).tasks(active_only=active)
        ]
    )


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


@app.command("migrate-state")
def migrate_state(
    redis_url: str | None = typer.Option(None, "--redis-url"),
    sqlite_path: Path | None = typer.Option(None, "--sqlite-path"),
    plans_dir: Path | None = typer.Option(None, "--plans-dir"),
) -> None:
    """Copy legacy Redis and filesystem-plan state into SQLite."""
    settings = get_settings()
    registry = _capability_registry()
    target_path = sqlite_path or (
        registry.store.paths.root / "state" / "canto.db"
    )
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
