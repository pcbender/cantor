from __future__ import annotations

from pathlib import Path

from canto.core.delegation_demo import cleanup_delegation_demo, run_delegation_demo


def test_scripted_demo_is_offline_isolated_and_cleans_success(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    result = run_delegation_demo()
    assert result.status == "reviewing"
    assert result.timeline_entries > 0
    assert result.cleaned_up is True
    assert not Path(result.root).exists()
    assert not (home / ".canto").exists()


def test_scripted_demo_promotes_only_when_requested_and_can_be_kept():
    result = run_delegation_demo(promote=True, keep=True)
    try:
        assert result.status == "promoted"
        assert result.cleaned_up is False
        assert Path(result.repository, "src", "app.py").read_text() == "value = 2\n"
        assert Path(result.artifact_root, "proposal.diff").is_file()
        assert Path(result.state_file).is_file()
    finally:
        cleanup_delegation_demo(result.root)
