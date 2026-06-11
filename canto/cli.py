from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

app = typer.Typer(help="Canto local orchestration broker")
skill_app = typer.Typer(help="Inspect skills")
provider_app = typer.Typer(help="Inspect providers")
job_app = typer.Typer(help="Inspect jobs")
capability_app = typer.Typer(help="Manage capability manifests")
credential_app = typer.Typer(help="Manage local encrypted credentials")
app.add_typer(skill_app, name="skill")
app.add_typer(provider_app, name="provider")
app.add_typer(job_app, name="job")
app.add_typer(capability_app, name="capability")
app.add_typer(credential_app, name="credential")


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
