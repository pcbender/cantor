from __future__ import annotations

from canto.core.delegation import DelegationError, DelegationService
from canto.core.delegation_executor import CodexCliExecutor, ExecutorError
from canto.core.delegation_workspace import DelegationWorkspaceService
from canto.core.executor_profiles import ExecutorProfileManager
from canto.models.ai_workers import WorkerSelectionPolicy
from canto.models.delegation import ExecutorLaunch, ExecutorProfile
from canto.models.schemas import utc_now


class CliWorkerSelectionError(DelegationError):
    pass


def cli_transport_allowed(policy: WorkerSelectionPolicy) -> bool:
    return "cli" in policy.allowed_transports


def http_transport_allowed(policy: WorkerSelectionPolicy) -> bool:
    return not policy.allowed_transports or "http" in policy.allowed_transports


class CliWorkerSelectionService:
    def __init__(
        self,
        delegation: DelegationService,
        workspaces: DelegationWorkspaceService,
        profiles: ExecutorProfileManager,
    ):
        self.delegation = delegation
        self.workspaces = workspaces
        self.profiles = profiles

    def launch_first_allowed(
        self, task_id: str, policy: WorkerSelectionPolicy
    ) -> ExecutorLaunch | None:
        if not cli_transport_allowed(policy):
            return None
        candidates = self._ordered_candidates(policy)
        failures: list[str] = []
        for profile in candidates:
            check = self.profiles.check(
                profile, subscription_auth=profile.model_provider != "ollama"
            )
            if not check["available"]:
                failures.append(f"{profile.executor_id}: {check['detail']}")
                continue
            self._assign_profile(task_id, profile)
            try:
                return CodexCliExecutor(self.delegation, self.workspaces).launch(task_id)
            except ExecutorError as exc:
                raise CliWorkerSelectionError(str(exc)) from exc
        if http_transport_allowed(policy):
            return None
        detail = "; ".join(failures) if failures else "no allowed CLI profiles"
        raise CliWorkerSelectionError(f"No eligible CLI Worker: {detail}")

    def _ordered_candidates(
        self, policy: WorkerSelectionPolicy
    ) -> list[ExecutorProfile]:
        profiles = [
            profile
            for profile in self.delegation.list_executor_profiles()
            if profile.harness == "codex_cli" and profile.launch_mode == "canto"
        ]
        if policy.allowed_cli_profiles:
            allowed = set(policy.allowed_cli_profiles)
            profiles = [profile for profile in profiles if profile.executor_id in allowed]
        by_id = {profile.executor_id: profile for profile in profiles}
        ordered = [
            by_id[executor_id]
            for executor_id in policy.preferred_cli_profiles
            if executor_id in by_id
        ]
        ordered_ids = {profile.executor_id for profile in ordered}
        remaining = sorted(
            (profile for profile in profiles if profile.executor_id not in ordered_ids),
            key=lambda profile: profile.executor_id,
        )
        if policy.prefer_subscription_cli:
            remaining.sort(key=lambda profile: profile.model_provider == "ollama")
        return ordered + remaining

    def _assign_profile(self, task_id: str, profile: ExecutorProfile) -> None:
        task = self.delegation.get_task(task_id)
        if task.status not in {"workspace_ready", "revision_requested"}:
            raise CliWorkerSelectionError(
                "CLI Worker launch requires a workspace_ready or revision_requested task"
            )
        updated = task.model_copy(
            update={
                "executor_id": profile.executor_id,
                "selected_model_key": f"cli:{profile.executor_id}",
                "updated_at": utc_now(),
            }
        )
        self.delegation.store.set_delegation_task(
            task_id, updated.model_dump(mode="json")
        )
