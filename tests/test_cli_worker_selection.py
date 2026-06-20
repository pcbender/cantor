from __future__ import annotations

from canto.core.cli_worker_selection import CliWorkerSelectionService
from canto.core.delegation import DelegationService
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.core.executor_profiles import ExecutorProfileManager
from canto.core.state import MemoryStateStore
from canto.models.ai_workers import WorkerSelectionPolicy
from canto.models.delegation import ExecutorProfile


def service(tmp_path):
    delegation = DelegationService(MemoryStateStore())
    return CliWorkerSelectionService(
        delegation,
        DelegationWorkspaceService(delegation, tmp_path / "work"),
        ExecutorProfileManager(delegation, tmp_path / "config" / "executors.yaml"),
    )


def test_cli_selection_ignores_cli_when_transport_not_allowed(tmp_path):
    result = service(tmp_path).launch_first_allowed(
        "task", WorkerSelectionPolicy()
    )

    assert result.state == "not_allowed"


def test_cli_selection_blocks_api_fallback_for_cli_only_policy(tmp_path):
    result = service(tmp_path).launch_first_allowed(
        "task",
        WorkerSelectionPolicy(
            allowed_transports=["cli"],
            allowed_cli_profiles=["missing"],
            priority="urgent",
        ),
    )

    assert result.state == "api_blocked"
    assert result.detail == "no allowed CLI profiles"


def test_cli_selection_requires_approval_for_balanced_api_spill(tmp_path):
    result = service(tmp_path).launch_first_allowed(
        "task",
        WorkerSelectionPolicy(
            allowed_transports=["cli", "http"],
            allowed_cli_profiles=["missing"],
            priority="balanced",
        ),
    )

    assert result.state == "api_requires_approval"


def test_cli_selection_allows_urgent_api_spill_when_http_is_allowed(tmp_path):
    result = service(tmp_path).launch_first_allowed(
        "task",
        WorkerSelectionPolicy(
            allowed_transports=["cli", "http"],
            allowed_cli_profiles=["missing"],
            priority="urgent",
        ),
    )

    assert result.state == "api_allowed"


def test_cli_candidate_explanation_marks_same_provider(tmp_path):
    selector = service(tmp_path)
    selector.delegation.set_executor_profile(
        ExecutorProfile(
            executor_id="codex-cloud",
            name="Codex Cloud",
            harness="codex_cli",
            model_provider="openai",
            launch_mode="canto",
        )
    )

    explanation = selector.explain_candidates(
        WorkerSelectionPolicy(
            allowed_transports=["cli"],
            preferred_cli_profiles=["codex-cloud"],
            orchestrator_provider="openai",
        )
    )

    assert explanation["candidates"] == [
        {
            "executor_id": "codex-cloud",
            "model_provider": "openai",
            "preferred": True,
            "same_as_orchestrator": True,
        }
    ]
