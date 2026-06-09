from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from canto.core.capability_manifest import CapabilityManifestValidator


class CapabilityScaffoldError(ValueError):
    """Raised when a capability scaffold cannot be created."""


SCAFFOLD_FILES = (
    "manifest.yaml",
    "README.md",
    "skills/{name}/skill.yaml",
    "skills/{name}/providers/local/provider.yaml",
    "skills/{name}/providers/local/run.py",
    "tests/test_provider.py",
)


def manifest_template(name: str) -> str:
    return yaml.safe_dump(
        {
            "name": name,
            "version": "0.1.0",
            "description": f"TODO: describe the {name} capability.",
            "skills": [name],
            "providers": [f"{name}.local"],
            "tools": [],
            "dependencies": {},
            "risk": {"level": "low", "requires_approval": False},
            "artifacts": [],
        },
        sort_keys=False,
    )


def skill_template(name: str) -> str:
    return yaml.safe_dump(
        {
            "name": name,
            "version": "0.1.0",
            "description": f"TODO: describe the {name} skill.",
            "inputs": {},
            "outputs": {},
            "providers": ["local"],
            "risk_level": 1,
        },
        sort_keys=False,
    )


def provider_template(name: str) -> str:
    return yaml.safe_dump(
        {
            "name": "local",
            "skill": name,
            "version": "0.1.0",
            "description": f"Placeholder local provider for {name}.",
            "runner": {"type": "python", "entrypoint": "run.py"},
            "inputs": {},
            "outputs": {},
            "tools": [],
            "dependencies": {},
            "permissions": {
                "network_read": False,
                "network_write": False,
                "filesystem_write": [],
                "destructive": False,
            },
            "risk_level": 1,
        },
        sort_keys=False,
    )


def runner_template(name: str) -> str:
    return f'''from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(
        json.dumps(
            {{
                "status": "completed",
                "summary": "Placeholder provider for {name} completed.",
                "artifacts": {{}},
                "warnings": ["Replace the placeholder provider logic."],
                "needs_human": True,
            }}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def test_template(name: str) -> str:
    return f'''import json
import subprocess
import sys
from pathlib import Path


def test_placeholder_provider_completes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    runner = root / "skills" / "{name}" / "providers" / "local" / "run.py"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({{"inputs": {{}}, "artifact_dir": str(tmp_path)}}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(runner), str(request)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "completed"
    assert result["artifacts"] == {{}}
'''


def readme_template(name: str) -> str:
    return f"""# {name}

Local Canto capability scaffold.

Replace the placeholder provider and tests before production use.
"""


def scaffold_file_content(name: str, template: str) -> str:
    contents = {
        "manifest.yaml": manifest_template(name),
        "README.md": readme_template(name),
        f"skills/{name}/skill.yaml": skill_template(name),
        f"skills/{name}/providers/local/provider.yaml": provider_template(name),
        f"skills/{name}/providers/local/run.py": runner_template(name),
        "tests/test_provider.py": test_template(name),
    }
    return contents[template.format(name=name)]


def scaffold_capability_structure(
    name: str, output_dir: str | Path = "."
) -> Path:
    if not CapabilityManifestValidator.NAME_PATTERN.fullmatch(name):
        raise CapabilityScaffoldError(
            "name must be a lowercase snake_case or hyphen-safe package name"
        )

    destination = Path(output_dir).expanduser().resolve() / name
    if destination.exists():
        raise CapabilityScaffoldError(
            f"Scaffold destination already exists: {destination}"
        )

    created = False
    try:
        destination.mkdir(parents=True)
        created = True
        for template in SCAFFOLD_FILES:
            path = destination / template.format(name=name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(scaffold_file_content(name, template), encoding="utf-8")
    except OSError as exc:
        if created:
            shutil.rmtree(destination, ignore_errors=True)
        raise CapabilityScaffoldError(f"Cannot create scaffold {destination}: {exc}") from exc
    return destination
