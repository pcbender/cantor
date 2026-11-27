"""Tests for the delegation-of-authority hook. Run: python -m unittest discover council/tests"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import policy_gate  # noqa: E402


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class PolicyGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        (self.repo / "a.txt").write_text("a\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "init")
        sh(self.repo, "git", "checkout", "-q", "-b", "claude/work")

    def tearDown(self):
        self.tmp.cleanup()

    def bash(self, command):
        hit = policy_gate.evaluate({"tool_name": "Bash", "cwd": str(self.repo),
                                    "tool_input": {"command": command}})
        return hit[0] if hit else "allow"

    def edit(self, path):
        hit = policy_gate.evaluate({"tool_name": "Edit", "cwd": str(self.repo),
                                    "tool_input": {"file_path": path}})
        return hit[0] if hit else "allow"

    # Tier 0 / 1: allowed silently
    def test_tier0_and_tier1_allowed(self):
        for cmd in ("git status", "git commit -m x", "git checkout -b council/t-codex",
                    "git push -u origin claude/work", "git push origin council/x-codex",
                    "git push", "gh pr create --draft --title t --body b",
                    "git worktree add .council/worktrees/x -b council/x",
                    "git worktree remove --force .council/worktrees/x",
                    "git branch -D council/x-codex", "rm -rf .council/worktrees/x",
                    "python council/scripts/council.py gate --dir .council/runs/x",
                    "cat .council/runs/x/gate.json", "gh pr view 3", "gh api repos/o/r/pulls"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), "allow")

    # Tier 2: ask Rosie
    def test_tier2_asks(self):
        for cmd in ("git push origin main", "git push --force", "git push -f origin claude/work",
                    "git push origin +claude/work", "git push origin :claude/old",
                    "git push origin feature/other", "git push --delete origin claude/work",
                    "gh pr merge 3", "gh pr ready 3", "gh pr create --title t --body b",
                    "git branch -D feature/x", "git tag -d v1", "npm install left-pad",
                    "pip install requests", "python -m pip install x", "rm -rf src",
                    "git clean -fd", "git checkout -- .", "git config --global user.name x",
                    "gh repo edit --visibility public",
                    "gh api -X DELETE repos/o/r"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), "ask")

    def test_main_branch_actions_ask(self):
        sh(self.repo, "git", "checkout", "-q", "main")
        for cmd in ("git commit -m x", "git merge claude/work", "git push", "git rebase claude/work",
                    "git reset --hard HEAD~1"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), "ask")

    def test_git_dash_c_uses_that_repo(self):
        sh(self.repo, "git", "checkout", "-q", "main")
        other = Path(self.tmp.name) / "wt"
        sh(self.repo, "git", "worktree", "add", "-q", "-b", "council/t-codex", str(other))
        self.assertEqual(self.bash(f'git -C "{other}" commit -m x'), "allow")
        self.assertEqual(self.bash("git commit -m x"), "ask")

    def test_large_merge_asks(self):
        sh(self.repo, "git", "checkout", "-q", "-b", "council/big-codex")
        (self.repo / "big.txt").write_text("x\n" * 401)
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "big")
        sh(self.repo, "git", "checkout", "-q", "claude/work")
        self.assertEqual(self.bash("git merge --no-ff council/big-codex"), "ask")
        sh(self.repo, "git", "checkout", "-q", "-b", "council/small-codex")
        (self.repo / "small.txt").write_text("x\n" * 10)
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "small")
        sh(self.repo, "git", "checkout", "-q", "claude/work")
        self.assertEqual(self.bash("git merge --no-ff council/small-codex"), "allow")

    def test_chained_commands_take_the_strictest(self):
        self.assertEqual(self.bash("git add a.txt && git push origin main"), "ask")
        self.assertEqual(self.bash("git status; codex exec --sandbox danger-full-access -"), "deny")

    # Never
    def test_never_denied(self):
        for cmd in ("codex exec --dangerously-bypass-approvals-and-sandbox -",
                    "agy --print x --dangerously-skip-permissions",
                    "codex exec -s danger-full-access -", "cat ~/.codex/auth.json",
                    "echo {} > .council/runs/x/codex.verdict.json",
                    "Set-Content .council/approved.json '{}'",
                    "cp fake.json .council/runs/x/gate.json"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), "deny")

    def test_file_tools(self):
        self.assertEqual(self.edit(str(self.repo / "src" / "app.py")), "allow")
        self.assertEqual(self.edit(str(self.repo / ".claude" / "settings.json")), "ask")
        self.assertEqual(self.edit(str(self.repo / ".github" / "workflows" / "ci.yml")), "ask")
        self.assertEqual(self.edit(str(self.repo / ".gitignore")), "ask")
        self.assertEqual(self.edit(str(self.repo / "council" / "council.config.json")), "ask")
        self.assertEqual(self.edit(str(self.repo / ".council" / "runs" / "x" / "gemini.verdict.json")), "deny")

    # Commit gate (kept from commit_gate.py)
    def test_commit_gate(self):
        (self.repo / ".council").mkdir()
        (self.repo / "b.txt").write_text("b\n")
        sh(self.repo, "git", "add", "b.txt")
        self.assertEqual(self.bash("git commit -m x"), "allow")  # run folders alone don't enable it
        (self.repo / ".council" / "enforce-commit-gate").write_text("")
        self.assertEqual(self.bash("git commit -m x"), "deny")  # no approval yet
        self.assertEqual(self.bash("git commit -am x"), "deny")
        self.assertEqual(self.bash("COUNCIL_SKIP=1 git commit -m x"), "ask")
        staged = subprocess.run(["git", "diff", "--cached", "--binary"], cwd=self.repo,
                                capture_output=True, text=True, encoding="utf-8").stdout
        import hashlib
        fp = hashlib.sha256(staged.encode("utf-8")).hexdigest()
        (self.repo / ".council" / "approved.json").write_text(json.dumps({"staged_fingerprint": fp}))
        self.assertEqual(self.bash("git commit -m x"), "allow")
        (self.repo / "c.txt").write_text("c\n")
        sh(self.repo, "git", "add", "c.txt")
        self.assertEqual(self.bash("git commit -m x"), "deny")  # restaged after approval

    def test_hook_output_shape(self):
        done = subprocess.run([sys.executable, str(Path(policy_gate.__file__))],
                              input=json.dumps({"tool_name": "Bash", "cwd": str(self.repo),
                                                "tool_input": {"command": "gh pr merge 1"}}),
                              capture_output=True, text=True)
        out = json.loads(done.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        done = subprocess.run([sys.executable, str(Path(policy_gate.__file__))],
                              input=json.dumps({"tool_name": "Bash", "cwd": str(self.repo),
                                                "tool_input": {"command": "git status"}}),
                              capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "")
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
