from __future__ import annotations

import subprocess
from pathlib import Path


def test_mvp_stability_demo():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["sh", str(root / "scripts" / "demo-mvp-v1.sh")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Canto MVP v1 stability demo passed." in result.stdout
