from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError


class RepositoryConfigError(ValueError):
    pass


class RepositoryConfig(BaseModel):
    version: int = 1
    repo_id: str
    canonical_path: str
    git_common_dir: str
    initial_head: str
    remotes: dict[str, str] = Field(default_factory=dict)


class RepositoryPolicy(BaseModel):
    version: int = 1
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    required_commands: list[str] = Field(default_factory=list)
    allow_network: bool = False
    allow_secrets: bool = False


class RepositoryDoctorCheck(BaseModel):
    name: str
    valid: bool
    detail: str


class RepositoryDoctorResult(BaseModel):
    valid: bool
    repository: str
    checks: list[RepositoryDoctorCheck] = Field(default_factory=list)


CANTO_AGENTS_MARKER_START = "<!-- canto-agent-instructions:start -->"
CANTO_AGENTS_MARKER_END = "<!-- canto-agent-instructions:end -->"
CANTO_AGENTS_SECTION = f"""{CANTO_AGENTS_MARKER_START}
## Canto Agent Instructions

This repository is Canto-enabled. Before working, read
`.canto/agents/shared.md`. Developer sessions supervising governed work must
also read `.canto/agents/orchestrator.md`; delegated Worker sessions must also
read `.canto/agents/executor.md`. The filenames retain internal compatibility
terms while the manuals define the public roles.

Do not bypass Canto assignment, Guardrail, review, Result, Approval, or Apply
rules.
{CANTO_AGENTS_MARKER_END}
"""

DELEGATE_TOML = """version = 1
instruction_root = ".canto/agents"
shared_instructions = ".canto/agents/shared.md"
orchestrator_instructions = ".canto/agents/orchestrator.md"
executor_instructions = ".canto/agents/executor.md"
"""

SHARED_AGENT_INSTRUCTIONS = """# Canto Shared Agent Instructions

- Canto is globally installed; do not install Canto into this repository.
- Durable state, credentials, Results, and Workspaces live under `~/.canto`.
- Repository-local Canto intent and Guardrails live under `.canto/`.
- Delegated Worker activity happens only in Canto-managed Git worktrees.
- Canonical repository changes require Developer review and acceptance before
  Canto may Apply the exact accepted Result.
- Do not commit or push unless the human explicitly instructs you to do so.
- Do not access secrets, credential vault files, or paths denied by Guardrails.
- Sparse checkout limits context but is not a security boundary.
"""

ORCHESTRATOR_AGENT_INSTRUCTIONS = """# Canto Developer Instructions

You are the Developer supervising governed Canto work. The compatibility
filename is `orchestrator.md`; the public authority is Developer.

- Define bounded work, Guardrails, and explicit instructions.
- Select and assign an approved Worker profile.
- Prefer a compatible approved local Worker when practical. If local profiles
  cannot perform the required tool actions, explicitly select a supervised
  `codex-cloud` Worker that uses the host Codex CLI's existing authentication.
- Never switch from a local Worker to a cloud Worker automatically. Disclose
  network and quota use, preserve the same bounded Workspace, and require the
  normal Capture, Review, and Apply flow.
- Do not use arbitrary `sleep` commands to guess whether a Worker finished.
  Keep the supervised launch command attached when possible, or use
  `canto delegate wait TASK_ID` to synchronize on durable task state.
- Inspect dashboards, immutable Results, command evidence, and conflicts.
- Request revisions when evidence or implementation is incomplete.
- Accept or reject Results explicitly; Workers cannot accept their own work.
- Authorize Canto to Apply only the exact accepted and verified Result to the
  named target.
- Report assignment, review, conflict, and Apply status to the human operator.
"""

EXECUTOR_AGENT_INSTRUCTIONS = """# Canto Delegated Worker Instructions

You are a Canto delegated Worker. The compatibility filename is `executor.md`;
the public role is Worker.

- Work only in the delegated Workspace and within the assignment's allowed
  paths.
- Follow Canto assignment instructions and revision messages as the source of
  truth.
- Do not access secrets or modify denied paths.
- Run only allowed tests and commands; report relevant results accurately.
- Do not modify the canonical repository.
- Do not self-assign, broaden scope, commit, push, accept, reject, queue, or
  Apply a Result.
- When complete, leave the Workspace ready for `canto delegate capture` so
  Canto can record an immutable Result for Developer review.
"""


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RepositoryConfigError(f"Git command failed ({' '.join(args)}): {message}")
    return completed.stdout.strip()


def git_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise RepositoryConfigError(f"Repository path does not exist: {candidate}")
    return Path(_git(candidate, "rev-parse", "--show-toplevel")).resolve()


def _git_metadata(repository: Path) -> tuple[str, str, dict[str, str]]:
    common_value = _git(repository, "rev-parse", "--git-common-dir")
    common = Path(common_value)
    if not common.is_absolute():
        common = repository / common
    head = _git(repository, "rev-parse", "HEAD")
    remotes = {
        name: _git(repository, "remote", "get-url", name)
        for name in _git(repository, "remote").splitlines()
        if name
    }
    return str(common.resolve()), head, remotes


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _string_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        if not path.is_file():
            raise RepositoryConfigError(f"Canto bootstrap path is not a file: {path}")
        return
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RepositoryConfigError(f"Cannot write Canto bootstrap file {path}: {exc}") from exc


def _write_canto_owned(path: Path, content: str) -> None:
    if path.exists() and not path.is_file():
        raise RepositoryConfigError(f"Canto bootstrap path is not a file: {path}")
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RepositoryConfigError(f"Cannot refresh Canto bootstrap file {path}: {exc}") from exc


def _ensure_agent_entrypoint(repository: Path) -> Path:
    path = repository / "AGENTS.md"
    if not path.exists():
        _write_if_missing(path, "# Agent Instructions\n\n" + CANTO_AGENTS_SECTION)
        return path
    if not path.is_file():
        raise RepositoryConfigError(f"Agent instruction entrypoint is not a file: {path}")
    content = path.read_text(encoding="utf-8")
    if CANTO_AGENTS_MARKER_START in content:
        if CANTO_AGENTS_MARKER_END not in content:
            raise RepositoryConfigError("Existing AGENTS.md has an incomplete Canto instruction section")
        start = content.index(CANTO_AGENTS_MARKER_START)
        end = content.index(CANTO_AGENTS_MARKER_END, start) + len(CANTO_AGENTS_MARKER_END)
        updated = content[:start] + CANTO_AGENTS_SECTION.rstrip("\n") + content[end:]
        if updated != content:
            temporary = path.with_name("AGENTS.md.tmp")
            try:
                temporary.write_text(updated, encoding="utf-8")
                temporary.replace(path)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise RepositoryConfigError(
                    f"Cannot refresh Canto pointer in {path}: {exc}"
                ) from exc
        return path
    separator = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
    temporary = path.with_name("AGENTS.md.tmp")
    try:
        temporary.write_text(content + separator + CANTO_AGENTS_SECTION, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RepositoryConfigError(f"Cannot add Canto pointer to {path}: {exc}") from exc
    return path


def _ensure_agent_instructions(repository: Path) -> None:
    config_dir = repository / ".canto"
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    _write_if_missing(config_dir / "delegate.toml", DELEGATE_TOML)
    _write_canto_owned(agents_dir / "shared.md", SHARED_AGENT_INSTRUCTIONS)
    _write_canto_owned(agents_dir / "orchestrator.md", ORCHESTRATOR_AGENT_INSTRUCTIONS)
    _write_canto_owned(agents_dir / "executor.md", EXECUTOR_AGENT_INSTRUCTIONS)
    _ensure_agent_entrypoint(repository)


def _require_file(repository: Path, relative: str) -> str:
    if not (repository / relative).is_file():
        raise RepositoryConfigError(f"Missing repository bootstrap file: {relative}")
    return "present"


def _require_agent_pointer(repository: Path) -> str:
    path = repository / "AGENTS.md"
    if not path.is_file():
        raise RepositoryConfigError("Missing repository bootstrap file: AGENTS.md")
    if CANTO_AGENTS_MARKER_START not in path.read_text(encoding="utf-8"):
        raise RepositoryConfigError("AGENTS.md does not reference Canto instructions")
    return "Canto pointer present"


def initialize_repository(path: str | Path) -> RepositoryConfig:
    repository = git_root(path)
    common_dir, head, remotes = _git_metadata(repository)
    config_dir = repository / ".canto"
    repo_path = config_dir / "repo.toml"
    policy_path = config_dir / "policy.toml"
    if repo_path.exists() or policy_path.exists():
        if repo_path.is_file() and policy_path.is_file():
            config = load_repository(repository)
            _ensure_agent_instructions(repository)
            return config
        raise RepositoryConfigError(
            f"Incomplete Canto repository configuration in {config_dir}"
        )
    config = RepositoryConfig(
        repo_id=f"repo_{uuid4().hex}",
        canonical_path=str(repository),
        git_common_dir=common_dir,
        initial_head=head,
        remotes=remotes,
    )
    policy = RepositoryPolicy()
    config_dir.mkdir(mode=0o755)
    repo_lines = [
        f"version = {config.version}",
        f"repo_id = {_toml_string(config.repo_id)}",
        f"canonical_path = {_toml_string(config.canonical_path)}",
        f"git_common_dir = {_toml_string(config.git_common_dir)}",
        f"initial_head = {_toml_string(config.initial_head)}",
        "",
        "[remotes]",
    ]
    repo_lines.extend(
        f"{_toml_string(name)} = {_toml_string(url)}"
        for name, url in sorted(remotes.items())
    )
    policy_lines = [
        f"version = {policy.version}",
        f"allowed_paths = {_string_list(policy.allowed_paths)}",
        f"denied_paths = {_string_list(policy.denied_paths)}",
        f"allowed_commands = {_string_list(policy.allowed_commands)}",
        f"required_commands = {_string_list(policy.required_commands)}",
        f"allow_network = {str(policy.allow_network).lower()}",
        f"allow_secrets = {str(policy.allow_secrets).lower()}",
    ]
    repo_temp = repo_path.with_suffix(".toml.tmp")
    policy_temp = policy_path.with_suffix(".toml.tmp")
    try:
        repo_temp.write_text("\n".join(repo_lines) + "\n", encoding="utf-8")
        policy_temp.write_text("\n".join(policy_lines) + "\n", encoding="utf-8")
        repo_temp.replace(repo_path)
        policy_temp.replace(policy_path)
        _ensure_agent_instructions(repository)
    except OSError as exc:
        repo_temp.unlink(missing_ok=True)
        policy_temp.unlink(missing_ok=True)
        repo_path.unlink(missing_ok=True)
        policy_path.unlink(missing_ok=True)
        try:
            config_dir.rmdir()
        except OSError:
            pass
        raise RepositoryConfigError(
            f"Cannot initialize Canto repository configuration: {exc}"
        ) from exc
    return config


def doctor_repository(path: str | Path) -> RepositoryDoctorResult:
    repository = git_root(path)
    checks: list[RepositoryDoctorCheck] = []

    def check(name: str, action) -> None:
        try:
            detail = action()
            checks.append(RepositoryDoctorCheck(name=name, valid=True, detail=str(detail)))
        except (OSError, RepositoryConfigError, tomllib.TOMLDecodeError, ValidationError) as exc:
            checks.append(RepositoryDoctorCheck(name=name, valid=False, detail=str(exc)))

    check("repository_identity", lambda: f"repo_id={load_repository(repository).repo_id}")
    required = [
        ".canto/repo.toml",
        ".canto/policy.toml",
        ".canto/delegate.toml",
        ".canto/agents/shared.md",
        ".canto/agents/orchestrator.md",
        ".canto/agents/executor.md",
    ]
    for relative in required:
        check(relative, lambda relative=relative: _require_file(repository, relative))
    check("AGENTS.md", lambda: _require_agent_pointer(repository))
    status = _git(repository, "status", "--porcelain", "--", "AGENTS.md", ".canto")
    checks.append(
        RepositoryDoctorCheck(
            name="instruction_files_git_state",
            valid=not bool(status),
            detail="tracked and clean" if not status else "Commit bootstrap instruction files before delegation:\n" + status,
        )
    )
    return RepositoryDoctorResult(
        valid=all(item.valid for item in checks),
        repository=str(repository),
        checks=checks,
    )


def find_repository(path: str | Path) -> Path:
    repository = git_root(path)
    if not (repository / ".canto" / "repo.toml").is_file():
        raise RepositoryConfigError(
            "This Git repository is not initialized for Canto. Run: canto repo init"
        )
    return repository


def load_repository(path: str | Path) -> RepositoryConfig:
    repository = find_repository(path)
    repo_path = repository / ".canto" / "repo.toml"
    policy_path = repository / ".canto" / "policy.toml"
    if not policy_path.is_file():
        raise RepositoryConfigError(
            f"Canto repository policy is missing: {policy_path}"
        )
    try:
        config = RepositoryConfig.model_validate(tomllib.loads(repo_path.read_text()))
        RepositoryPolicy.model_validate(tomllib.loads(policy_path.read_text()))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise RepositoryConfigError(f"Invalid Canto repository configuration: {exc}") from exc
    common_dir, _, remotes = _git_metadata(repository)
    if Path(config.canonical_path).resolve() != repository:
        raise RepositoryConfigError(
            "Canto repository path changed; run an explicit repository relink before use"
        )
    if Path(config.git_common_dir).resolve() != Path(common_dir).resolve():
        raise RepositoryConfigError("Canto repository Git common-dir identity changed")
    if config.remotes and config.remotes != remotes:
        raise RepositoryConfigError("Canto repository remote metadata changed")
    return config


def load_repository_policy(path: str | Path) -> RepositoryPolicy:
    repository = find_repository(path)
    try:
        return RepositoryPolicy.model_validate(
            tomllib.loads((repository / ".canto" / "policy.toml").read_text())
        )
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise RepositoryConfigError(f"Invalid Canto repository policy: {exc}") from exc
