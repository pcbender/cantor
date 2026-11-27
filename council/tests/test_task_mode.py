"""Write-mode tests with stub members (no real CLI is called).
Run: python -m unittest discover council/tests"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import council  # noqa: E402

STUB = r'''
import os, subprocess, sys
from pathlib import Path
mode = sys.argv[1]
cwd = Path.cwd()
sys.stdin.read() if not sys.stdin.isatty() else None
if mode == "good":
    (cwd / "src").mkdir(exist_ok=True)
    (cwd / "src" / "hello.py").write_text("print('hi')\n")
elif mode == "escape":
    (cwd.parents[2] / "evil.txt").write_text("escaped\n")
elif mode == "commit":
    (cwd / "x.txt").write_text("x\n")
    subprocess.run(["git", "add", "x.txt"], check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "sneaky"], check=True)
elif mode == "protected":
    (cwd / ".github").mkdir(exist_ok=True)
    (cwd / ".github" / "ci.yml").write_text("on: push\n")
print("## Changed\n- stub\n## Tested\nnot run\n## Unsure\nnothing")
'''


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class TaskModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_env = {k: os.environ.get(k) for k in ("TEMP", "TMP")}
        os.environ["TEMP"] = os.environ["TMP"] = str(root / "elsewhere")  # see %TEMP% guard
        self.repo = root / "repo"
        self.repo.mkdir()
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        (self.repo / ".gitignore").write_text(".council/\n")
        (self.repo / "a.txt").write_text("a\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "init")
        sh(self.repo, "git", "checkout", "-q", "-b", "claude/work")
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "stub.py").write_text(STUB)
        self.run_dir = self.repo / ".council" / "runs" / "t1"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "task.md").write_text("# Task\nAdd hello.\n\n## Allowed paths\n- src/**\n- x.txt\n")
        self.cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True)
        self.tmp.cleanup()

    def stub(self, mode):
        if os.name == "nt":
            exe = self.bin / f"stub-{mode}.cmd"
            exe.write_text(f'@"{sys.executable}" "{self.bin / "stub.py"}" {mode}\r\n')
        else:
            exe = self.bin / f"stub-{mode}"
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.bin / "stub.py"}" {mode}\n')
            exe.chmod(0o755)
        return str(exe)

    def run_task(self, mode, member="codex"):
        config = council.load_config()
        config["members"][member].update(enabled=True, executable=self.stub(mode), model=None,
                                         extra_args=[])
        # Stubs don't accept codex/agy flags, so build the argv ourselves.
        orig = council.ADAPTERS[member].build
        council.ADAPTERS[member].build = lambda self_, pf, ws, of, write=False: (
            [self_.executable()], pf.read_text(encoding="utf-8"))
        try:
            args = argparse.Namespace(member=member, brief=str(self.run_dir / "task.md"), base=None,
                                      workspace=None, timeout=60)
            code = council.cmd_task(args, config)
        finally:
            council.ADAPTERS[member].build = orig
        record = json.loads((self.run_dir / f"{member}.task.json").read_text())
        return code, record

    def test_good_run(self):
        code, rec = self.run_task("good")
        self.assertEqual(rec["status"], "DONE", rec)
        self.assertEqual(code, 0)
        self.assertEqual(rec["files"], ["src/hello.py"])
        self.assertEqual(rec["branch"], "council/t1-codex")
        wt = Path(rec["worktree"])
        self.assertTrue((wt / "src" / "hello.py").is_file())
        self.assertFalse((self.repo / "src").exists())  # main checkout untouched
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=wt,
                                capture_output=True, text=True).stdout.split()
        self.assertEqual(staged, ["src/hello.py"])  # staged for the chairman's review

    def test_escape_is_a_violation(self):
        _, rec = self.run_task("escape")
        self.assertEqual(rec["status"], "VIOLATION")
        self.assertTrue(any("main checkout untracked" in v for v in rec["violations"]))

    def test_member_commit_is_a_violation(self):
        _, rec = self.run_task("commit")
        self.assertEqual(rec["status"], "VIOLATION")
        self.assertTrue(any("new commits" in v for v in rec["violations"]))

    def test_protected_path_is_a_violation(self):
        _, rec = self.run_task("protected")
        self.assertEqual(rec["status"], "VIOLATION")
        self.assertTrue(any(".github/ci.yml" in v for v in rec["violations"]))

    def test_existing_worktree_refused_and_cleanup(self):
        self.run_task("good")
        args = argparse.Namespace(member="codex", brief=str(self.run_dir / "task.md"), base=None,
                                  workspace=None, timeout=60)
        self.assertEqual(council.cmd_task(args, council.load_config()), 2)
        wt = self.repo / ".council" / "worktrees" / "t1-codex"
        council.cmd_cleanup(argparse.Namespace(dir=str(self.run_dir), member="codex",
                                               workspace=None, discard=False), {})
        self.assertTrue(wt.exists())  # uncommitted member work is kept unless --discard
        # once committed and merged, a plain cleanup removes both
        sh(wt, "git", "commit", "-qm", "member work")
        sh(self.repo, "git", "merge", "-q", "--no-ff", "-m", "merge", "council/t1-codex")
        council.cmd_cleanup(argparse.Namespace(dir=str(self.run_dir), member="codex",
                                               workspace=None, discard=False), {})
        self.assertFalse(wt.exists())
        self.assertNotIn("council/t1-codex", subprocess.run(["git", "branch"], cwd=self.repo,
                                                            capture_output=True, text=True).stdout)
        # an unmerged committed branch is kept unless --discard
        self.run_dir2 = self.repo / ".council" / "runs" / "t2"
        self.run_dir2.mkdir()
        (self.run_dir2 / "task.md").write_text("# Task\n")
        self.run_dir = self.run_dir2
        _, rec = self.run_task("good")
        (Path(rec["worktree"]) / "more.txt").write_text("more\n")
        sh(Path(rec["worktree"]), "git", "add", "more.txt")
        sh(Path(rec["worktree"]), "git", "commit", "-qm", "more")
        council.cmd_cleanup(argparse.Namespace(dir=str(self.run_dir), member="codex",
                                               workspace=None, discard=False), {})
        self.assertIn("council/t2-codex", subprocess.run(["git", "branch"], cwd=self.repo,
                                                         capture_output=True, text=True).stdout)
        council.cmd_cleanup(argparse.Namespace(dir=str(self.run_dir), member="codex",
                                               workspace=None, discard=True), {})
        self.assertNotIn("council/t2-codex", subprocess.run(["git", "branch"], cwd=self.repo,
                                                            capture_output=True, text=True).stdout)

    def test_review_round_runner_checks(self):
        # Rewriting an already-modified file in the main checkout is caught by content hash.
        (self.repo / "a.txt").write_text("dirty\n")
        STUB_REWRITE = "(Path.cwd().parents[2] / 'a.txt').write_text('dirtier\\n')"
        (self.bin / "stub.py").write_text(STUB.replace(
            'elif mode == "protected":', f'elif mode == "rewrite":\n    {STUB_REWRITE}\nelif mode == "protected":'))
        _, rec = self.run_task("rewrite")
        self.assertEqual(rec["status"], "VIOLATION")
        self.assertTrue(any("main checkout worktree" in v for v in rec["violations"]))

    def test_rename_into_protected_path(self):
        (self.repo / "src").mkdir()
        (self.repo / "src" / "old.yml").write_text("x\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "add old")
        mv = ("(Path.cwd() / '.github').mkdir(exist_ok=True); "
              "(Path.cwd() / 'src' / 'old.yml').rename(Path.cwd() / '.github' / 'ci.yml')")
        (self.bin / "stub.py").write_text(STUB.replace(
            'elif mode == "protected":', f'elif mode == "rename":\n    {mv}\nelif mode == "protected":'))
        _, rec = self.run_task("rename")
        self.assertEqual(rec["status"], "VIOLATION")
        self.assertTrue(any(".github/ci.yml" in v for v in rec["violations"]))

    def test_continue_round(self):
        _, rec = self.run_task("good")
        self.assertEqual(rec["status"], "DONE")
        config = council.load_config()
        config["members"]["codex"].update(enabled=True, executable=self.stub("good"), extra_args=[])
        orig = council.ADAPTERS["codex"].build
        council.ADAPTERS["codex"].build = lambda self_, pf, ws, of, write=False: (
            [self_.executable()], pf.read_text(encoding="utf-8"))
        try:
            args = argparse.Namespace(member="codex", brief=str(self.run_dir / "task.md"), base=None,
                                      workspace=None, timeout=60, resume=True)
            self.assertEqual(council.cmd_task(args, config), 0)
        finally:
            council.ADAPTERS["codex"].build = orig

    def test_gate_requires_all_reviewers(self):
        verdict = {"member": "gemini", "verdict": "pass", "findings": [],
                   "fingerprint": council.diff_fingerprint(self.repo)}
        (self.run_dir / "gemini.verdict.json").write_text(json.dumps(verdict))
        config = council.load_config()
        gate = lambda req: council.cmd_gate(argparse.Namespace(dir=str(self.run_dir), workspace=None,
                                                               require=req), config)
        self.assertEqual(gate(None), 1)          # codex is enabled but has no verdict
        self.assertEqual(gate("gemini"), 0)      # cross-review: only the other member
        self.assertTrue((self.repo / ".council" / "approved.json").is_file())
        self.assertEqual(gate("codex,gemini"), 1)
        self.assertFalse((self.repo / ".council" / "approved.json").is_file())  # withdrawn

    def test_bypass_in_extra_args_refused(self):
        adapter = council.CodexAdapter({"executable": "codex", "extra_args": ["-s", "danger-full-access"]})
        with self.assertRaises(council.MemberUnavailable):
            adapter.executable()

    def test_claude_cannot_write(self):
        args = argparse.Namespace(member="claude", brief=str(self.run_dir / "task.md"), base=None,
                                  workspace=None, timeout=60)
        self.assertEqual(council.cmd_task(args, council.load_config()), 2)

    def test_helpers(self):
        self.assertTrue(council.glob_match("src/a/b.py", "src/**"))
        self.assertTrue(council.glob_match("council.config.json", "**/council.config.json"))
        self.assertTrue(council.glob_match("x/council.config.json", "**/council.config.json"))
        self.assertFalse(council.glob_match("lib/a.py", "src/**"))
        self.assertEqual(council.allowed_paths("## Allowed paths\n- `src/**`\n- x.txt\n## Next\n- no"),
                         ["src/**", "x.txt"])
        denied = "jetski: no output produced — a tool required the \"command\" permission that..."
        self.assertEqual(council.AGY_DENIED.search(denied).group(1), "command")


if __name__ == "__main__":
    unittest.main()
