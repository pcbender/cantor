from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from canto.core.dependencies import check_dependencies
from canto.core.registry import Registry


def select_manifests(registry: Registry, inputs: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    skill_name = inputs.get("skill")
    provider_name = inputs.get("provider")
    tool_name = inputs.get("tool")

    if tool_name:
        if skill_name or provider_name:
            raise ValueError("tool cannot be combined with skill or provider")
        tool = registry.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")
        return f"tool {tool_name}", [tool]

    if not skill_name:
        raise ValueError("Provide either tool or skill")
    skill = registry.skills.get(skill_name)
    if not skill:
        raise ValueError(f"Unknown skill: {skill_name}")

    if provider_name:
        provider = registry.providers.get((skill_name, provider_name))
        if not provider:
            raise ValueError(f"Unknown provider: {skill_name}.{provider_name}")
        manifests = [provider]
        target = f"provider {skill_name}.{provider_name}"
    else:
        manifests = [
            provider
            for (registered_skill, _), provider in sorted(registry.providers.items())
            if registered_skill == skill_name
        ]
        target = f"skill {skill_name}"

    tool_names = sorted({name for manifest in manifests for name in manifest.get("tools", [])})
    for name in tool_names:
        tool = registry.tools.get(name)
        if not tool:
            raise ValueError(f"Registered provider refers to unknown tool: {name}")
        manifests.append(tool)
    return target, manifests


def markdown_report(target: str, report: dict[str, Any]) -> str:
    missing = report["missing"]
    plan = report["install_plan"]
    system = "\n".join(f"- `{name}`" for name in missing["system"]) or "- None"
    python = "\n".join(f"- `{name}`" for name in missing["python"]) or "- None"
    actions = (
        "\n".join(
            f"- `{item['command']}`"
            + (" (approval required)" if item["approval_required"] else "")
            for item in plan
        )
        or "- None"
    )
    return f"""# Dependency Report

Target: {target}

Status: **{report["status"]}**

## Missing system dependencies

{system}

## Missing Python dependencies

{python}

## Install plan

{actions}
"""


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    root = Path(request["canto_root"]).resolve()
    artifact_dir = Path(request["artifact_dir"]).resolve()
    registry = Registry(root / "skills", root / "tools")
    target, manifests = select_manifests(registry, request["inputs"])
    report = {"target": target, **check_dependencies(manifests)}

    (artifact_dir / "dependency_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "dependency_report.md").write_text(
        markdown_report(target, report),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": f"Dependency check for {target}: {report['status']}.",
                "artifacts": {
                    "dependency_report_json": "dependency_report.json",
                    "dependency_report_md": "dependency_report.md",
                },
                "warnings": [],
                "needs_human": bool(report["install_plan"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
