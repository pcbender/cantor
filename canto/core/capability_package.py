from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from pydantic import BaseModel, Field

from canto.core.capability_manifest import (
    CapabilityManifest,
    CapabilityManifestError,
    CapabilityManifestValidator,
)


CHECKSUMS_NAME = "CHECKSUMS.sha256"
MANIFEST_NAME = "canto.yaml"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
}
EXCLUDED_FILE_NAMES = {".env"}


class CapabilityPackageError(ValueError):
    """Raised when a capability package cannot be created or validated."""


class PackageValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manifest: CapabilityManifest | None = None


def provider_binding_errors(
    manifest: CapabilityManifest, contains: Callable[[str], bool]
) -> list[str]:
    if manifest.execution is None:
        return []
    errors = []
    for binding in manifest.execution.providers:
        skill_path = f"skills/{binding.skill}/skill.yaml"
        provider_path = (
            f"skills/{binding.skill}/providers/{binding.provider}/provider.yaml"
        )
        missing = [
            path for path in (skill_path, provider_path) if not contains(path)
        ]
        if missing:
            errors.append(
                "Missing execution provider binding "
                f"({binding.skill}, {binding.provider}): {', '.join(missing)}"
            )
    return errors


def _source_manifest_path(source: Path) -> Path:
    candidates = [path for path in (source / "canto.yaml", source / "manifest.yaml") if path.is_file()]
    if not candidates:
        raise CapabilityPackageError(
            f"Capability directory must contain canto.yaml or manifest.yaml: {source}"
        )
    if len(candidates) > 1:
        raise CapabilityPackageError(
            f"Capability directory contains both canto.yaml and manifest.yaml: {source}"
        )
    return candidates[0]


def _validate_source(source: Path) -> tuple[CapabilityManifest, Path]:
    if source.is_symlink() or not source.is_dir():
        raise CapabilityPackageError(f"Capability source must be a local directory: {source}")
    manifest_path = _source_manifest_path(source)
    try:
        manifest = CapabilityManifest.load(manifest_path)
    except CapabilityManifestError as exc:
        raise CapabilityPackageError(str(exc)) from exc
    result = CapabilityManifestValidator.validate(manifest)
    if not result.valid:
        raise CapabilityPackageError("Invalid capability manifest: " + "; ".join(result.errors))
    binding_errors = provider_binding_errors(
        manifest, lambda relative: (source / relative).is_file()
    )
    if binding_errors:
        raise CapabilityPackageError("Invalid capability package: " + "; ".join(binding_errors))
    return manifest, manifest_path


def _excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
        return True
    name = relative.name
    return (
        name in EXCLUDED_FILE_NAMES
        or name.endswith(".pyc")
        or name.endswith(".canto")
    )


def collect_package_files(
    source: Path, manifest_path: Path, *, replace_checksums: bool = False
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise CapabilityPackageError(f"Capability contains a symbolic link: {relative}")
        if not path.is_file() or _excluded(relative):
            continue
        archive_path = MANIFEST_NAME if path == manifest_path else relative.as_posix()
        if archive_path == CHECKSUMS_NAME:
            if replace_checksums:
                continue
            raise CapabilityPackageError(
                f"Capability source must not contain generated {CHECKSUMS_NAME}"
            )
        if archive_path in files:
            raise CapabilityPackageError(f"Duplicate package path: {archive_path}")
        files[archive_path] = path.read_bytes()
    return dict(sorted(files.items()))


def build_checksums(files: dict[str, bytes]) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {path}"
        for path, content in sorted(files.items())
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def pack_capability(
    source: str | Path,
    output_dir: str | Path = ".",
    *,
    replace_checksums: bool = False,
) -> Path:
    source_path = Path(source).expanduser().resolve()
    manifest, manifest_path = _validate_source(source_path)
    files = collect_package_files(
        source_path, manifest_path, replace_checksums=replace_checksums
    )
    if MANIFEST_NAME not in files:
        raise CapabilityPackageError("Package manifest was not collected")
    files[CHECKSUMS_NAME] = build_checksums(files)

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    package_path = output / f"{manifest.name}-{manifest.version}.canto"
    temporary_path = package_path.with_suffix(".canto.tmp")
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for archive_path, content in sorted(files.items()):
                archive.writestr(_zip_info(archive_path), content, compresslevel=9)
        temporary_path.replace(package_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise CapabilityPackageError(f"Cannot create capability package: {exc}") from exc
    validation = validate_package(package_path)
    if not validation.valid:
        package_path.unlink(missing_ok=True)
        raise CapabilityPackageError(
            "Created package failed validation: " + "; ".join(validation.errors)
        )
    return package_path


def safe_archive_path(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _parse_checksums(content: bytes) -> tuple[dict[str, str], list[str]]:
    errors = []
    checksums: dict[str, str] = {}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {}, [f"{CHECKSUMS_NAME} is not valid UTF-8: {exc}"]
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            errors.append(f"Invalid checksum record on line {line_number}")
            continue
        digest, path = parts
        try:
            int(digest, 16)
        except ValueError:
            errors.append(f"Invalid SHA-256 digest on line {line_number}")
            continue
        if not safe_archive_path(path) or path == CHECKSUMS_NAME:
            errors.append(f"Invalid checksum path on line {line_number}: {path}")
            continue
        if path in checksums:
            errors.append(f"Duplicate checksum path: {path}")
            continue
        checksums[path] = digest
    return checksums, errors


def validate_package(package: str | Path) -> PackageValidationResult:
    package_path = Path(package)
    errors: list[str] = []
    warnings: list[str] = []
    manifest = None
    try:
        package_bytes = package_path.read_bytes()
        archive_context = zipfile.ZipFile(io.BytesIO(package_bytes))
    except (OSError, zipfile.BadZipFile) as exc:
        return PackageValidationResult(
            valid=False,
            errors=[f"Cannot read capability package {package_path}: {exc}"],
        )

    with archive_context as archive:
        names = [info.filename for info in archive.infolist()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            errors.append(f"Duplicate archive paths: {duplicates}")
        for info in archive.infolist():
            if not safe_archive_path(info.filename):
                errors.append(f"Unsafe archive path: {info.filename}")
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == 0o120000:
                errors.append(f"Symbolic links are not allowed: {info.filename}")
            if info.is_dir():
                errors.append(f"Directory entries are not allowed: {info.filename}")

        name_set = set(names)
        if MANIFEST_NAME not in name_set:
            errors.append(f"Package is missing {MANIFEST_NAME}")
        if CHECKSUMS_NAME not in name_set:
            errors.append(f"Package is missing {CHECKSUMS_NAME}")

        checksums: dict[str, str] = {}
        if CHECKSUMS_NAME in name_set and names.count(CHECKSUMS_NAME) == 1:
            parsed, checksum_errors = _parse_checksums(archive.read(CHECKSUMS_NAME))
            checksums = parsed
            errors.extend(checksum_errors)

        content_names = name_set - {CHECKSUMS_NAME}
        missing_records = sorted(content_names - set(checksums))
        extra_records = sorted(set(checksums) - content_names)
        if missing_records:
            errors.append(f"Files missing checksum records: {missing_records}")
        if extra_records:
            errors.append(f"Checksum records reference missing files: {extra_records}")
        for name, expected_digest in checksums.items():
            if name not in content_names or names.count(name) != 1:
                continue
            actual_digest = hashlib.sha256(archive.read(name)).hexdigest()
            if actual_digest != expected_digest:
                errors.append(f"Checksum mismatch: {name}")

        if MANIFEST_NAME in name_set and names.count(MANIFEST_NAME) == 1:
            try:
                manifest = CapabilityManifest.from_yaml(
                    archive.read(MANIFEST_NAME).decode("utf-8"),
                    source=f"{package_path}:{MANIFEST_NAME}",
                )
                validation = CapabilityManifestValidator.validate(manifest)
                errors.extend(validation.errors)
                warnings.extend(validation.warnings)
                errors.extend(
                    provider_binding_errors(manifest, lambda path: path in name_set)
                )
                for skill in manifest.skills:
                    expected = f"skills/{skill}/skill.yaml"
                    if expected not in name_set:
                        errors.append(f"Package is missing declared skill: {expected}")
                for provider in manifest.providers:
                    if "." not in provider:
                        errors.append(
                            f"Provider identifier must use skill.provider: {provider}"
                        )
                        continue
                    skill, provider_name = provider.split(".", 1)
                    expected = (
                        f"skills/{skill}/providers/{provider_name}/provider.yaml"
                    )
                    if expected not in name_set:
                        errors.append(f"Package is missing declared provider: {expected}")
                for tool in manifest.tools:
                    expected = f"tools/{tool}/tool.yaml"
                    if expected not in name_set:
                        errors.append(f"Package is missing declared tool: {expected}")
            except (UnicodeDecodeError, CapabilityManifestError) as exc:
                errors.append(str(exc))

    return PackageValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        manifest=manifest,
    )


def extract_package(package: str | Path, destination: str | Path) -> Path:
    result = validate_package(package)
    if not result.valid:
        raise CapabilityPackageError("Invalid capability package: " + "; ".join(result.errors))

    destination_path = Path(destination)
    destination_path.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(package) as archive:
            for info in archive.infolist():
                target = destination_path / PurePosixPath(info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info.filename))
    except (OSError, zipfile.BadZipFile) as exc:
        raise CapabilityPackageError(f"Cannot extract capability package: {exc}") from exc
    return destination_path
