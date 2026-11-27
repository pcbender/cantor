# Council skill for Claude Code

What's kept from Cantor, rebuilt as a Claude Code skill. Claude (Desktop app, Remote Control)
is the chairman. Codex and Gemini are members on your subscription logins: read-only when
consulted or reviewing, and confined to their own git worktree when given a task.

## Modes

| Mode | Command | Members can |
| --- | --- | --- |
| Consult | `/council approach <problem>` | read the repo, propose a plan |
| Ask | `/council <question>` | read the repo, answer |
| Review | `/council review` | read the staged diff, return a verdict |
| Task | `/council task <what to do>` | edit files in `.council/worktrees/<run>-<member>` only |

Run folders go in `.council/runs/`, worktrees in `.council/worktrees/`. Add `.council/` to
the repo's `.gitignore` (task mode refuses to run without it).

## What came from Cantor

| Cantor | Here |
| --- | --- |
| `CliExecutor` + `CodexCliAdapter` / `ClaudeCliAdapter` | `scripts/council.py` adapters: read-only by default, write mode for tasks |
| `GeminiCliAdapter` (`gemini`) | Replaced by `agy` (Antigravity). Gemini CLI stopped serving AI Pro/Ultra on 2026-06-18 |
| `assert_auth` subscription checks | `council.py check`. Refuses a member that would bill an API key |
| `cli_env.build_subprocess_env` | `scrubbed_env()`, **fixed for Windows** |
| `map_quota` | Quota and auth detection, reported as `QUOTA` / `AUTH` |
| `workspace_patch_sha256` acceptance check | Diff fingerprint: a pass only counts for the exact staged change |
| Review gate (`acceptance_ready`, blockers) | `council.py gate` + the commit gate in `policy_gate.py` |
| Cross-vendor structured verdict (explored, never built) | JSON verdict schema, consistency rule, combine policy |

## How write mode is confined (tested on Serenity, 2026-11-27)

- **Codex** runs `codex exec --sandbox workspace-write --cd <worktree>`. It can edit files and
  run commands inside the worktree. Writes to the parent folder and the main checkout are
  denied, and so are `git add`/`commit` (a linked worktree's git metadata lives in the main
  repo's `.git/`, outside the sandbox). Network is off. Caveat found in testing: the sandbox
  also allows writes to `%TEMP%`, so `task` refuses a worktree under `%TEMP%`.
- **Gemini** runs `agy --print <prompt> --add-dir <worktree> --mode accept-edits --sandbox`.
  Headless, it may edit files inside the worktree; edits elsewhere and **every** shell
  command are auto-denied, and a denial ends the run (reported as `DENIED`). So Gemini edits
  and the chairman runs the tests. Per-session allow rules via `agy --settings` did not take
  effect in testing.
- **Afterwards** the runner compares the main checkout (HEAD, branch, status, refs, stash)
  before and after, checks the worktree has no new commits, and checks every changed path
  against the brief's `## Allowed paths` and a protected list (`.git`, `.github/`, `.claude/`,
  `.council/`, `.canto/`, `council.config.json`, `CLAUDE.md`, `.gitignore`, settings,
  lockfiles, `.env`). The main-checkout comparison uses content hashes, renames are checked
  as their new path, ignored files the member created are checked too, and a rewritten
  worktree `.git` pointer is caught before any git command runs there. Any breach is
  `VIOLATION`. Branches under `council/` are left out of the comparison so two tasks can run
  in parallel.
- **Another round** on the same worktree: `task ... --continue` (only for the registered
  worktree on its `council/` branch).
- Not checked: edits to files that were already gitignored inside the worktree, and new
  ignored files outside the allowed paths (test runs create `__pycache__` and the like).
  `cleanup` treats ignored files in a council worktree as disposable build output.

## Install (Serenity, native Windows)

1. Copy this folder to `C:\Users\mrose\.claude\skills\council\`.
2. `pip install pywinpty` (fallback for agy's empty-output-on-pipe bug).
3. Log in once, interactively: `codex login`, then run `agy` once.
4. Check: `python C:\Users\mrose\.claude\skills\council\scripts\council.py check`
5. Tests: `python -m unittest discover -s council/tests`

## Delegation-of-authority hook

`scripts/policy_gate.py` enforces the policy in `SKILL.md`. Tier 0 and Tier 1 actions pass
silently. Tier 2 actions return `ask`, so Claude Code prompts you (on your phone over Remote
Control) and only you can approve. "Never" actions are denied. It also contains the commit
gate that used to be `commit_gate.py`.

Add to `C:\Users\mrose\.claude\settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python C:/Users/mrose/.claude/skills/council/scripts/council.py:*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit|Read",
        "hooks": [
          { "type": "command",
            "command": "python C:/Users/mrose/.claude/skills/council/scripts/policy_gate.py" }
        ]
      }
    ]
  }
}
```

What it checks, in short:

- **ask**: push to `main`/`master` or to a branch not named `council/*` or `claude/*`; force,
  delete, mirror or `--tags` pushes; commit, merge, rebase or reset while on `main`; merges
  over 400 changed lines; rebase or `reset --hard` of a pushed branch; deleting non-council
  branches, tags or worktrees; `git clean -f` and `checkout -- .` in the main checkout; global
  git config; `gh pr merge/ready/close`, non-draft `gh pr create`, `gh repo/release/secret/...`
  and writing `gh api` calls; dependency installs; recursive deletes outside `.council/`;
  edits to config files; `COUNCIL_SKIP=1`.
- **deny**: sandbox-bypass flags, reading CLI credentials, and writing verdict, gate or
  approval files by hand; `git commit -a` and commits whose staged diff the council has not
  passed, in repos where the commit gate is on.

It splits chained commands (`&&`, `;`, `|`, `&`, newlines, subshells), looks inside
`bash -c` / `pwsh -Command`, expands git aliases, tracks a `git checkout` earlier in the
same command, normalises paths (including `..`, `~` and NTFS `::$DATA` suffixes), and checks
shell writes (`>`, `Set-Content`, `cp`, `sed -i`...) against the same config and forgery rules
as the Edit tool.

Limits: it sees only the chairman's own tool calls, not what a member runs inside its
sandbox (the sandboxes and the after-run check cover that). It classifies commands with
simple parsing, so it is a guardrail against mistakes, not a sandbox: an agent set on
evading it could write a script and run that. Branch ownership is by name (`council/*`,
`claude/*`), so another session's `claude/*` branch counts as delegated too.

## Commit gate (optional, per repo)

Create `.council/enforce-commit-gate` in a repo to require a passing council review of the
exact staged diff before Claude can `git commit` there. Restaging anything after approval
blocks it again. Run folders alone don't turn it on.

## Gate policy

- Any member says `reject` → **REJECT**
- Any `revise`, unparseable reply, member that failed to run, or required reviewer with no
  verdict (`--require`, default every enabled member) → **REVISE**
- Any non-pass removes an earlier `.council/approved.json`
- A `pass` with a blocker or major finding is downgraded to `revise`
- Reviews of an older diff are marked stale → **REVISE**
- Otherwise → **PASS**

Change member roles, models and timeout in `council.config.json`. Turn on `claude` as a
member if you ever chair from Codex instead (read-only; it has no write mode).
