#!/usr/bin/env python3
"""Claude Code PreToolUse hook: the chairman's delegation-of-authority policy.

Tier 0/1 actions (local, disposable work; pushing its own feature branch; draft PRs)
are allowed silently. Tier 2 actions return "ask", so Claude Code prompts the person
(on their phone over Remote Control) and only they can approve. "Never" actions are
denied outright. The policy itself is in SKILL.md.

It also keeps the council commit gate (formerly commit_gate.py): in a repo with a
`.council/enforce-commit-gate` file, `git commit` needs a passing council review of the
exact staged diff. `COUNCIL_SKIP=1` no longer bypasses silently; it asks the person.

Wire it to Bash, PowerShell, Edit, Write, MultiEdit, NotebookEdit and Read (see README).
Output: nothing (allow), or a JSON permission decision on stdout.

This is a guardrail against mistakes, not a sandbox: it classifies commands with simple
parsing, so an agent determined to evade it could (e.g. by writing a script and running
it). The member sandboxes and council.py's after-run checks do not depend on it.
"""
from __future__ import annotations

import hashlib
import json
import os
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
AGENT_CLIS = {"codex", "agy", "claude", "gemini"}
CONFIG_NAMES = {"settings.json", "settings.local.json", "council.config.json", "claude.md",
                "agents.md", "gemini.md", ".gitignore", "package-lock.json", "yarn.lock",
                "pnpm-lock.yaml", "uv.lock", "poetry.lock", "cargo.lock"}
CONFIG_DIRS = {".claude", ".github", ".canto"}
SHELLS = {"bash", "sh", "zsh", "pwsh", "powershell", "cmd"}
PREFIX_WORDS = {"env", "command", "sudo", "exec", "time", "nohup", "&", ".", "call", "builtin"}
WRITE_VERBS = {"set-content", "sc", "out-file", "add-content", "ac", "tee", "tee-object", "cp",
               "copy", "copy-item", "cpi", "mv", "move", "move-item", "mi", "new-item", "ni",
               "truncate", "touch", "install", "ln", "new-itemproperty"}
DELETE_VERBS = {"rm", "rmdir", "del", "erase", "rd", "remove-item", "ri"}
GIT_BUILTINS = set("""add am annotate apply archive bisect blame branch bundle cat-file check-attr
check-ignore checkout cherry cherry-pick citool clean clone commit config count-objects describe
diff difftool fetch filter-branch format-patch fsck gc grep gui hash-object help init log ls-files
ls-remote ls-tree merge merge-base mergetool mv name-rev notes pull push range-diff rebase reflog
remote repack replace request-pull reset restore rev-list rev-parse revert rm shortlog show
show-branch show-ref sparse-checkout stash status submodule switch symbolic-ref tag update-index
update-ref verify-commit version whatchanged worktree write-tree maintenance var""".split())
GH_READ_ACTIONS = {"view", "list", "status", "diff", "checks", "download", "watch", "browse"}

# Per-evaluation state: branch switches earlier in a chained command.
_BRANCH_OVERRIDE: dict[str, str] = {}


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


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def norm_path(raw: str, cwd: Path) -> Path:
    """Absolute, normalised path. Strips quotes and NTFS alternate-data-stream suffixes."""
    p = raw.strip().strip("'\"").replace("\\", "/")
    p = re.sub(r"(?<=.)(?<!^[A-Za-z]):[^/]*$", "", p)  # foo.json::$DATA -> foo.json
    p = os.path.expanduser(p)
    path = Path(p)
    if not path.is_absolute():
        path = cwd / path
    return Path(os.path.normpath(str(path)))


def parts_lower(path: Path) -> list[str]:
    return [x.lower() for x in path.parts]


def is_forgery(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".verdict.json") or (
        name in ("gate.json", "approved.json") and ".council" in parts_lower(path))


def is_secret(path: Path) -> bool:
    lowered = parts_lower(path)
    name = path.name.lower()
    return (name == "auth.json" and ".codex" in lowered) or name in ("oauth_creds.json",
                                                                       ".credentials.json")


def is_config(path: Path) -> bool:
    return path.name.lower() in CONFIG_NAMES or any(d in parts_lower(path) for d in CONFIG_DIRS)


def repo_top(cwd: Path) -> Path:
    code, top = git(cwd, "rev-parse", "--show-toplevel")
    return Path(top) if code == 0 and top else cwd


def under_council(path: Path, cwd: Path) -> bool:
    council = Path(os.path.normpath(str(repo_top(cwd) / ".council")))
    try:
        return os.path.normcase(str(path)).startswith(os.path.normcase(str(council)) + os.sep) \
            or os.path.normcase(str(path)) == os.path.normcase(str(council))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# command splitting
# ---------------------------------------------------------------------------
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||&|\r?\n|\(|\)|\{|\}|\$\(|`)\s*")


def split_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def strip_prefixes(words: list[str]) -> list[str]:
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])
                     or words[0].lower() in PREFIX_WORDS):
        words = words[1:]
    return words


def base_name(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return re.sub(r"\.(exe|cmd|bat|ps1)$", "", name)


# ---------------------------------------------------------------------------
# git rules
# ---------------------------------------------------------------------------
def git_parts(words: list[str], cwd: Path):
    """For `git ...` return (cwd, subcommand, args, risky-options) or None."""
    if not words or base_name(words[0]) != "git":
        return None
    i, risky = 1, []
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            target = Path(words[i + 1])
            cwd = target if target.is_absolute() else cwd / target
            i += 2
        elif w == "-c" and i + 1 < len(words):
            if words[i + 1].lower().startswith("alias."):
                risky.append("-c alias.*")
            i += 2
        elif w.startswith(("--git-dir", "--work-tree", "--namespace", "--config-env")):
            risky.append(w.split("=")[0])
            i += 1 if "=" in w else 2
        elif w.startswith("-"):
            i += 1
        else:
            return cwd, w, words[i + 1:], risky
    return None


def current_branch(cwd: Path) -> str:
    key = os.path.normcase(str(repo_top(cwd)))
    if key in _BRANCH_OVERRIDE:
        return _BRANCH_OVERRIDE[key]
    return git(cwd, "rev-parse", "--abbrev-ref", "HEAD")[1]


def own_branch(name: str) -> bool:
    return name.startswith(OWN_BRANCH_PREFIXES) and name not in PROTECTED_BRANCHES


def is_pushed(cwd: Path, branch: str) -> bool:
    code, out = git(cwd, "for-each-ref", "--format=%(refname)", "refs/remotes")
    return code == 0 and any(r.endswith("/" + branch) for r in out.splitlines())


def split_flags(args: list[str], value_opts: set[str]) -> tuple[list[str], list[str]]:
    """Expand short clusters (-fu -> -f -u) and separate flags from positionals,
    skipping the values of options in value_opts."""
    flags, pos, skip = [], [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            name = a.split("=")[0]
            flags.append(name)
            if name in value_opts and "=" not in a:
                skip = True
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:]):
                flags.append("-" + ch)
                if "-" + ch in value_opts:
                    if j == len(a) - 2:
                        skip = True
                    break
        else:
            pos.append(a)
    return flags, pos


def check_push(cwd: Path, args: list[str]):
    flags, pos = split_flags(args, {"--repo", "--receive-pack", "--exec", "-o", "--push-option"})
    risky = {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror", "--all",
             "--tags", "--delete", "-d", "--prune", "--repo", "--receive-pack", "--exec"}
    if risky.intersection(flags):
        return "ask", "Force, delete, mirror, --all, --tags or --repo pushes need Rosie's approval (Tier 2)."
    refspecs = pos[1:] or [current_branch(cwd)]
    for spec in refspecs:
        if spec.startswith(("+", ":")):
            return "ask", f"Push refspec {spec} forces or deletes a branch (Tier 2)."
        src, _, dst = spec.partition(":")
        src = src.removeprefix("refs/heads/")
        dst = (dst or src).removeprefix("refs/heads/")
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
    code, out = git(cwd, "diff", "--numstat", "--no-renames", f"HEAD...{ref}")
    if code:
        return 0
    return sum(int(p) for row in out.splitlines() for p in row.split("\t")[:2] if p.isdigit())


def check_git(cwd: Path, sub: str, args: list[str], risky: list[str], command: str, depth: int = 0):
    if risky:
        return "ask", (f"git options {', '.join(risky)} can retarget or redefine the command; "
                       "Rosie approves (Tier 2).")
    if sub not in GIT_BUILTINS and depth < 3:
        code, expansion = git(cwd, "config", "--get", f"alias.{sub}")
        if code == 0 and expansion:
            if expansion.startswith("!"):
                return "ask", f"`git {sub}` is a shell alias ({expansion}); Rosie approves (Tier 2)."
            words = split_words(expansion)
            return check_git(cwd, words[0], words[1:] + args, [], command, depth + 1)
    branch = current_branch(cwd)
    on_protected = branch in PROTECTED_BRANCHES
    flags, pos = split_flags(args, {"-m", "-F", "-C", "-c", "--author", "--date", "-t",
                                    "--template", "--cleanup", "--trailer", "--fixup", "--squash",
                                    "-b", "-B", "--onto", "-X", "--strategy-option", "-s",
                                    "--strategy", "--message", "--file"})

    if sub in ("checkout", "switch"):
        new = None
        if {"-b", "-B", "-c", "-C"} & set(flags):
            for i, a in enumerate(args):
                if a in ("-b", "-B", "-c", "-C") and i + 1 < len(args):
                    new = args[i + 1]
        elif pos and "--" not in args and git(cwd, "rev-parse", "--verify", "--quiet",
                                              f"refs/heads/{pos[0]}")[0] == 0:
            new = pos[0]
        if new:
            _BRANCH_OVERRIDE[os.path.normcase(str(repo_top(cwd)))] = new
    if sub == "push":
        return check_push(cwd, args)
    if on_protected and sub in ("merge", "rebase", "cherry-pick", "revert", "am", "pull",
                                "commit", "reset", "apply"):
        return "ask", f"`git {sub}` while {branch} is checked out changes {branch} (Tier 2)."
    if sub in ("update-ref", "filter-branch", "filter-repo", "replace", "reflog") and \
            not (sub == "reflog" and (not pos or pos[0] == "show")):
        return "ask", f"`git {sub}` rewrites refs or history directly (Tier 2)."
    if sub == "symbolic-ref" and len(pos) >= 2:
        return "ask", "`git symbolic-ref` with a target rewrites HEAD (Tier 2)."
    if sub == "merge":
        for ref in pos:
            lines = merge_size(cwd, ref)
            if lines > MERGE_ASK_LINES:
                return "ask", (f"Merging {ref} brings in {lines} changed lines (over "
                               f"{MERGE_ASK_LINES}); Rosie approves merges that large (Tier 2).")
    if sub == "rebase" and is_pushed(cwd, branch):
        return "ask", "Rebasing a branch that has been pushed rewrites shared history (Tier 2)."
    if sub == "reset" and "--hard" in flags and is_pushed(cwd, branch):
        return "ask", "`git reset --hard` on a pushed branch can lose work (Tier 2)."
    if sub == "branch":
        if {"-D", "-d", "--delete", "-m", "-M", "--move", "-f", "--force", "-c", "-C",
                "--copy"} & set(flags):
            if not pos or any(not n.startswith("council/") or n in PROTECTED_BRANCHES for n in pos):
                return "ask", ("Deleting, renaming, copying or force-moving branches the council "
                               "did not create needs Rosie (Tier 2).")
    if sub == "tag" and {"-d", "--delete", "-f", "--force"} & set(flags):
        return "ask", "Deleting or moving tags needs Rosie's approval (Tier 2)."
    if sub == "worktree" and pos[:1] in (["remove"], ["move"]):
        targets = pos[1:]
        if not targets or any(not under_council(norm_path(t, cwd), cwd) for t in targets):
            return "ask", "Removing or moving a worktree the council did not create needs Rosie (Tier 2)."
    if sub == "clean" and ("-f" in flags or "--force" in flags) and not under_council(norm_path(".", cwd), cwd):
        return "ask", "`git clean -f` deletes untracked files in the main checkout (Tier 2)."
    if sub in ("checkout", "restore") and any(p in (".", ":/", "*", ":/*") for p in pos) \
            and not under_council(norm_path(".", cwd), cwd):
        return "ask", "Discarding local changes across the main checkout needs Rosie (Tier 2)."
    if sub == "stash" and pos[:1] in (["drop"], ["clear"]):
        return "ask", "Dropping stashes loses work (Tier 2)."
    if sub == "config" and ({"--global", "--system"} & set(flags)) and not (
            {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin"} & set(flags)):
        if len(pos) >= 2 or {"--unset", "--unset-all", "--add", "--replace-all", "--edit", "-e"} & set(flags):
            return "ask", "Changing global git config needs Rosie's approval (Tier 2)."
    if sub == "commit":
        return commit_gate(cwd, args, flags, pos, command)
    return None


def commit_gate(cwd: Path, args, flags, pos, command: str):
    top = repo_top(cwd)
    code, common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main_repo = Path(common).parent if code == 0 and common else top
    markers = (top / ".council" / "enforce-commit-gate", main_repo / ".council" / "enforce-commit-gate")
    if not any(m.is_file() for m in markers):
        return None  # gate not enabled for this repo (run folders alone don't enable it)
    if "COUNCIL_SKIP=1" in command:
        return "ask", "COUNCIL_SKIP=1 bypasses the council commit gate; Rosie decides (Tier 2)."
    unsafe = {"-a", "--all", "-i", "--include", "-o", "--only", "--amend", "-p", "--patch",
              "--interactive"} & set(flags)
    if unsafe or pos:
        return "deny", ("Council gate: commit exactly the reviewed staged change; no -a, --include, "
                        "--only, --amend, --patch or pathspecs.")
    stamp = top / ".council" / "approved.json"
    staged = subprocess.run(["git", "-C", str(top), "diff", "--cached", "--binary"], text=True,
                            encoding="utf-8", errors="replace", capture_output=True,
                            check=False).stdout
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
# other shell rules
# ---------------------------------------------------------------------------
def check_gh(words: list[str]):
    if len(words) < 3:
        return None
    group, action = words[1], words[2]
    if group == "pr":
        if action in ("merge", "ready", "close", "reopen", "review"):
            return "ask", f"`gh pr {action}` needs Rosie's approval (Tier 2)."
        if action == "create" and not {"--draft", "-d"} & set(words):
            return "ask", "Only draft PRs are delegated; a ready PR needs Rosie (Tier 2)."
    if group == "issue" and action not in GH_READ_ACTIONS:
        return "ask", f"`gh issue {action}` posts or changes things on GitHub (Tier 2)."
    if group in ("repo", "release", "secret", "variable", "workflow", "ruleset", "label", "gist",
                 "run", "cache", "codespace", "ssh-key", "gpg-key", "auth", "extension"):
        if action not in GH_READ_ACTIONS:
            return "ask", f"`gh {group} {action}` changes GitHub settings or state (Tier 2)."
    if group == "api":
        method, fields = "GET", False
        for i, w in enumerate(words[2:], start=2):
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if w in ("-X", "--method"):
                method = nxt.upper()
            elif w.startswith("--method="):
                method = w.split("=", 1)[1].upper()
            elif w.startswith("-X") and len(w) > 2:
                method = w[2:].upper()
            elif w in ("-f", "-F", "--field", "--raw-field", "--input") or \
                    w.startswith(("--field=", "--raw-field=", "--input=")) or \
                    (re.match(r"^-[fF].", w) is not None):
                fields = True
        if method != "GET" or fields:
            return "ask", "Writing `gh api` calls change GitHub state (Tier 2)."
    return None


def is_install(words: list[str]) -> bool:
    head = base_name(words[0])
    toks = [w.lower() for w in words[1:]]
    if head in ("npm", "pnpm", "yarn", "bun"):
        return bool({"i", "install", "add", "up", "update", "upgrade", "remove", "uninstall"} & set(toks))
    if head in ("pip", "pip3") or (head == "uv" and toks[:1] == ["pip"]):
        return bool({"install", "uninstall"} & set(toks))
    if re.match(r"^(py|python[\d.]*)$", head) and "-m" in toks:
        rest = toks[toks.index("-m") + 1:]
        return rest[:1] == ["pip"] and bool({"install", "uninstall"} & set(rest))
    if head in ("uv", "poetry", "pdm", "cargo", "go", "gem", "composer"):
        return bool(toks) and toks[0] in ("add", "remove", "update", "upgrade", "install", "get", "require")
    if head in ("winget", "choco", "scoop", "brew", "apt", "apt-get"):
        return bool(toks) and toks[0] in ("install", "upgrade", "uninstall", "remove")
    if head == "dotnet":
        return toks[:2] in (["add", "package"], ["remove", "package"])
    return head in ("install-module", "install-package", "update-module")


def write_targets(segment: str, words: list[str], cwd: Path) -> list[Path]:
    targets = [norm_path(m, cwd) for m in re.findall(r"(?<![0-9&])>>?\s*([^\s|;&<>]+)", segment)]
    head = base_name(words[0]) if words else ""
    if head in WRITE_VERBS or head in DELETE_VERBS or (head == "sed" and any(
            w.startswith("-i") or w == "--in-place" for w in words)):
        targets += [norm_path(w, cwd) for w in words[1:] if not w.startswith(("-", "/"))]
    return targets


def check_segment(segment: str, cwd: Path, command: str, depth: int = 0):
    words = strip_prefixes(split_words(segment))
    if not words:
        return None
    head = base_name(words[0])
    lowered = [w.lower() for w in words]

    # nested shells: bash -c "...", pwsh -Command "...", cmd /c ...
    if head in SHELLS and depth < 3:
        for i, w in enumerate(lowered):
            if w in ("-c", "-command", "/c", "/k") and i + 1 < len(words):
                return check_shell(" ".join(words[i + 1:]), cwd, depth + 1)

    if head in AGENT_CLIS or (head.startswith("python") and any("council.py" in w for w in lowered)):
        for w in lowered:
            if any(flag in w for flag in NEVER_FLAGS):
                return "deny", "Sandbox-bypass flags remove the members' fence; the policy never allows them."

    for w in words[1:]:
        if not w.startswith("-") and is_secret(norm_path(w, cwd)):
            return "deny", "Reading or copying CLI credentials is never delegated."

    for target in write_targets(segment, words, cwd):
        if is_forgery(target):
            return "deny", "Council verdict, gate and approval files are written only by council.py."
        if is_secret(target):
            return "deny", "CLI credential files are never touched by the chairman."
        if is_config(target):
            return "ask", f"Writing {target.name} changes config or governance (Tier 2)."

    parts = git_parts(words, cwd)
    if parts:
        return check_git(*parts, command)
    if head == "gh":
        return check_gh(words)
    if is_install(words):
        return "ask", "Adding, removing or upgrading dependencies needs Rosie's approval (Tier 2)."
    if head in DELETE_VERBS and any(w in ("-r", "-rf", "-fr", "-R", "/s") or w.lower().startswith("-rec")
                                    or (re.match(r"^-[a-zA-Z]*[rR]", w) is not None) for w in words[1:]):
        targets = [w for w in words[1:] if not w.startswith(("-", "/"))]
        if not targets or any(not under_council(norm_path(t, cwd), cwd) for t in targets):
            return "ask", "Recursive deletes outside .council/ need Rosie's approval (Tier 2)."
    return None


def check_shell(command: str, cwd: Path, depth: int = 0):
    # Backslashes are path separators on Windows; posix shlex would eat them.
    text = command.replace("\\", "/")
    strictest = None
    for segment in SEGMENT_SPLIT.split(text):
        hit = check_segment(segment.strip(), cwd, command, depth)
        if hit and (strictest is None or (hit[0] == "deny" and strictest[0] != "deny")):
            strictest = hit
    return strictest


def check_file_tool(raw: str, cwd: Path):
    if not raw:
        return None
    path = norm_path(raw, cwd)
    if is_forgery(path):
        return "deny", "Council verdict, gate and approval files are written only by council.py."
    if is_secret(path):
        return "deny", "CLI credential files are never edited by the chairman."
    if is_config(path):
        return "ask", f"Editing {path.name} changes config or governance (Tier 2)."
    return None


def evaluate(payload: dict):
    _BRANCH_OVERRIDE.clear()
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or ".")
    if tool in ("Bash", "PowerShell"):
        return check_shell(tool_input.get("command", ""), cwd)
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return check_file_tool(tool_input.get("file_path") or tool_input.get("notebook_path") or "", cwd)
    if tool == "Read" and is_secret(norm_path(tool_input.get("file_path") or "", cwd)):
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
