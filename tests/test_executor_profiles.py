from __future__ import annotations

import pytest

from canto.core.delegation import DelegationService
from canto.core.executor_profiles import ExecutorProfileError, ExecutorProfileManager
from canto.core.state import MemoryStateStore
from canto.models.delegation import ExecutorProfile
import canto.core.executor_profiles as profile_module


def manager(tmp_path):
    return ExecutorProfileManager(
        DelegationService(MemoryStateStore()), tmp_path / "config" / "executors.yaml"
    )


def test_builtin_presets_are_credential_free_and_reusable(tmp_path):
    profiles = manager(tmp_path)
    profile = profiles.resolve(
        "cloud-mini", preset="codex-cloud", cli_override={"model": "gpt-5.4-mini"}
    )
    profiles.save(profile)
    assert profile.harness == "codex_cli"
    assert profile.model_provider == "openai"
    assert profiles.delegation.get_executor_profile("cloud-mini").model == "gpt-5.4-mini"


def test_profile_precedence_is_cli_task_saved_preset_default(tmp_path):
    profiles = manager(tmp_path)
    profiles.save(
        ExecutorProfile(
            executor_id="worker",
            name="saved",
            harness="codex_cli",
            executable="saved-codex",
            model="saved-model",
            launch_mode="canto",
        )
    )
    resolved = profiles.resolve(
        "worker",
        preset="codex-cloud",
        task_override={"model": "task-model"},
        cli_override={"model": "cli-model"},
    )
    assert resolved.executable == "saved-codex"
    assert resolved.model == "cli-model"


def test_user_presets_load_from_global_config_and_reject_secrets(tmp_path):
    profiles = manager(tmp_path)
    profiles.config_file.parent.mkdir(parents=True)
    profiles.config_file.write_text(
        "presets:\n  local:\n    harness: codex_cli\n    executable: codex\n    launch_mode: canto\n"
    )
    assert "local" in profiles.presets()

    profiles.config_file.write_text("presets:\n  unsafe:\n    token: secret\n")
    with pytest.raises(ExecutorProfileError, match="Credentials are not allowed"):
        profiles.presets()


def test_profile_check_is_non_mutating(tmp_path):
    profiles = manager(tmp_path)
    profile = profiles.resolve("manual-reviewer", preset="manual")
    assert profiles.check(profile)["available"] is True
    assert profiles.delegation.list_executor_profiles() == []


def test_profile_check_can_require_codex_subscription_auth(tmp_path, monkeypatch):
    profiles = manager(tmp_path)
    profile = profiles.resolve("cloud", preset="codex-cloud")
    monkeypatch.setattr(profile_module.shutil, "which", lambda value: "/usr/bin/codex")
    monkeypatch.setenv("HOME", str(tmp_path))

    failed = profiles.check(profile, subscription_auth=True)
    assert failed["available"] is False
    assert "subscription auth" in failed["detail"]

    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text(
        '{"auth_mode": "chatgpt", "OPENAI_API_KEY": null}', encoding="utf-8"
    )

    passed = profiles.check(profile, subscription_auth=True)
    assert passed["available"] is True


def test_ollama_preset_is_local_only_and_checks_installed_model(tmp_path, monkeypatch):
    profiles = manager(tmp_path)
    profile = profiles.resolve(
        "local-small", preset="codex-ollama", cli_override={"model": "qwen3:8b"}
    )
    monkeypatch.setattr(
        profile_module.shutil,
        "which",
        lambda value: f"/usr/bin/{value}" if value in {"codex", "ollama"} else None,
    )
    monkeypatch.setattr(
        profile_module.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Completed", (), {"returncode": 0, "stdout": "NAME ID SIZE\nqwen3:8b abc 5GB\n", "stderr": ""}
        )(),
    )
    assert profile.configuration["extra_args"] == ["--oss", "--local-provider", "ollama"]
    assert profiles.check(profile)["available"] is True


def test_ollama_check_never_pulls_missing_model(tmp_path, monkeypatch):
    profiles = manager(tmp_path)
    profile = profiles.resolve(
        "local-small", preset="codex-ollama", cli_override={"model": "missing-model"}
    )
    commands = []
    monkeypatch.setattr(profile_module.shutil, "which", lambda value: f"/usr/bin/{value}")

    def run(argv, **kwargs):
        commands.append(argv)
        return type("Completed", (), {"returncode": 0, "stdout": "NAME ID SIZE\n", "stderr": ""})()

    monkeypatch.setattr(profile_module.subprocess, "run", run)
    result = profiles.check(profile)
    assert result["available"] is False
    assert "will not pull" in result["detail"]
    assert commands == [["/usr/bin/ollama", "list"]]
