#!/usr/bin/env python3
"""Council member runner — salvaged from Cantor's CliExecutor.

Runs one council member (codex, gemini via Antigravity `agy`, or claude) headless
on your subscription login, captures its answer to a file, and — in review mode —
parses a structured verdict.

Stdlib only. Native Windows first; also works on macOS/Linux.

Usage:
  python council.py check
  python council.py consult --member codex  --brief .council/runs/<id>/brief.md  # how would you approach it?
  python council.py ask     --member codex  --brief .council/runs/<id>/brief.md  # open question
  python council.py review  --member gemini --brief .council/runs/<id>/brief.md
  python council.py gate    --dir .council/runs/<id>      # combine verdicts, stamp the diff
  python council.py task    --member codex  --brief .council/runs/<id>/task.md [--base BRANCH]
  python council.py cleanup --dir .council/runs/<id> [--member codex]

Members are read-only in consult/ask/review. In `task` (write mode) one member edits files
inside its own git worktree under .council/worktrees/; it cannot commit, push or write
outside that worktree, and the runner checks afterwards that it didn't.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
CONFIG_PATH = SKILL_ROOT / "council.config.json"

# ---------------------------------------------------------------------------
# Environment scrubbing (from Cantor cli_env.py)
# Cantor's allowlist was POSIX-only (HOME, PATH, TERM...). On native Windows the
# CLIs also need USERPROFILE / APPDATA / SystemRoot etc. or they can't find their
# auth files or even start. Those are added here.
# ---------------------------------------------------------------------------
SAFE_ENV_KEYS = {
    "HOME", "LANG", "LC_ALL", "PATH", "TERM", "TZ", "TMPDIR",
    # Windows essentials
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMROOT", "SYSTEMDRIVE",
    "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERNAME", "COMPUTERNAME",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
}
# Never leak API keys into a subscription worker: if one is present the CLI may
# silently switch to metered API billing.
BLOCKED_ENV_KEYS = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CODEX_API_KEY", "CODEX_BASE_URL",
    "GEMINI_API_KEY", "GEMINI_BASE_URL", "GOOGLE_API_KEY", "GOOGLE_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
}


def scrubbed_env() -> dict[str, str]:
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in SAFE_ENV_KEYS and upper not in BLOCKED_ENV_KEYS:
            env[key] = value
    env.setdefault("NO_COLOR", "1")
    return env


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "timeout_seconds": 900,
    "members": {
        "codex": {"enabled": True, "executable": "codex", "model": None, "extra_args": [],
                  "role": "Adversarial code reviewer: correctness, edge cases, bugs."},
        "gemini": {"enabled": True, "executable": "agy", "model": None, "extra_args": [],
                   "role": "Whole-repo critic: architecture, consistency, what was missed."},
        "claude": {"enabled": False, "executable": "claude", "model": None, "extra_args": [],
                   "role": "Fresh-context second opinion."},
    },
}


def load_config() -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.is_file():
        user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["timeout_seconds"] = user.get("timeout_seconds", config["timeout_seconds"])
        for name, values in user.get("members", {}).items():
            config["members"].setdefault(name, {}).update(values)
    return config


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    member: str
    ok: bool
    text: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    quota_hit: bool = False
    auth_problem: bool = False
    used_pty: bool = False
    denied: str = ""
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


class MemberUnavailable(RuntimeError):
    pass


def looks_like_quota(text: str) -> bool:  # Cantor map_quota
    t = text.lower()
    return any(s in t for s in ("rate limit", "quota", "usage limit", "resource_exhausted"))


def looks_like_auth(text: str) -> bool:
    t = text.lower()
    return any(s in t for s in ("authentication required", "not logged in", "please log in",
                                "login required", "unauthorized"))


# ---------------------------------------------------------------------------
# Adapters (from Cantor CliExecutor). Read-only by default; write=True is the
# task mode, where a member may edit files inside one worktree and nothing else.
# ---------------------------------------------------------------------------
class Adapter:
    name = ""
    label = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def executable(self) -> str:
        exe = self.cfg.get("executable") or self.name
        resolved = shutil.which(exe)
        if not resolved:
            raise MemberUnavailable(f"{self.label} not found on PATH: {exe}")
        return resolved

    def check_auth(self) -> str:
        return "not checked"

    def build(self, prompt_file: Path, workspace: Path, out_file: Path,
              write: bool = False) -> tuple[list[str], str | None]:
        """Return (argv, stdin_text)."""
        raise NotImplementedError

    def read_answer(self, stdout: str, out_file: Path) -> str:
        return stdout


class CodexAdapter(Adapter):
    name, label = "codex", "Codex CLI"

    def check_auth(self) -> str:
        auth = Path.home() / ".codex" / "auth.json"
        if not auth.is_file():
            raise MemberUnavailable("Codex is not logged in (run `codex login`).")
        try:
            data = json.loads(auth.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemberUnavailable(f"Cannot read Codex auth state: {exc}")
        if data.get("auth_mode") != "chatgpt":
            raise MemberUnavailable("Codex is not using ChatGPT subscription auth.")
        if data.get("OPENAI_API_KEY"):
            raise MemberUnavailable("Codex auth contains an API key (would bill the API).")
        return "ChatGPT subscription"

    def build(self, prompt_file, workspace, out_file, write=False):
        # workspace-write confines writes to `workspace` (tested on Windows: no writes to
        # the parent folder or the main checkout, and no `git add`/`commit`, because a
        # linked worktree's git metadata lives outside it). Network stays off.
        sandbox = "workspace-write" if write else "read-only"
        argv = [self.executable(), "exec", "--sandbox", sandbox,
                "--skip-git-repo-check", "--cd", str(workspace),
                "--output-last-message", str(out_file)]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        argv += list(self.cfg.get("extra_args", []))
        argv.append("-")  # prompt on stdin: no argv length limit on Windows
        return argv, prompt_file.read_text(encoding="utf-8")

    def read_answer(self, stdout, out_file):
        if out_file.is_file() and out_file.read_text(encoding="utf-8").strip():
            return out_file.read_text(encoding="utf-8")
        return stdout


class ClaudeAdapter(Adapter):
    name, label = "claude", "Claude Code CLI"

    def check_auth(self) -> str:
        try:
            done = subprocess.run([self.executable(), "auth", "status"], text=True,
                                  capture_output=True, timeout=15, env=scrubbed_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MemberUnavailable(f"Cannot inspect Claude auth: {exc}")
        text = (done.stdout + done.stderr).lower()
        if done.returncode:
            raise MemberUnavailable("Claude CLI is not logged in.")
        if "api key" in text or "apikey" in text:
            raise MemberUnavailable("Claude CLI appears to be on API-key auth.")
        return "claude.ai subscription"

    def build(self, prompt_file, workspace, out_file, write=False):
        if write:
            raise MemberUnavailable("Write mode is only supported for codex and gemini.")
        argv = [self.executable(), "--print", "--input-format", "text",
                "--output-format", "text", "--permission-mode", "plan",
                "--no-session-persistence"]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        argv += list(self.cfg.get("extra_args", []))
        return argv, prompt_file.read_text(encoding="utf-8")


class GeminiAgyAdapter(Adapter):
    """Gemini via Antigravity CLI (`agy`). Replaces Cantor's GeminiCliAdapter:
    Gemini CLI stopped serving Google AI Pro/Ultra accounts on 2026-06-18.

    The prompt is NOT passed on argv (Windows ~32K limit). agy is told to read the
    brief file from the workspace instead.
    """
    name, label = "gemini", "Antigravity CLI (agy)"

    def check_auth(self) -> str:
        return "cached agy login (run `agy` once interactively if this fails)"

    def build(self, prompt_file, workspace, out_file, write=False):
        if write:
            # Headless accept-edits (tested): file edits inside --add-dir are allowed,
            # edits outside it and ALL shell commands are auto-denied, and a denial ends
            # the run. The prompt goes inline so agy needs no access to the run folder
            # (where verdict files live).
            prompt = prompt_file.read_text(encoding="utf-8")
            if len(prompt) > MAX_INLINE_PROMPT:
                raise MemberUnavailable(
                    f"Task prompt is {len(prompt)} chars; agy write mode passes it inline "
                    f"(limit {MAX_INLINE_PROMPT}). Shorten the brief and point at files.")
            argv = [self.executable(), "--print", prompt, "--add-dir", str(workspace),
                    "--mode", "accept-edits", "--sandbox"]
        else:
            instruction = (
                f"Read the file at {prompt_file} and do exactly what it asks. "
                "Do not modify any files. Do not run shell commands: in this mode they are "
                "denied and end your run, so use your file-reading tools only. "
                "Reply with your answer only."
            )
            # --mode plan enforces read-only instead of relying on the instruction alone.
            # The brief's folder is added too: headless agy auto-denies reads outside
            # its workspace (e.g. reviewing a worktree with the brief in the main repo).
            argv = [self.executable(), "--print", instruction, "--add-dir", str(workspace),
                    "--add-dir", str(prompt_file.parent), "--mode", "plan"]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        argv += list(self.cfg.get("extra_args", []))
        return argv, None


ADAPTERS = {"codex": CodexAdapter, "gemini": GeminiAgyAdapter, "claude": ClaudeAdapter}
WRITE_MEMBERS = ("codex", "gemini")
MAX_INLINE_PROMPT = 24000  # Windows command lines top out at 32,767 chars
AGY_DENIED = re.compile(r"no output produced.*?required the \"(\w+)\" permission", re.S)


# ---------------------------------------------------------------------------
# Execution, with the agy non-TTY workaround
# ---------------------------------------------------------------------------
def _run_plain(argv, stdin_text, cwd, timeout):
    return subprocess.run(argv, input=stdin_text, cwd=cwd, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, timeout=timeout,
                          env=scrubbed_env(), check=False)


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def _run_pty(argv, cwd, timeout) -> tuple[str, int]:
    """Run under a pseudo-terminal. Windows: pywinpty (`pip install pywinpty`).
    POSIX: stdlib pty."""
    if os.name == "nt":
        try:
            from winpty import PtyProcess  # type: ignore
        except ImportError as exc:
            raise MemberUnavailable(
                "agy printed nothing to a pipe (known non-TTY bug) and pywinpty is not "
                "installed. Fix: `pip install pywinpty`.") from exc
        proc = PtyProcess.spawn(subprocess.list2cmdline(argv), cwd=str(cwd),
                                env=scrubbed_env(), dimensions=(50, 400))
        chunks, start = [], time.time()
        while True:
            try:
                data = proc.read(4096)
            except EOFError:
                break
            if data:
                chunks.append(data)
            elif not proc.isalive():
                break
            if time.time() - start > timeout:
                proc.terminate(force=True)
                raise subprocess.TimeoutExpired(argv, timeout)
        code = proc.exitstatus if proc.exitstatus is not None else 0
        return ANSI.sub("", "".join(chunks)).replace("\r", ""), code
    import pty
    import select
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(argv[0], argv, scrubbed_env())
    chunks, start = [], time.time()
    while True:
        if time.time() - start > timeout:
            os.kill(pid, 9)
            raise subprocess.TimeoutExpired(argv, timeout)
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data.decode("utf-8", "replace"))
    _, status = os.waitpid(pid, 0)
    return ANSI.sub("", "".join(chunks)).replace("\r", ""), os.waitstatus_to_exitcode(status)


def run_member(name: str, prompt_file: Path, workspace: Path, out_dir: Path, cfg: dict,
               timeout: int, write: bool = False) -> RunResult:
    adapter = ADAPTERS[name](cfg)
    out_file = out_dir / f"{name}.raw.md"
    result = RunResult(member=name, ok=False)
    start = time.time()
    try:
        argv, stdin_text = adapter.build(prompt_file, workspace, out_file, write=write)
        try:
            done = _run_plain(argv, stdin_text, workspace, timeout)
            result.exit_code, result.stderr = done.returncode, done.stderr
            text = adapter.read_answer(done.stdout, out_file)
            if name == "gemini" and done.returncode == 0 and not text.strip():
                result.notes.append("Empty stdout on pipe; retried under a pseudo-terminal.")
                text, result.exit_code = _run_pty(argv, workspace, timeout)
                result.used_pty = True
        except subprocess.TimeoutExpired:
            result.timed_out = True
            text = ""
        result.text = text.strip()
        blob = f"{result.text}\n{result.stderr}"
        result.quota_hit = looks_like_quota(blob) and result.exit_code not in (0, None)
        result.auth_problem = looks_like_auth(blob) and result.exit_code not in (0, None)
        result.ok = bool(result.text) and result.exit_code == 0 and not result.timed_out
        denied = AGY_DENIED.search(result.text) if name == "gemini" else None
        if denied:
            result.ok = False
            result.denied = denied.group(1)
            result.notes.append(f"agy tried an action needing the '{denied.group(1)}' "
                                "permission; it was auto-denied and the run stopped.")
        if result.timed_out:
            result.notes.append(f"Timed out after {timeout}s.")
        elif not result.ok and not result.text:
            result.notes.append("No answer produced.")
    except MemberUnavailable as exc:
        result.notes.append(str(exc))
    result.seconds = round(time.time() - start, 1)
    return result


# ---------------------------------------------------------------------------
# Verdicts (new — Cantor's reviews were human-only decisions; this is the
# cross-vendor structured verdict Cantor explored but never shipped)
# ---------------------------------------------------------------------------
VERDICTS = ("pass", "revise", "reject")
SEVERITIES = ("blocker", "major", "minor", "nit")

REVIEW_INSTRUCTIONS = """
---
END YOUR REPLY with a single fenced ```json block, and nothing after it, matching:
{
  "verdict": "pass" | "revise" | "reject",
  "confidence": 0.0-1.0,
  "summary": "one or two sentences",
  "findings": [
    {"severity": "blocker"|"major"|"minor"|"nit",
     "file": "path or null", "line": number or null,
     "issue": "what is wrong", "fix": "concrete suggested fix"}
  ]
}
Use "reject" only if the approach itself is wrong. Use "revise" if any blocker or
major finding exists. Use "pass" otherwise. Do not invent findings to seem thorough.
"""

CONSULT_INSTRUCTIONS = """
---
You are being consulted BEFORE any work starts. Read the code you need to; do not edit
anything. Answer with these headings:
## Approach - the plan you would follow, as numbered steps
## Files - the files you would read or change, and why
## Risks - what could go wrong or is easy to miss
## Alternatives - other approaches worth considering and why you did not pick them
## Open questions - what you would ask the person before starting
## Difficulty - easy / medium / hard, and whether you would want to do this task yourself
Be concrete and point at real code. Disagree with the brief if it is heading the wrong way.
"""

WRITE_INSTRUCTIONS = """
---
WRITE MODE. You are working in a git worktree made for this task: {worktree}
Rules:
- Edit files only inside that folder. Writes anywhere else are blocked.
- Do NOT run git add, commit, push, merge, checkout or branch. The chairman reviews and
  commits your work.
- Do not touch these protected paths: {protected}
- Stay within the allowed paths if the brief lists any.
- {shell_note}
When you are done, reply with a report using these headings:
## Changed - each file and what you changed
## Tested - what you ran or checked, and the result (or "not run")
## Unsure - anything you are not confident about or left undone
"""

SHELL_NOTE = {
    "codex": "You may run commands (tests, linters) inside the worktree; network is off.",
    "gemini": "Do not run any shell commands: they are denied in this mode and end your run. "
              "Use your file tools only; the chairman will run the tests.",
}

PROTECTED_GLOBS = (
    ".git/**", ".github/**", ".claude/**", ".council/**", "**/council.config.json",
    "**/CLAUDE.md", "**/AGENTS.md", "**/GEMINI.md", ".gitignore", "**/settings.json",
    "**/settings.local.json", "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml",
    "**/uv.lock", "**/poetry.lock", "**/Cargo.lock", "**/.env", "**/.env.*",
)

JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_verdict(member: str, text: str) -> dict:
    blocks = JSON_BLOCK.findall(text)
    candidate = blocks[-1] if blocks else None
    if candidate is None:
        start, end = text.rfind("{"), text.rfind("}")
        candidate = text[start:end + 1] if 0 <= start < end else None
    try:
        data = json.loads(candidate) if candidate else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or data.get("verdict") not in VERDICTS:
        return {"member": member, "verdict": "unparseable", "confidence": 0.0,
                "summary": "Reviewer did not return a valid verdict block.", "findings": []}
    findings = []
    for f in data.get("findings") or []:
        if isinstance(f, dict):
            sev = f.get("severity") if f.get("severity") in SEVERITIES else "minor"
            findings.append({"severity": sev, "file": f.get("file"), "line": f.get("line"),
                             "issue": str(f.get("issue", "")), "fix": str(f.get("fix", ""))})
    verdict = data["verdict"]
    # Consistency rule: a blocker/major finding can't coexist with "pass".
    if verdict == "pass" and any(f["severity"] in ("blocker", "major") for f in findings):
        verdict = "revise"
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return {"member": member, "verdict": verdict, "confidence": confidence,
            "summary": str(data.get("summary", "")), "findings": findings}


def combine(verdicts: list[dict]) -> str:
    """Gate policy: any reject -> reject; any revise/unparseable -> revise; all pass -> pass.
    A member that failed to run doesn't count as a pass."""
    kinds = [v["verdict"] for v in verdicts]
    if not kinds:
        return "revise"
    if "reject" in kinds:
        return "reject"
    if any(k in ("revise", "unparseable", "unavailable") for k in kinds):
        return "revise"
    return "pass"


# ---------------------------------------------------------------------------
# Diff stamp (from Cantor's workspace_patch_sha256 check): a pass only counts
# for the exact change that was reviewed.
# ---------------------------------------------------------------------------
def diff_fingerprint(repo: Path) -> str:
    def git(*args):
        done = subprocess.run(["git", "-C", str(repo), *args], text=True, encoding="utf-8",
                              errors="replace", capture_output=True, check=False)
        return done.stdout if done.returncode == 0 else ""
    staged = git("diff", "--cached", "--binary")
    unstaged = git("diff", "--binary")
    return hashlib.sha256((staged + "\0" + unstaged).encode("utf-8")).hexdigest()


def staged_fingerprint(repo: Path) -> str:
    done = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--binary"], text=True,
                          encoding="utf-8", errors="replace", capture_output=True, check=False)
    return hashlib.sha256(done.stdout.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cmd_check(args, config):
    rows = []
    for name, cfg in config["members"].items():
        if not cfg.get("enabled"):
            rows.append((name, "disabled", ""))
            continue
        adapter = ADAPTERS[name](cfg)
        try:
            exe = adapter.executable()
            auth = adapter.check_auth()
            rows.append((name, "ready", f"{exe} — {auth}"))
        except MemberUnavailable as exc:
            rows.append((name, "NOT READY", str(exc)))
    for name, status, detail in rows:
        print(f"{name:8} {status:10} {detail}")
    return 0 if all(s != "NOT READY" for _, s, _ in rows) else 1


def cmd_run(args, config, kind: str):
    review = kind == "review"
    brief = Path(args.brief).resolve()
    out_dir = brief.parent
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    cfg = config["members"].get(args.member)
    if cfg is None or args.member not in ADAPTERS:
        print(f"Unknown member: {args.member}", file=sys.stderr)
        return 2
    role = cfg.get("role", "")
    prompt = f"You are a council member. Your role: {role}\n\n" + brief.read_text(encoding="utf-8")
    if review:
        # Save the staged diff where every member can read it: headless agy can't run
        # `git diff` (shell commands are denied and end its run).
        diff_file = out_dir / "staged.diff"
        diff_file.write_text(git(workspace, "diff", "--cached", "--binary"), encoding="utf-8")
        prompt += (f"\n\nThe staged diff under review is saved at {diff_file}. Read it there; "
                   "you can also read any file in the repository for context.\n")
        prompt += "\n" + REVIEW_INSTRUCTIONS
    elif kind == "consult":
        prompt += "\n" + CONSULT_INSTRUCTIONS
    prompt_file = out_dir / f"{args.member}.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    result = run_member(args.member, prompt_file, workspace, out_dir, cfg,
                        args.timeout or config["timeout_seconds"])
    answer_path = out_dir / f"{args.member}.md"
    answer_path.write_text(result.text or "(no answer)\n" + "\n".join(result.notes), encoding="utf-8")
    meta = {k: v for k, v in result.__dict__.items() if k != "text"}
    meta["stderr"] = meta["stderr"][-2000:]
    if review:
        verdict = parse_verdict(args.member, result.text) if result.ok else {
            "member": args.member, "verdict": "unavailable", "confidence": 0.0,
            "summary": "; ".join(result.notes) or "Member failed.", "findings": []}
        verdict["fingerprint"] = diff_fingerprint(workspace)
        (out_dir / f"{args.member}.verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        meta["verdict"] = verdict["verdict"]
    (out_dir / f"{args.member}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    status = "ok" if result.ok else ("QUOTA" if result.quota_hit else
                                     "AUTH" if result.auth_problem else "FAILED")
    line = f"{args.member}: {status} in {result.seconds}s -> {answer_path}"
    if review:
        line += f" | verdict={meta['verdict']}"
    if result.notes:
        line += " | " + " ".join(result.notes)
    print(line)
    return 0 if result.ok else 1


def cmd_gate(args, config):
    out_dir = Path(args.dir).resolve()
    repo = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    verdicts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.verdict.json"))]
    current = diff_fingerprint(repo)
    stale = [v["member"] for v in verdicts if v.get("fingerprint") != current]
    decision = combine(verdicts)
    if stale:
        decision = "revise"
    gate = {
        "decision": decision,
        "members": {v["member"]: v["verdict"] for v in verdicts},
        "stale_reviews": stale,
        "staged_fingerprint": staged_fingerprint(repo),
        "working_fingerprint": current,
        "findings": [dict(f, member=v["member"]) for v in verdicts for f in v.get("findings", [])],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (out_dir / "gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    if decision == "pass":
        stamp = repo / ".council" / "approved.json"
        stamp.parent.mkdir(exist_ok=True)
        stamp.write_text(json.dumps({"staged_fingerprint": gate["staged_fingerprint"],
                                     "source": str(out_dir / "gate.json")}, indent=2), encoding="utf-8")
    counts = {s: sum(1 for f in gate["findings"] if f["severity"] == s) for s in SEVERITIES}
    print(f"GATE: {decision.upper()} | " + ", ".join(f"{m}={v}" for m, v in gate["members"].items())
          + f" | findings: {counts}" + (f" | stale: {stale}" if stale else ""))
    return 0 if decision == "pass" else 1


# ---------------------------------------------------------------------------
# Write mode: one member, one worktree, checked afterwards
# ---------------------------------------------------------------------------
def git(repo: Path, *args, check: bool = False) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], text=True, encoding="utf-8",
                          errors="replace", capture_output=True, check=False)
    if check and done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def repo_root(start: Path) -> Path:
    top = git(start, "rev-parse", "--show-toplevel").strip()
    if not top:
        raise RuntimeError(f"Not inside a git repository: {start}")
    return Path(top).resolve()


def run_slug(run_dir: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", run_dir.name).strip("-") or "task"


def snapshot(repo: Path) -> dict:
    """State of the main checkout that a confined member must not be able to change."""
    return {
        "head": git(repo, "rev-parse", "HEAD").strip(),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "status": git(repo, "status", "--porcelain", "-uall"),
        "refs": git(repo, "for-each-ref", "--format=%(refname) %(objectname)",
                    "refs/heads", "refs/tags"),
        "stash": git(repo, "stash", "list"),
    }


def glob_match(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/")
    regex, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif c == "*":
            regex, i = regex + "[^/]*", i + 1
        elif c == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(c), i + 1
    return re.fullmatch(regex, path) is not None


def allowed_paths(brief_text: str) -> list[str]:
    """Bullets under an '## Allowed paths' heading in the brief. Empty = anywhere not protected."""
    m = re.search(r"^#+\s*Allowed paths\s*$(.*?)(?=^#|\Z)", brief_text, re.M | re.S | re.I)
    if not m:
        return []
    return [g.strip().strip("`") for g in re.findall(r"^\s*[-*]\s+(.+)$", m.group(1), re.M)]


def worktree_changes(wt: Path) -> tuple[list[str], int]:
    """Stage everything in the worktree (the chairman reviews the staged diff) and
    return (changed paths, changed lines)."""
    git(wt, "add", "-A", check=True)
    files, lines = [], 0
    for row in git(wt, "diff", "--cached", "--numstat").splitlines():
        added, deleted, path = row.split("\t", 2)
        files.append(path)
        lines += (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
    return files, lines


def cmd_task(args, config):
    if args.member not in WRITE_MEMBERS:
        print(f"Write mode supports {', '.join(WRITE_MEMBERS)}, not {args.member}.", file=sys.stderr)
        return 2
    cfg = config["members"].get(args.member)
    if not cfg or not cfg.get("enabled"):
        print(f"Member {args.member} is disabled in council.config.json.", file=sys.stderr)
        return 2
    brief = Path(args.brief).resolve()
    run_dir = brief.parent
    repo = repo_root(Path(args.workspace).resolve() if args.workspace else Path.cwd())
    base = args.base or git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    base_sha = git(repo, "rev-parse", base, check=True).strip()
    slug = run_slug(run_dir)
    branch = f"council/{slug}-{args.member}"
    wt = repo / ".council" / "worktrees" / f"{slug}-{args.member}"
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp and str(wt).lower().startswith(str(Path(temp).resolve()).lower()):
        # Codex's workspace-write sandbox also allows writes to %TEMP% (found in the
        # canary test), so a worktree under it would not be confined.
        print("Refusing to run write mode inside %TEMP%: the sandbox can't confine it.",
              file=sys.stderr)
        return 2
    if wt.exists() or git(repo, "branch", "--list", branch).strip():
        print(f"{branch} or {wt} already exists. Run `council.py cleanup --dir {run_dir}` "
              "first, or use a new run folder.", file=sys.stderr)
        return 2
    if subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", ".council/x"],
                      capture_output=True).returncode != 0:
        print("Add `.council/` to .gitignore first, so worktrees and run files never get "
              "committed to the main checkout.", file=sys.stderr)
        return 2
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-b", branch, str(wt), base_sha, check=True)

    brief_text = brief.read_text(encoding="utf-8")
    allowed = allowed_paths(brief_text)
    prompt = (f"You are a council member doing a task. Your role: {cfg.get('role', '')}\n\n"
              + brief_text + "\n" + WRITE_INSTRUCTIONS.format(
                  worktree=wt, protected=", ".join(PROTECTED_GLOBS),
                  shell_note=SHELL_NOTE[args.member]))
    prompt_file = run_dir / f"{args.member}.task-prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    before = snapshot(repo)
    result = run_member(args.member, prompt_file, wt, run_dir, cfg,
                        args.timeout or config["timeout_seconds"], write=True)
    after = snapshot(repo)

    violations = [f"main checkout {key} changed during the run"
                  for key in ("head", "branch", "status", "stash") if before[key] != after[key]]
    if before["refs"] != after["refs"]:
        violations.append("branches or tags changed during the run")
    if git(wt, "rev-parse", "HEAD").strip() != base_sha:
        violations.append("the worktree has new commits (members must not commit)")
    files, lines = worktree_changes(wt)
    for f in files:
        if any(glob_match(f, g) for g in PROTECTED_GLOBS):
            violations.append(f"protected path changed: {f}")
        elif allowed and not any(glob_match(f, g) for g in allowed):
            violations.append(f"outside allowed paths: {f}")

    if violations:
        status = "VIOLATION"
    elif result.ok:
        status = "DONE"
    elif result.denied:
        status = "DENIED"
    else:
        status = "QUOTA" if result.quota_hit else "AUTH" if result.auth_problem else "FAILED"
    report = run_dir / f"{args.member}.md"
    report.write_text(result.text or "(no report)\n" + "\n".join(result.notes), encoding="utf-8")
    record = {
        "member": args.member, "status": status, "branch": branch, "worktree": str(wt),
        "base": base, "base_sha": base_sha, "files": files, "lines_changed": lines,
        "allowed_paths": allowed, "violations": violations,
        "staged_fingerprint": staged_fingerprint(wt), "seconds": result.seconds,
        "notes": result.notes, "stderr": result.stderr[-2000:],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (run_dir / f"{args.member}.task.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    line = (f"{args.member}: {status} in {result.seconds}s | {len(files)} files, {lines} lines "
            f"| worktree {wt} | branch {branch} | report {report}")
    if violations:
        line += " | VIOLATIONS: " + "; ".join(violations)
    if result.notes:
        line += " | " + " ".join(result.notes)
    print(line)
    return 0 if status == "DONE" else 1


def cmd_cleanup(args, config):
    """Remove the worktrees and council/* branches a task run created. Only touches
    paths under .council/worktrees/ and branches named council/<run>-<member>."""
    run_dir = Path(args.dir).resolve()
    repo = repo_root(Path(args.workspace).resolve() if args.workspace else Path.cwd())
    members = [args.member] if args.member else list(WRITE_MEMBERS)
    slug = run_slug(run_dir)
    for member in members:
        wt = repo / ".council" / "worktrees" / f"{slug}-{member}"
        branch = f"council/{slug}-{member}"
        if wt.exists():
            if git(wt, "status", "--porcelain").strip() and not args.discard:
                print(f"kept {wt}: it has uncommitted work (commit it, or pass --discard)")
                continue
            git(repo, "worktree", "remove", "--force", str(wt), check=True)
            print(f"removed worktree {wt}")
        if git(repo, "branch", "--list", branch).strip():
            merged = branch in git(repo, "branch", "--merged", "HEAD").split()
            if merged or args.discard:
                git(repo, "branch", "-D", branch, check=True)
                print(f"deleted branch {branch}" + ("" if merged else " (unmerged, discarded)"))
            else:
                print(f"kept {branch}: not merged into HEAD (pass --discard to delete it)")
    git(repo, "worktree", "prune")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Council member runner")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("ask", "consult", "review"):
        p = sub.add_parser(name)
        p.add_argument("--member", required=True)
        p.add_argument("--brief", required=True)
        p.add_argument("--workspace")
        p.add_argument("--timeout", type=int)
    g = sub.add_parser("gate")
    g.add_argument("--dir", required=True)
    g.add_argument("--workspace")
    t = sub.add_parser("task")
    t.add_argument("--member", required=True)
    t.add_argument("--brief", required=True)
    t.add_argument("--base", help="branch or commit to start from (default: current branch)")
    t.add_argument("--workspace", help="repo to work in (default: current directory)")
    t.add_argument("--timeout", type=int)
    c = sub.add_parser("cleanup")
    c.add_argument("--dir", required=True)
    c.add_argument("--member")
    c.add_argument("--workspace")
    c.add_argument("--discard", action="store_true", help="also delete unmerged council branches")
    args = parser.parse_args()
    config = load_config()
    if args.cmd == "check":
        return cmd_check(args, config)
    if args.cmd in ("ask", "consult", "review"):
        return cmd_run(args, config, kind=args.cmd)
    if args.cmd == "task":
        return cmd_task(args, config)
    if args.cmd == "cleanup":
        return cmd_cleanup(args, config)
    return cmd_gate(args, config)


if __name__ == "__main__":
    sys.exit(main())
