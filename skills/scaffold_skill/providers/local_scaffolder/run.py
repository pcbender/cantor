from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
        raise ValueError("Skill name must be lowercase snake_case and 2-64 characters")
    return value


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    artifact_dir = Path(request["artifact_dir"])
    inputs = request["inputs"]
    skill = safe_name(inputs["skill"])
    description = inputs.get("description", "TODO skill description")
    domain = safe_name(inputs.get("domain", "general"))
    manifest = f"""name: {skill}
version: 0.1.0
description: {description}
domain: {domain}
inputs: {{}}
outputs: {{}}
providers: []
risk_level: 1
"""
    (artifact_dir / "skill.yaml").write_text(manifest, encoding="utf-8")
    (artifact_dir / "README.md").write_text(f"# {skill}\n\nUnregistered Canto skill scaffold.\n", encoding="utf-8")
    (artifact_dir / "test_skill.py").write_text("def test_skill_placeholder():\n    assert True\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": f"Created unregistered scaffold for skill {skill}.",
                "artifacts": {
                    "scaffold_manifest": "skill.yaml",
                    "scaffold_readme": "README.md",
                    "scaffold_test": "test_skill.py",
                },
                "warnings": ["Scaffold is not registered."],
                "needs_human": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
