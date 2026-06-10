import subprocess
from pathlib import Path


def test_release_demo_script_runs_end_to_end():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["bash", str(root / "scripts" / "demo-v2.2.sh")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "release_demo\t1.0.0\tlow" in result.stdout
    assert '"status": "completed"' in result.stdout
    assert "Canto v2.2 release demo passed." in result.stdout
