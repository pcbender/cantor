# Cantor → Council: handoff (2026-11-27)

Decisions and context from the chat where this pivot was planned. Read this before working on
the council skill.

## Direction

- Claude Code now covers most of what Cantor was built to coordinate: subagents, worktrees,
  hooks, skills, MCP, Remote Control. **Cantor is retired as a framework.** Its useful ideas
  move into small Claude Code pieces.
- Goal: a "council of experts" across Rosie's three subscriptions (Claude, ChatGPT, Gemini),
  using subscription logins, not API billing.
- **Chairman = Claude Code in the Desktop app**, so the session can be driven from the phone
  via Remote Control (`/remote-control`). Members are Codex and Gemini, both read-only.

## Facts that shaped the design

- **Gemini CLI is dead for consumer subscriptions.** It stopped serving Google AI Pro/Ultra
  accounts on 2026-06-18. The replacement is Antigravity CLI (`agy`); headless mode is
  `agy -p` / `--print`, using cached credentials from one interactive `agy` login.
- **Known agy bug:** when run from a pipe or subprocess (non-TTY), `agy -p` can finish with
  exit 0 and print nothing. The runner retries under a pseudo-terminal (pywinpty on Windows).
- Codex: `codex exec` (headless), `codex mcp-server` (Codex as an MCP tool), ChatGPT
  subscription auth lives in `~/.codex/auth.json` with `auth_mode: chatgpt`.
- Serenity runs native Windows now (moving off WSL2).

## What was kept from Cantor

- `CliExecutor` adapters, read-only → `scripts/council.py`
- Subscription-auth checks (refuse API-key billing) → `council.py check`
- `cli_env` env scrubbing, **fixed for Windows** (the original allowlist was POSIX-only and
  dropped USERPROFILE/APPDATA/SystemRoot)
- `map_quota` → QUOTA/AUTH reporting
- `workspace_patch_sha256` check → diff fingerprint; a pass only counts for the reviewed diff
- Review gate/blockers → `council.py gate` + `commit_gate.py` PreToolUse hook

**New (never built in Cantor):** the cross-vendor structured verdict. Cantor's reviews were
human-only decisions. The schema is pass/revise/reject + findings with severity. Gate policy:
any reject → REJECT; any revise, unparseable or missing member → REVISE; a pass with a
blocker or major finding is downgraded to revise; stale reviews → REVISE.

## Status / next steps

- [ ] Install the skill: the source lives in `council/` at the repo root (remote tools can't
      write into `.claude/`). Copy it to `.claude/skills/council/` for this repo, or to
      `~/.claude/skills/council/` for every repo.
- [ ] First real run on Serenity: `python council/scripts/council.py check`
- [ ] Confirm `codex exec --output-last-message` exists in the installed version
- [ ] Confirm `agy` flags (`agy --help`); adjust `extra_args` or the adapter
- [ ] `pip install pywinpty`
- [ ] Decide whether to also install the skill user-wide (`~/.claude/skills/council`) so it
      works in every repo, not just this one
- [ ] Optional: add allow rules + commit-gate hook (see `council/README.md`)
- [ ] Optional: archive the old `canto/` framework code once the council skill is proven
