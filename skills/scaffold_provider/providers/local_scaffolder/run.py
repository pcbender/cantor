from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
        raise ValueError("Names must be lowercase snake_case and 2-64 characters")
    return value


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    artifact_dir = Path(request["artifact_dir"])
    inputs = request["inputs"]
    skill = safe_name(inputs["skill"])
    provider = safe_name(inputs["provider"])
    description = inputs.get("description", "TODO provider description")
    manifest = f"""name: {provider}
skill: {skill}
version: 0.1.0
description: {description}
runner:
  type: python
  entrypoint: run.py
inputs: {{}}
outputs: {{}}
dependencies:
  system: [python3]
permissions:
  destructive: false
risk_level: 1
"""
    runner = '''from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps({"status": "completed", "summary": "TODO", "artifacts": {}, "warnings": [], "needs_human": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    (artifact_dir / "provider.yaml").write_text(manifest, encoding="utf-8")
    (artifact_dir / "run.py").write_text(runner, encoding="utf-8")
    (artifact_dir / "README.md").write_text(f"# {skill}.{provider}\n\nUnregistered Canto provider scaffold.\n", encoding="utf-8")
    (artifact_dir / "test_provider.py").write_text("def test_provider_placeholder():\n    assert True\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "summary": f"Created unregistered scaffold for {skill}.{provider}.", "artifacts": {"scaffold_manifest": "provider.yaml", "scaffold_runner": "run.py", "scaffold_readme": "README.md", "scaffold_test": "test_provider.py"}, "warnings": ["Scaffold is not registered."], "needs_human": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

