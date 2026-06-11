from __future__ import annotations

from pathlib import Path

from canto.core.delegation_review import DelegationReviewService
from canto.core.delegation_review_summary import DelegationReviewSummaryService
from tests.test_delegation_review import capture


def test_review_summary_reports_evidence_and_acceptance_readiness(tmp_path):
    service, workspaces, _, result = capture(tmp_path)
    summary = DelegationReviewSummaryService(service, workspaces).summarize("task_1")
    assert summary.result_revision == result.revision
    assert summary.changed_files == ["src/app.py"]
    assert summary.patch_additions == 1
    assert summary.patch_deletions == 1
    assert summary.artifact_checksums_valid is True
    assert summary.acceptance_ready is True
    assert summary.promotion_ready is False
    assert summary.blockers == []


def test_review_summary_reports_checksum_and_workspace_blockers(tmp_path):
    service, workspaces, workspace, _ = capture(tmp_path)
    artifact = workspace.parent / "artifacts" / "revision-1" / "summary.md"
    artifact.chmod(0o644)
    artifact.write_text("tampered\n")
    (workspace / "src" / "app.py").write_text("value = 3\n")

    summary = DelegationReviewSummaryService(service, workspaces).summarize("task_1")
    assert summary.acceptance_ready is False
    assert any("checksum invalid" in blocker for blocker in summary.blockers)
    assert "Workspace changed after result capture" in summary.blockers


def test_review_summary_reports_promotion_readiness_after_acceptance(tmp_path):
    service, workspaces, _, _ = capture(tmp_path)
    DelegationReviewService(service, workspaces).accept("task_1", "reviewer")
    summary = DelegationReviewSummaryService(service, workspaces).summarize("task_1")
    assert summary.acceptance_ready is False
    assert summary.promotion_ready is True
