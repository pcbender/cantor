from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from canto.core.capability_manifest import (
    CapabilityManifest,
    CapabilityManifestError,
    CapabilityManifestValidator,
)
from canto.core.capability_package import (
    CapabilityPackageError,
    extract_package,
    pack_capability,
    provider_binding_errors,
    validate_package,
)


class LocalRegistryError(ValueError):
    """Raised when local registry metadata cannot be loaded."""


class RegistryEntry(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    installed: bool
    path: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    risk: Literal["low", "medium", "high"]


class InstalledCapability(BaseModel):
    entry: RegistryEntry
    manifest: CapabilityManifest


class InstalledValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InstallResult(BaseModel):
    entry: RegistryEntry
    warnings: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class LocalRegistryPaths:
    root: Path
    registry: Path
    installed: Path
    cache: Path

    @property
    def state_file(self) -> Path:
        return self.root / "state.sqlite"

    @property
    def legacy_state_file(self) -> Path:
        return self.root / "state" / "canto.db"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def vault(self) -> Path:
        return self.root / "vault"

    @property
    def plans(self) -> Path:
        return self.root / "plans"

    @property
    def index_file(self) -> Path:
        return self.registry / "index.json"

    @classmethod
    def from_home(cls, home: Path | None = None) -> LocalRegistryPaths:
        if home is None:
            configured = os.getenv("CANTO_HOME")
            root = Path(configured).expanduser() if configured else Path.home() / ".canto"
        else:
            root = Path(home).expanduser() / ".canto"
        return cls(
            root=root,
            registry=root / "registry",
            installed=root / "installed",
            cache=root / "cache",
        )

    def create(self) -> None:
        for path in (
            self.registry,
            self.installed,
            self.cache,
            self.plans,
            self.work,
            self.config,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_state()

    def _migrate_legacy_state(self) -> None:
        legacy = self.legacy_state_file
        target = self.state_file
        if legacy.exists() and target.exists():
            raise LocalRegistryError(
                "Both legacy and current SQLite state files exist; refusing to choose: "
                f"{legacy} and {target}"
            )
        if not legacy.exists():
            return
        temporary = target.with_suffix(".sqlite.tmp")
        temporary.unlink(missing_ok=True)
        try:
            with sqlite3.connect(legacy) as source, sqlite3.connect(temporary) as destination:
                source.backup(destination)
            temporary.chmod(0o600)
            temporary.replace(target)
            legacy.unlink()
            legacy.with_name(f"{legacy.name}-wal").unlink(missing_ok=True)
            legacy.with_name(f"{legacy.name}-shm").unlink(missing_ok=True)
            try:
                legacy.parent.rmdir()
            except OSError:
                pass
        except (OSError, sqlite3.Error) as exc:
            temporary.unlink(missing_ok=True)
            raise LocalRegistryError(
                f"Cannot migrate legacy SQLite state {legacy} to {target}: {exc}"
            ) from exc


class RegistryStore:
    def __init__(self, paths: LocalRegistryPaths | None = None):
        self.paths = paths or LocalRegistryPaths.from_home()

    @classmethod
    def from_home(cls, home: Path | None = None) -> RegistryStore:
        return cls(LocalRegistryPaths.from_home(home))

    def initialize(self) -> None:
        self.paths.create()

    def load(self) -> list[RegistryEntry]:
        if not self.paths.index_file.exists():
            return []

        try:
            data = json.loads(self.paths.index_file.read_text(encoding="utf-8"))
            return TypeAdapter(list[RegistryEntry]).validate_python(data)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise LocalRegistryError(
                f"Cannot load local registry index {self.paths.index_file}: {exc}"
            ) from exc

    def save(self, entries: list[RegistryEntry]) -> None:
        temporary_path = self.paths.index_file.with_suffix(".json.tmp")
        try:
            temporary_path.write_text(
                json.dumps(
                    [entry.model_dump(mode="json") for entry in entries],
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.paths.index_file)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise LocalRegistryError(
                f"Cannot save local registry index {self.paths.index_file}: {exc}"
            ) from exc

    def load_manifest(self, entry: RegistryEntry) -> CapabilityManifest:
        manifest_path = Path(entry.path) / "canto.yaml"
        try:
            return CapabilityManifest.load(manifest_path)
        except CapabilityManifestError as exc:
            raise LocalRegistryError(str(exc)) from exc

    def remove_installed_directory(self, entry: RegistryEntry) -> None:
        installed_root = self.paths.installed.resolve()
        target = Path(entry.path).resolve()
        if not target.is_relative_to(installed_root):
            raise LocalRegistryError(
                f"Installed path is outside registry root: {entry.path}"
            )
        if not target.is_dir():
            raise LocalRegistryError(f"Installed directory not found: {entry.path}")
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise LocalRegistryError(
                f"Cannot remove installed directory {entry.path}: {exc}"
            ) from exc

    def checksum_directory(self, directory: Path) -> str:
        digest = hashlib.sha256()
        try:
            files = sorted(path for path in directory.rglob("*") if path.is_file())
            for path in files:
                if path.is_symlink():
                    raise LocalRegistryError(
                        f"Installed capability contains a symbolic link: {path}"
                    )
                relative_path = path.relative_to(directory).as_posix().encode("utf-8")
                content = path.read_bytes()
                digest.update(relative_path)
                digest.update(b"\0")
                digest.update(str(len(content)).encode("ascii"))
                digest.update(b"\0")
                digest.update(content)
        except OSError as exc:
            raise LocalRegistryError(
                f"Cannot checksum installed directory {directory}: {exc}"
            ) from exc
        return f"sha256:{digest.hexdigest()}"

    def reject_symbolic_links(self, directory: Path) -> None:
        if directory.is_symlink():
            raise LocalRegistryError(f"Capability directory is a symbolic link: {directory}")
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise LocalRegistryError(
                    f"Capability directory contains a symbolic link: {path}"
                )

    def install_directory(self, source: Path, destination: Path) -> None:
        if destination.exists():
            raise LocalRegistryError(
                f"Capability is already installed at {destination}"
            )

        temporary_root = Path(tempfile.mkdtemp(prefix="install-", dir=self.paths.cache))
        staged = temporary_root / "package"
        try:
            shutil.copytree(source, staged)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(destination)
        except OSError as exc:
            raise LocalRegistryError(
                f"Cannot install capability directory {source}: {exc}"
            ) from exc
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)

    def discard_installed_directory(self, directory: Path) -> None:
        installed_root = self.paths.installed.resolve()
        target = directory.resolve()
        if not target.is_relative_to(installed_root):
            raise LocalRegistryError(
                f"Installed path is outside registry root: {directory}"
            )
        shutil.rmtree(target, ignore_errors=True)


class Registry:
    def __init__(self, store: RegistryStore):
        self.store = store

    @classmethod
    def local(cls, home: Path | None = None) -> Registry:
        store = RegistryStore.from_home(home)
        store.initialize()
        return cls(store)

    def list_installed(self) -> list[RegistryEntry]:
        return sorted(
            (entry for entry in self.store.load() if entry.installed),
            key=lambda entry: (entry.name, entry.version),
        )

    def search(self, query: str) -> list[RegistryEntry]:
        normalized_query = query.casefold()
        return sorted(
            (
                entry
                for entry in self.store.load()
                if normalized_query in entry.name.casefold()
            ),
            key=lambda entry: (entry.name, entry.version),
        )

    def inspect(self, name: str, version: str | None = None) -> InstalledCapability:
        matches = self._installed_matches(name, version)
        if not matches:
            identifier = f"{name} {version}" if version else name
            raise LocalRegistryError(f"Installed capability not found: {identifier}")
        if len(matches) > 1:
            raise LocalRegistryError(
                f"Multiple installed versions found for {name}; specify --version"
            )

        entry = matches[0]
        return InstalledCapability(
            entry=entry,
            manifest=self.store.load_manifest(entry),
        )

    def remove(self, name: str, version: str | None = None) -> RegistryEntry:
        entries = self.store.load()
        matches = self._installed_matches(name, version, entries)
        if not matches:
            identifier = f"{name} {version}" if version else name
            raise LocalRegistryError(f"Installed capability not found: {identifier}")
        if len(matches) > 1:
            raise LocalRegistryError(
                f"Multiple installed versions found for {name}; specify --version"
            )

        entry = matches[0]
        self.store.remove_installed_directory(entry)
        self.store.save([candidate for candidate in entries if candidate != entry])
        return entry

    def validate_installed(
        self, name: str, version: str | None = None
    ) -> InstalledValidationResult:
        capability = self.inspect(name, version)
        entry = capability.entry
        manifest = capability.manifest
        errors: list[str] = []

        expected_path = (
            self.store.paths.installed / entry.name / entry.version
        ).resolve()
        installed_path = Path(entry.path).resolve()
        if installed_path != expected_path:
            errors.append(
                f"registry path does not match installed layout: {entry.path}"
            )

        manifest_result = CapabilityManifestValidator.validate(manifest)
        errors.extend(manifest_result.errors)
        errors.extend(
            provider_binding_errors(
                manifest, lambda relative: (installed_path / relative).is_file()
            )
        )
        if manifest.name != entry.name:
            errors.append(
                f"manifest name {manifest.name} does not match registry name {entry.name}"
            )
        if manifest.version != entry.version:
            errors.append(
                "manifest version "
                f"{manifest.version} does not match registry version {entry.version}"
            )
        if manifest.risk.level != entry.risk:
            errors.append(
                f"manifest risk {manifest.risk.level} does not match registry risk {entry.risk}"
            )

        checksum = self.store.checksum_directory(installed_path)
        if checksum != entry.checksum:
            errors.append("installed directory checksum does not match registry checksum")

        return InstalledValidationResult(
            valid=not errors,
            errors=errors,
            warnings=manifest_result.warnings,
        )

    def install_directory(self, source: str | Path) -> InstallResult:
        source_input = Path(source).expanduser()
        if source_input.is_symlink():
            raise LocalRegistryError(
                f"Capability directory is a symbolic link: {source}"
            )
        if not source_input.is_dir():
            raise LocalRegistryError(
                f"Capability source must be a local directory: {source}"
            )
        source_path = source_input.resolve()
        self.store.reject_symbolic_links(source_path)

        try:
            manifest = CapabilityManifest.load(source_path / "canto.yaml")
        except CapabilityManifestError as exc:
            raise LocalRegistryError(str(exc)) from exc
        validation = CapabilityManifestValidator.validate(manifest)
        if not validation.valid:
            raise LocalRegistryError("Invalid capability manifest: " + "; ".join(validation.errors))
        binding_errors = provider_binding_errors(
            manifest, lambda relative: (source_path / relative).is_file()
        )
        if binding_errors:
            raise LocalRegistryError(
                "Invalid capability package: " + "; ".join(binding_errors)
            )

        entries = self.store.load()
        if any(
            entry.installed
            and entry.name == manifest.name
            and entry.version == manifest.version
            for entry in entries
        ):
            raise LocalRegistryError(
                f"Capability already installed: {manifest.name} {manifest.version}"
            )

        source_checksum = self.store.checksum_directory(source_path)
        destination = (
            self.store.paths.installed / manifest.name / manifest.version
        ).resolve()
        self.store.install_directory(source_path, destination)
        try:
            installed_checksum = self.store.checksum_directory(destination)
            if installed_checksum != source_checksum:
                raise LocalRegistryError(
                    "Installed capability checksum does not match source directory"
                )
            entry = RegistryEntry(
                name=manifest.name,
                version=manifest.version,
                installed=True,
                path=str(destination),
                checksum=installed_checksum,
                risk=manifest.risk.level,
            )
            retained_entries = [
                candidate
                for candidate in entries
                if not (
                    candidate.name == entry.name
                    and candidate.version == entry.version
                )
            ]
            self.store.save([*retained_entries, entry])
        except (LocalRegistryError, ValidationError):
            self.store.discard_installed_directory(destination)
            raise

        return InstallResult(
            entry=entry,
            warnings=validation.warnings,
            dependencies=manifest.dependencies,
        )

    def install_package(self, package: str | Path) -> InstallResult:
        package_path = Path(package).expanduser()
        if not package_path.is_file() or package_path.suffix != ".canto":
            raise LocalRegistryError(
                f"Capability package must be a local .canto archive: {package}"
            )
        validation = validate_package(package_path)
        if not validation.valid:
            raise LocalRegistryError(
                "Invalid capability package: " + "; ".join(validation.errors)
            )

        temporary_root = Path(
            tempfile.mkdtemp(prefix="archive-", dir=self.store.paths.cache)
        )
        extracted = temporary_root / "package"
        try:
            extract_package(package_path, extracted)
            result = self.install_directory(extracted)
        except CapabilityPackageError as exc:
            raise LocalRegistryError(str(exc)) from exc
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)
        return result

    def export(
        self,
        name: str,
        version: str | None = None,
        output_dir: str | Path = ".",
    ) -> Path:
        capability = self.inspect(name, version)
        validation = self.validate_installed(name, capability.entry.version)
        if not validation.valid:
            raise LocalRegistryError(
                "Installed capability is invalid: " + "; ".join(validation.errors)
            )
        try:
            return pack_capability(
                capability.entry.path,
                output_dir,
                replace_checksums=True,
            )
        except CapabilityPackageError as exc:
            raise LocalRegistryError(str(exc)) from exc

    def execution_roots(self) -> list[Path]:
        roots = []
        for entry in self.list_installed():
            validation = self.validate_installed(entry.name, entry.version)
            if not validation.valid:
                raise LocalRegistryError(
                    f"Installed capability is invalid: {entry.name} {entry.version}: "
                    + "; ".join(validation.errors)
                )
            roots.append(Path(entry.path))
        return roots

    def _installed_matches(
        self,
        name: str,
        version: str | None,
        entries: list[RegistryEntry] | None = None,
    ) -> list[RegistryEntry]:
        candidates = entries if entries is not None else self.store.load()
        return [
            entry
            for entry in candidates
            if entry.installed
            and entry.name == name
            and (version is None or entry.version == version)
        ]
