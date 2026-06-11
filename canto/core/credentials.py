from __future__ import annotations

import base64
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

class CredentialError(ValueError):
    """Raised when a credential reference or vault record is invalid."""


VAULT_REFERENCE = re.compile(
    r"vault:(?P<scope>[a-z][a-z0-9_-]{0,63})/(?P<name>[a-z][a-z0-9_-]{0,63})"
)


class CredentialVault:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.key_path = self.root / "master.key"
        self.records_dir = self.root / "records"

    @classmethod
    def local(cls) -> "CredentialVault":
        canto_home = Path(os.getenv("CANTO_HOME", Path.home() / ".canto"))
        return cls(canto_home / "vault")

    def _initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.records_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.records_dir, 0o700)
        if not self.key_path.exists():
            try:
                fd = os.open(
                    self.key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
        os.chmod(self.key_path, 0o600)

    def _key(self) -> bytes:
        self._initialize()
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise CredentialError("Credential vault master key is invalid")
        return key

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
            raise CredentialError(
                f"Credential {label} must start with a lowercase letter and use "
                "lowercase letters, numbers, underscores, or hyphens"
            )

    def _path(self, scope: str, name: str) -> Path:
        self._validate_identifier(scope, "scope")
        self._validate_identifier(name, "name")
        return self.records_dir / f"{scope}--{name}.json"

    def set(self, scope: str, name: str, value: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if not value:
            raise CredentialError("Credential value cannot be empty")
        path = self._path(scope, name)
        key = self._key()
        nonce = secrets.token_bytes(12)
        associated_data = f"{scope}/{name}".encode()
        ciphertext = AESGCM(key).encrypt(nonce, value.encode(), associated_data)
        generation = 1
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                generation = int(current.get("generation", 1)) + 1
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                raise CredentialError(
                    f"Existing credential record vault:{scope}/{name} is invalid"
                )
        record = {
            "version": 1,
            "generation": generation,
            "scope": scope,
            "name": name,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        return f"vault:{scope}/{name}"

    def rotate(self, scope: str, name: str, value: str) -> str:
        if not self._path(scope, name).is_file():
            raise CredentialError(f"Unknown credential: vault:{scope}/{name}")
        return self.set(scope, name, value)

    def generation(self, scope: str, name: str) -> int:
        path = self._path(scope, name)
        if not path.is_file():
            raise CredentialError(f"Unknown credential: vault:{scope}/{name}")
        try:
            return int(json.loads(path.read_text(encoding="utf-8"))["generation"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CredentialError(
                f"Credential record vault:{scope}/{name} is invalid"
            ) from exc

    def get(self, scope: str, name: str) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        path = self._path(scope, name)
        if not path.is_file():
            raise CredentialError(f"Unknown credential: vault:{scope}/{name}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            nonce = base64.b64decode(record["nonce"], validate=True)
            ciphertext = base64.b64decode(record["ciphertext"], validate=True)
            plaintext = AESGCM(self._key()).decrypt(
                nonce, ciphertext, f"{scope}/{name}".encode()
            )
        except Exception as exc:
            raise CredentialError(
                f"Credential record vault:{scope}/{name} cannot be decrypted"
            ) from exc
        return plaintext.decode()

    def delete(self, scope: str, name: str) -> None:
        path = self._path(scope, name)
        if not path.is_file():
            raise CredentialError(f"Unknown credential: vault:{scope}/{name}")
        path.unlink()

    def list(self) -> list[str]:
        if not self.records_dir.is_dir():
            return []
        records = []
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                records.append(f"vault:{record['scope']}/{record['name']}")
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        return records

    def resolve_reference(self, reference: str) -> str:
        if reference.startswith("env:"):
            variable = reference.removeprefix("env:")
            value = os.getenv(variable)
            if value is None:
                raise CredentialError(f"Environment credential is not set: {variable}")
            return value
        match = VAULT_REFERENCE.fullmatch(reference)
        if not match:
            raise CredentialError(f"Unsupported credential reference: {reference}")
        return self.get(match.group("scope"), match.group("name"))


def resolve_credential_inputs(
    value: Any, vault: CredentialVault
) -> tuple[Any, list[str]]:
    secrets_found: list[str] = []

    def resolve(item: Any, key: str | None = None) -> Any:
        if isinstance(item, dict):
            return {name: resolve(child, str(name)) for name, child in item.items()}
        if isinstance(item, list):
            return [resolve(child) for child in item]
        if key and key.lower().endswith("_ref") and isinstance(item, str):
            secret = vault.resolve_reference(item)
            secrets_found.extend([item, secret])
            return secret
        return item

    return resolve(value), secrets_found
