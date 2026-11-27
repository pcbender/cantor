#!/usr/bin/env python3
"""Claude Code PreToolUse hook: the chairman's delegation-of-authority policy.

Tier 0/1 actions (local, disposable work; pushing its own feature branch; draft PRs)
are allowed silently. Tier 2 actions return "ask", so Claude Code prompts the person
(on their phone over Remote Control) and only they can approve. "Never" actions are
denied outright. The policy itself is in SKILL.md.

It also keeps the council commit gate (formerly commit_gate.py): in a repo with a
`.council/enforce-commit-gate` file, `git commit` needs a passing council review of the exact staged
diff. `COUNCIL_SKIP=1` no longer bypasses silently; it asks the person.

Wire it to the Bash, PowerShell, Edit, Write and NotebookEdit tools (see README).
Output: nothing (allow), or a JSON permission decision on stdout.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

MERGE_ASK_LINES = 400
PROTECTED_BRANCHES = {"main", "master"}
OWN_BRANCH_PREFIXES = ("council/", "claude/")

NEVER_FLAGS = ("danger-full-access", "--dangerously-bypass-approvals-and-sandbox",
               "--dangerously-skip-permissions", "--yolo")
FORGERY_FILES = re.compile(r"(\.verdict\.json|(^|[\\/])gate\.json|approved\.json)$", re.I)
SECRET_FILES = re.compile(r"(\.codex[\\/]auth\.json|oauth_creds\.json|\.credentials\.json)", re.I)
FORGERY_WRITE = re.compile(
    r">>?\s*['\"]?[^\s'\"|;&]*(\.verdict|gate|approved)\.json"
    r"|\b(Set-Content|Out-File|Add-Content|tee|cp|copy|mv|move|Copy-Item|Move-Item|sed\s+-i)\b"
    r"[^|;&]*(\.verdict|\bgate|approved)\.json", re.I)
CONFIG_PATHS = re.compile(
    r"(^|[\\/])(\.claude|\.github)[\\/]|(^|[\\/])(settings(\.local)?\.json|council\.config\.json"
    r"|CLAUDE\.md|AGENTS\.md|GEMINI\.md|\.gitignore|package-lock\.json|yarn\.lock"
    r"|pnpm-lock\.yaml|uv\.lock|poetry\.lock|Cargo\.lock)$", re.I)
INSTALLERS = re.compile(
    r"^(npm|pnpm|yarn|bun)\s+(i|install|add|up|update|upgrade)\b|^(pip|pip3|uv\s+pip)\s+install\b"
    r"|^uv\s+(add|sync|lock)\b|^poetry\s+(add|update|install)\b|^cargo\s+(add|update|install)\b"
    r"|^(winget|choco|scoop)\s+(install|upgrade)\b|^python[\d.]*\s+-m\s+pip\s+install\b|^Install-Module\b",
    re.I)
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


def decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": kind,
                                   "permissionDecisionReason": reason}}


def git(cwd: Path, *args) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(cwd), *args], text=True, encoding="utf-8",
                              errors="replace", capture_output=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return done.returncode, done.stdout.strip()


def split_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def git_parts(words: list[str], cwd: Path) -> tuple[Path, str, list[str]] | None:
    """For a `git ...` command return (effective cwd, subcommand, remaining args)."""
    if not words or Path(words[0]).name.lower() not in ("git", "git.exe"):
        return None
    i = 1
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            target = Path(words[i + 1])
            cwd = target if target.is_absolute() else cwd / target
            i += 2
        elif w == "-c" and i + 1 < len(words):
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return cwd, w, words[i + 1:]
    return None


def current_branch(cwd: Path) -> str:
    return git(cwd, "rev-parse", "--abbrev-ref", "HEAD")[1]


def own_branch(name: str) -> bool:
    return name.startswith(OWN_BRANCH_PREFIXES) and name not in PROTECTED_BRANCHES


# ---------------------------------------------------------------------------
# git rules
# ---------------------------------------------------------------------------
def check_push(cwd: Path, args: list[str]) -> tuple[str, str] | None:
    flags = [a for a in args if a.startswith("-")]
    pos = [a for a in args if not a.startswith("-")]
    if any(f in ("-f", "--force", "--force-with-lease", "--mirror", "--all", "--tags", "--delete", "-d",
                 "--prune") or f.startswith("--force") for f in flags):
        return "ask", "Force, delete, mirror, --all or --tags pushes need Rosie's approval (Tier 2)."
    refspecs = pos[1:]
    if not refspecs:
        refspecs = [current_branch(cwd)]
    for spec in refspecs:
        if spec.startswith("+") or spec.startswith(":"):
            return "ask", f"Push refspec {spec} forces or deletes a branch (Tier 2)."
        dst = spec.split(":")[-1].removeprefix("refs/heads/")
        src = spec.split(":")[0].removeprefix("refs/heads/")
        if src == "HEAD":
            src = current_branch(cwd)
        if dst == "HEAD":
            dst = src
        if dst in PROTECTED_BRANCHES:
            return "ask", f"Pushing to {dst} needs Rosie's approval (Tier 2)."
        if not own_branch(dst):
            return "ask", (f"Pushing to {dst}, which is not a council/ or claude/ branch, "
                           "needs Rosie's approval (Tier 2).")
    return None


def merge_size(cwd: Path, ref: str) -> int:
    code, out = git(cwd, "diff", "--numstat", f"HEAD...{ref}")
    if code:
        return 0
    total = 0
    for row in out.splitlines():
        parts = row.split("\t")
        total += sum(int(p) for p in parts[:2] if p.isdigit())
    return total


def check_git(cwd: Path, sub: str, args: list[str], command: str) -> tuple[str, str] | None:
    branch = current_branch(cwd)
    on_protected = branch in PROTECTED_BRANCHES
    if sub == "push":
        return check_push(cwd, args)
    if sub in ("merge", "rebase", "cherry-pick", "revert", "am", "pull") and on_protected:
        return "ask", f"`git {sub}` while {branch} is checked out changes {branch} (Tier 2)."
    if sub == "commit" and on_protected:
        return "ask", f"Committing directly on {branch} needs Rosie's approval (Tier 2)."
    if sub == "merge":
        refs = [a for a in args if not a.startswith("-")]
        for ref in refs:
            lines = merge_size(cwd, ref)
            if lines > MERGE_ASK_LINES:
                return "ask", (f"Merging {ref} brings in {lines} changed lines (over "
                               f"{MERGE_ASK_LINES}); Rosie approves merges that large (Tier 2).")
    if sub == "rebase" and not on_protected:
        upstream = git(cwd, "rev-parse", "--abbrev-ref", "@{upstream}")[0] == 0
        if upstream:
            return "ask", "Rebasing a branch that has been pushed rewrites shared history (Tier 2)."
    if sub == "reset" and "--hard" in args:
        if git(cwd, "rev-parse", "--abbrev-ref", "@{upstream}")[0] == 0 or on_protected:
            return "ask", "`git reset --hard` on a pushed or protected branch can lose work (Tier 2)."
    if sub == "branch" and any(a in ("-D", "-d", "--delete", "-m", "-M", "--move") for a in args):
        names = [a for a in args if not a.startswith("-")]
        if not names or any(not n.startswith("council/") for n in names):
            return "ask", "Deleting or renaming branches the council did not create needs Rosie (Tier 2)."
    if sub == "tag" and any(a in ("-d", "--delete", "-f", "--force") for a in args):
        return "ask", "Deleting or moving tags needs Rosie's approval (Tier 2)."
    if sub == "worktree" and args[:1] == ["remove"]:
        targets = [a for a in args[1:] if not a.startswith("-")]
        if any(".council" not in t.replace("\\", "/").split("/") for t in targets):
            return "ask", "Removing a worktree the council did not create needs Rosie (Tier 2)."
    if sub == "clean" and any(a.startswith("-") and "f" in a for a in args):
        if ".council" not in str(cwd):
            return "ask", "`git clean -f` deletes untracked files in the main checkout (Tier 2)."
    if sub in ("checkout", "restore") and ("." in args or "--" in args and args[-1] == "."):
        if ".council" not in str(cwd):
            return "ask", "Discarding all local changes in the main checkout needs Rosie (Tier 2)."
    if sub == "config" and "--global" in args and not any(a in ("--get", "--list", "-l") for a in args):
        return "ask", "Changing global git config needs Rosie's approval (Tier 2)."
    if sub == "commit":
        return commit_gate(cwd, args, command)
    return None


def commit_gate(cwd: Path, args: list[str], command: str) -> tuple[str, str] | None:
    code, top = git(cwd, "rev-parse", "--show-toplevel")
    repo = Path(top) if code == 0 and top else cwd
    if not (repo / ".council" / "enforce-commit-gate").is_file():
        return None  # gate not enabled for this repo (run folders alone don't enable it)
    if "COUNCIL_SKIP=1" in command:
        return "ask", "COUNCIL_SKIP=1 bypasses the council commit gate; Rosie decides (Tier 2)."
    if any(a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a[1:])
           for a in args):
        return "deny", ("Council gate: stage files explicitly instead of `git commit -a`, so the "
                        "reviewed change is exactly what gets committed.")
    stamp = repo / ".council" / "approved.json"
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--binary"],
                                     text=True, encoding="utf-8", errors="replace",
                                     capture_output=True, check=False).stdout
    fingerprint = hashlib.sha256(staged.encode("utf-8")).hexdigest()
    if not stamp.is_file():
        return "deny", "Council gate: no passing council review here. Run /council review first."
    try:
        approved = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        approved = {}
    if approved.get("staged_fingerprint") != fingerprint:
        return "deny", ("Council gate: the staged change differs from what the council approved. "
                        "Re-run /council review.")
    return None


# ---------------------------------------------------------------------------
# shell rules
# ---------------------------------------------------------------------------
def check_segment(segment: str, cwd: Path, command: str) -> tuple[str, str] | None:
    words = split_words(segment)
    # strip leading VAR=value assignments
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]
    if not words:
        return None
    parts = git_parts(words, cwd)
    if parts:
        return check_git(*parts, command)
    head = Path(words[0]).name.lower()
    rest = " ".join(words)
    if head in ("gh", "gh.exe") and len(words) >= 3:
        group, action = words[1], words[2]
        if group == "pr" and action in ("merge", "ready", "close", "reopen"):
            return "ask", f"`gh pr {action}` needs Rosie's approval (Tier 2)."
        if group == "pr" and action == "create" and "--draft" not in words and "-d" not in words:
            return "ask", "Only draft PRs are delegated; a ready PR needs Rosie (Tier 2)."
        if group in ("repo", "release", "secret", "variable", "workflow", "api", "ruleset"):
            if not (group == "api" and not any(w in ("-X", "--method", "-f", "-F", "--field",
                                                     "--raw-field", "--input") for w in words)):
                return "ask", f"`gh {group} {action}` changes GitHub settings or state (Tier 2)."
    if INSTALLERS.search(rest):
        return "ask", "Adding or upgrading dependencies needs Rosie's approval (Tier 2)."
    if head in ("rm", "rmdir", "del", "remove-item", "ri", "rd") and \
            any(w.lower() in ("-r", "-rf", "-fr", "-recurse", "/s") or w.lower().startswith("-r")
                for w in words[1:]):
        targets = [w for w in words[1:] if not w.startswith("-") and not w.startswith("/")]
        if not targets or any(".council" not in t.replace("\\", "/") for t in targets):
            return "ask", "Recursive deletes outside .council/ need Rosie's approval (Tier 2)."
    return None


def check_shell(command: str, cwd: Path) -> tuple[str, str] | None:
    lowered = command.lower()
    for flag in NEVER_FLAGS:
        if flag in lowered:
            return "deny", f"`{flag}` removes the members' sandbox; the policy never allows it."
    if SECRET_FILES.search(command):
        return "deny", "Reading or copying CLI credentials is never delegated."
    if FORGERY_WRITE.search(command):
        return "deny", "Council verdict, gate and approval files are written only by council.py."
    strictest = None
    for segment in SEGMENT_SPLIT.split(command):
        hit = check_segment(segment.strip(), cwd, command)
        if hit and (strictest is None or (hit[0] == "deny" and strictest[0] != "deny")):
            strictest = hit
    return strictest


def check_file_tool(path: str) -> tuple[str, str] | None:
    if not path:
        return None
    if FORGERY_FILES.search(path):
        return "deny", "Council verdict, gate and approval files are written only by council.py."
    if SECRET_FILES.search(path):
        return "deny", "CLI credential files are never edited by the chairman."
    if CONFIG_PATHS.search(path):
        return "ask", f"Editing {Path(path).name} changes config or governance (Tier 2)."
    return None


def evaluate(payload: dict) -> tuple[str, str] | None:
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or ".")
    if tool in ("Bash", "PowerShell"):
        return check_shell(tool_input.get("command", ""), cwd)
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return check_file_tool(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if tool == "Read" and SECRET_FILES.search(tool_input.get("file_path") or ""):
        return "deny", "Reading CLI credentials is never delegated."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    hit = evaluate(payload)
    if hit:
        print(json.dumps(decision(*hit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
