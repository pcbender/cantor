from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


JOB_ID_PATTERN = re.compile(r"job_[0-9]{8}_[a-f0-9]{6}")


def load_inventory(root: Path, source_job_id: str) -> dict[str, Any]:
    if not JOB_ID_PATTERN.fullmatch(source_job_id):
        raise ValueError("source_job_id is not a valid Canto job ID")
    inventory_path = root / "work" / "jobs" / source_job_id / "inventory.json"
    if not inventory_path.is_file():
        raise ValueError(f"Source job does not contain inventory.json: {source_job_id}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory, dict) or not isinstance(inventory.get("pages"), list):
        raise ValueError("Source inventory has an invalid structure")
    return inventory


def assess(inventory: dict[str, Any], source_job_id: str, target_cms: str) -> dict[str, Any]:
    pages = inventory["pages"]
    media = inventory.get("media", [])
    warnings = list(inventory.get("warnings", []))
    groups = Counter(str(page.get("probable_type", "unknown")) for page in pages)
    pages_without_titles = sum(not str(page.get("title", "")).strip() for page in pages)
    pages_without_descriptions = sum(not str(page.get("meta_description", "")).strip() for page in pages)

    risks = []
    if warnings:
        risks.append("The source inventory contains crawl warnings that require review.")
    if pages_without_titles:
        risks.append(f"{pages_without_titles} pages do not have a usable title.")
    if pages_without_descriptions:
        risks.append(f"{pages_without_descriptions} pages do not have a meta description.")
    if not pages:
        risks.append("No pages were inventoried; migration planning cannot proceed.")

    next_steps = [
        "Confirm the target CMS and required content model.",
        "Review probable content groups and map them to target content types.",
        "Validate media ownership, formats, and destination paths.",
        "Run content extraction before building an importer.",
    ]
    if target_cms != "unspecified":
        next_steps[0] = f"Define the content model and field mapping for {target_cms}."

    return {
        "source_job_id": source_job_id,
        "source_url": inventory.get("source_url", ""),
        "target_cms": target_cms,
        "summary": {
            "pages": len(pages),
            "media": len(media),
            "warnings": len(warnings),
            "pages_without_titles": pages_without_titles,
            "pages_without_descriptions": pages_without_descriptions,
        },
        "probable_content_groups": dict(sorted(groups.items())),
        "risks": risks,
        "recommended_next_steps": next_steps,
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    groups = (
        "\n".join(
            f"- {name}: {count}"
            for name, count in report["probable_content_groups"].items()
        )
        or "- None"
    )
    risks = "\n".join(f"- {item}" for item in report["risks"]) or "- None identified"
    next_steps = "\n".join(
        f"{index}. {item}"
        for index, item in enumerate(report["recommended_next_steps"], start=1)
    )
    return f"""# Migration Assessment

Source: {report["source_url"] or "Unknown"}
Source job: `{report["source_job_id"]}`
Target CMS: {report["target_cms"]}

## Inventory Summary

- Pages: {summary["pages"]}
- Media references: {summary["media"]}
- Crawl warnings: {summary["warnings"]}
- Pages without titles: {summary["pages_without_titles"]}
- Pages without meta descriptions: {summary["pages_without_descriptions"]}

## Probable Content Groups

{groups}

## Migration Risks

{risks}

## Recommended Next Steps

{next_steps}
"""


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    inputs = request["inputs"]
    root = Path(request["canto_root"]).resolve()
    artifact_dir = Path(request["artifact_dir"]).resolve()
    source_job_id = inputs["source_job_id"]
    target_cms = inputs.get("target_cms", "unspecified").strip() or "unspecified"
    inventory = load_inventory(root, source_job_id)
    report = assess(inventory, source_job_id, target_cms)

    (artifact_dir / "migration_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "migration_report.md").write_text(
        markdown_report(report),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": (
                    f"Assessed {report['summary']['pages']} pages and "
                    f"{report['summary']['media']} media references for migration."
                ),
                "artifacts": {
                    "migration_report_json": "migration_report.json",
                    "migration_report_md": "migration_report.md",
                },
                "warnings": report["risks"],
                "needs_human": True,
                "recommended_next_steps": report["recommended_next_steps"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
