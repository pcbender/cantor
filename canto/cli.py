from __future__ import annotations

import json
from typing import Any

import typer
import uvicorn

from canto.api.server import create_app
from canto.config import get_settings
from canto.core.jobs import JobError, JobService
from canto.core.registry import Registry
from canto.core.state import RedisStateStore
from canto.models.schemas import JobRequest, Policy

app = typer.Typer(help="Canto local orchestration broker")
skill_app = typer.Typer(help="Inspect skills")
provider_app = typer.Typer(help="Inspect providers")
job_app = typer.Typer(help="Inspect jobs")
app.add_typer(skill_app, name="skill")
app.add_typer(provider_app, name="provider")
app.add_typer(job_app, name="job")


def _runtime() -> tuple:
    settings = get_settings()
    store = RedisStateStore(settings.redis_url)
    registry = Registry(settings.skills_dir, settings.tools_dir)
    return settings, store, registry, JobService(settings, registry, store)


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
        redis_status = "ok" if store.ping() else "error"
    except Exception:
        redis_status = "error"
    _print({"status": "ok" if redis_status == "ok" else "degraded", "redis": redis_status, "version": "0.1.0"})


@app.command()
def registry() -> None:
    _, _, registry_value, _ = _runtime()
    _print(registry_value.snapshot())


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
