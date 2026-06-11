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


def initialize_repository(path: str | Path) -> RepositoryConfig:
    repository = git_root(path)
    common_dir, head, remotes = _git_metadata(repository)
    config_dir = repository / ".canto"
    repo_path = config_dir / "repo.toml"
    policy_path = config_dir / "policy.toml"
    if repo_path.exists() or policy_path.exists():
        if repo_path.is_file() and policy_path.is_file():
            return load_repository(repository)
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
