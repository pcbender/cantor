from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from canto.config import Settings
from canto.core.capability_package import pack_capability, validate_package
from canto.core.jobs import JobService
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.orchestration import CapabilityMatcher, Orchestrator, PlanStore
from canto.core.registry import Registry as RuntimeRegistry
from canto.core.state import MemoryStateStore


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "release_demo"


def show(value: object) -> None:
    print(json.dumps(value, indent=2))


def main() -> None:
    jobs_dir = ROOT / "work" / "jobs"
    existing_jobs = set(jobs_dir.iterdir()) if jobs_dir.is_dir() else set()
    try:
        with tempfile.TemporaryDirectory(prefix="canto-release-demo-") as temporary:
            temp = Path(temporary)
            registry = CapabilityRegistry.local(temp / "home")

            print("[1/10] Pack")
            package = pack_capability(SOURCE, temp / "dist")
            print(package)

            print("[2/10] Validate package")
            validation = validate_package(package)
            assert validation.valid, validation.errors

            print("[3/10] Install")
            installed = registry.install_package(package)
            print(f"Installed {installed.entry.name} {installed.entry.version}")

            print("[4/10] List")
            for entry in registry.list_installed():
                print(f"{entry.name}\t{entry.version}\t{entry.risk}")

            print("[5/10] Inspect")
            show(registry.inspect("release_demo").model_dump(mode="json"))

            print("[6/10] Discover")
            matches = CapabilityMatcher(registry).discover("run the release demo")
            assert matches and matches[0].name == "release_demo"
            show([match.model_dump(mode="json") for match in matches])

            settings = Settings(
                root_dir=ROOT,
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
                    capability_registry=registry,
                ),
                state,
            )
            orchestrator = Orchestrator(
                registry,
                PlanStore(registry.store.paths.plans),
                job_service=service,
            )

            print("[7/10] Plan and approve")
            plan = orchestrator.create_plan(
                "run the release demo", approve=True
            )
            assert plan.status == "approved"
            show(plan.model_dump(mode="json"))

            print("[8/10] Execute")
            execution = orchestrator.execute(plan.plan_id)
            assert execution.status == "completed"
            artifact = Path(execution.artifacts["release-demo.json"])
            assert json.loads(artifact.read_text(encoding="utf-8")) == {
                "contract_version": "1.0",
                "demo": "canto-v2.2",
                "status": "completed",
            }
            show(execution.model_dump(mode="json"))

            print("[9/10] Explain")
            explanation = orchestrator.explain(plan.plan_id)
            assert explanation.status == "completed"
            show(explanation.model_dump(mode="json"))

            print("[10/10] Export")
            exported = registry.export("release_demo", output_dir=temp / "exported")
            assert validate_package(exported).valid
            print(exported)

            print("Canto v2.2 release demo passed.")
    finally:
        if jobs_dir.is_dir():
            for job_dir in set(jobs_dir.iterdir()) - existing_jobs:
                if job_dir.is_dir():
                    shutil.rmtree(job_dir)


if __name__ == "__main__":
    main()
