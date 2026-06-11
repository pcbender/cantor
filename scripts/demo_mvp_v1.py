from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from canto.config import Settings
from canto.core.capability_package import pack_capability, validate_package
from canto.core.credentials import CredentialVault
from canto.core.jobs import JobService
from canto.core.local_registry import Registry as CapabilityRegistry
from canto.core.orchestration import CapabilityMatcher, Orchestrator, PlanStore
from canto.core.registry import Registry as RuntimeRegistry
from canto.core.state import SqliteStateStore
from canto.models.schemas import JobRequest


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="canto-mvp-v1-") as temporary:
        temp = Path(temporary)
        runtime_root = temp / "runtime"
        shutil.copytree(ROOT / "skills", runtime_root / "skills")
        shutil.copytree(ROOT / "tools", runtime_root / "tools")
        capability_registry = CapabilityRegistry.local(temp / "home")
        package = pack_capability(ROOT / "examples" / "mvp_v1_demo", temp / "dist")
        assert validate_package(package).valid
        capability_registry.install_package(package)

        settings = Settings(
            root_dir=runtime_root,
            redis_url="redis://unused",
            host="127.0.0.1",
            port=8765,
            provider_timeout_seconds=10,
            max_provider_output_bytes=1_048_576,
        )
        store = SqliteStateStore(temp / "home" / ".canto" / "state" / "canto.db")
        vault = CredentialVault(temp / "home" / ".canto" / "vault")
        vault.set("demo", "token", "mvp-secret")
        runtime_registry = RuntimeRegistry(
            settings.skills_dir,
            settings.tools_dir,
            capability_registry=capability_registry,
        )
        service = JobService(settings, runtime_registry, store, vault=vault)
        orchestrator = Orchestrator(
            capability_registry, PlanStore(store), job_service=service
        )

        matches = CapabilityMatcher(capability_registry).discover("verify mvp v1")
        assert matches and matches[0].name == "mvp_v1_demo"
        plan = orchestrator.create_plan(
            "verify mvp v1",
            inputs={"demo_token_ref": "vault:demo/token"},
            approve=True,
        )
        execution = orchestrator.execute(plan.plan_id)
        proof = json.loads(Path(execution.artifacts["mvp-v1-demo.json"]).read_text())
        assert proof["credential_received"] is True
        assert "mvp-secret" not in json.dumps(store.get_plan(plan.plan_id))

        target = temp / "managed.json"
        target.write_text('{"status":"before"}\n', encoding="utf-8")
        dry_run = service.create_job(
            JobRequest(
                skill="managed_json",
                provider="local_document",
                inputs={
                    "target_path": str(target),
                    "target_id": "mvp-v1:local",
                    "desired": {"status": "after"},
                    "idempotency_key": "mvp-v1-demo-1",
                },
            )
        )
        dry_run = service.process_job(dry_run.job_id)
        promotion = service.promote(dry_run.job_id)
        live = service.approve(promotion.approval_id, "cantor", "MVP v1 demo")
        assert json.loads(target.read_text()) == {"status": "after"}
        recovery = service.recover(live.job_id)
        service.approve(recovery.approval_id, "cantor", "MVP v1 rollback")
        assert json.loads(target.read_text()) == {"status": "before"}

        print("Canto MVP v1 stability demo passed.")


if __name__ == "__main__":
    main()
