from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

import redis
from redis.exceptions import WatchError


class StateStore(Protocol):
    def ping(self) -> bool: ...
    def set_job(self, job_id: str, value: dict[str, Any]) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def transition_job(self, job_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool: ...
    def append_event(self, job_id: str, value: dict[str, Any]) -> None: ...
    def get_events(self, job_id: str) -> list[dict[str, Any]]: ...
    def set_artifacts(self, job_id: str, value: list[dict[str, Any]]) -> None: ...
    def get_artifacts(self, job_id: str) -> list[dict[str, Any]]: ...
    def set_approval(self, approval_id: str, value: dict[str, Any]) -> None: ...
    def get_approval(self, approval_id: str) -> dict[str, Any] | None: ...
    def transition_approval(self, approval_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool: ...
    def set_registry(self, value: dict[str, Any]) -> None: ...
    def get_registry(self) -> dict[str, Any] | None: ...
    def set_plan(self, plan_id: str, value: dict[str, Any]) -> None: ...
    def get_plan(self, plan_id: str) -> dict[str, Any] | None: ...
    def claim_idempotency(self, key: str, value: dict[str, Any]) -> dict[str, Any] | None: ...
    def set_idempotency(self, key: str, value: dict[str, Any]) -> None: ...


class SqliteStateStore:
    """Durable single-user state store backed by SQLite."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self._init_lock = RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        return self._raw_connect()

    def _raw_connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._raw_connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS job_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS job_events_job_sequence
                        ON job_events(job_id, sequence);
                    CREATE TABLE IF NOT EXISTS job_artifacts (
                        job_id TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS approvals (
                        approval_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS registry_snapshot (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS plans (
                        plan_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS idempotency_records (
                        idempotency_key TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        value_json TEXT NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(self.SCHEMA_VERSION)),
                )
                version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if version != (str(self.SCHEMA_VERSION),):
                    raise RuntimeError(
                        "Unsupported SQLite state schema version: "
                        f"{version[0] if version else 'missing'}"
                    )
            self.path.chmod(0o600)
            self._initialized = True

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _load(value: str | None) -> Any:
        return json.loads(value) if value is not None else None

    def ping(self) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone() == (1,)

    def set_job(self, job_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs(job_id, status, value_json) VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (job_id, value["status"], self._dump(value)),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def transition_job(
        self, job_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        if not expected_statuses:
            return False
        placeholders = ",".join("?" for _ in expected_statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""UPDATE jobs SET status = ?, value_json = ?
                WHERE job_id = ? AND status IN ({placeholders})""",
                (
                    value["status"],
                    self._dump(value),
                    job_id,
                    *sorted(expected_statuses),
                ),
            )
        return cursor.rowcount == 1

    def append_event(self, job_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO job_events(job_id, value_json) VALUES (?, ?)",
                (job_id, self._dump(value)),
            )

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT value_json FROM job_events
                WHERE job_id = ? ORDER BY sequence""",
                (job_id,),
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def set_artifacts(self, job_id: str, value: list[dict[str, Any]]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO job_artifacts(job_id, value_json) VALUES (?, ?)
                ON CONFLICT(job_id) DO UPDATE SET value_json=excluded.value_json""",
                (job_id, self._dump(value)),
            )

    def get_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM job_artifacts WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._load(row[0]) if row else []

    def set_approval(self, approval_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO approvals(approval_id, status, value_json)
                VALUES (?, ?, ?) ON CONFLICT(approval_id) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (approval_id, value["status"], self._dump(value)),
            )

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return self._load(row[0]) if row else None

    def transition_approval(
        self, approval_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        if not expected_statuses:
            return False
        placeholders = ",".join("?" for _ in expected_statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""UPDATE approvals SET status = ?, value_json = ?
                WHERE approval_id = ? AND status IN ({placeholders})""",
                (
                    value["status"],
                    self._dump(value),
                    approval_id,
                    *sorted(expected_statuses),
                ),
            )
        return cursor.rowcount == 1

    def set_registry(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO registry_snapshot(singleton, value_json) VALUES (1, ?)
                ON CONFLICT(singleton) DO UPDATE SET value_json=excluded.value_json""",
                (self._dump(value),),
            )

    def get_registry(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM registry_snapshot WHERE singleton = 1"
            ).fetchone()
        return self._load(row[0]) if row else None

    def set_plan(self, plan_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO plans(plan_id, status, value_json) VALUES (?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (plan_id, value["status"], self._dump(value)),
            )

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def claim_idempotency(
        self, key: str, value: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, value_json FROM idempotency_records WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row and row[0] != "failed":
                return self._load(row[1])
            connection.execute(
                """INSERT INTO idempotency_records(idempotency_key, status, value_json)
                VALUES (?, ?, ?) ON CONFLICT(idempotency_key) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (key, value["status"], self._dump(value)),
            )
        return None

    def set_idempotency(self, key: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO idempotency_records(idempotency_key, status, value_json)
                VALUES (?, ?, ?) ON CONFLICT(idempotency_key) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (key, value["status"], self._dump(value)),
            )


class RedisStateStore:
    def __init__(self, url: str):
        self.client = redis.Redis.from_url(url, decode_responses=True)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def set_job(self, job_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:job:{job_id}", json.dumps(value))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:job:{job_id}")
        return json.loads(value) if value else None

    def transition_job(self, job_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool:
        key = f"canto:job:{job_id}"
        while True:
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    current = pipe.get(key)
                    if not current or json.loads(current).get("status") not in expected_statuses:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.set(key, json.dumps(value))
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def append_event(self, job_id: str, value: dict[str, Any]) -> None:
        self.client.rpush(f"canto:job:{job_id}:events", json.dumps(value))

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        return [json.loads(value) for value in self.client.lrange(f"canto:job:{job_id}:events", 0, -1)]

    def set_artifacts(self, job_id: str, value: list[dict[str, Any]]) -> None:
        self.client.set(f"canto:job:{job_id}:artifacts", json.dumps(value))

    def get_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        value = self.client.get(f"canto:job:{job_id}:artifacts")
        return json.loads(value) if value else []

    def set_approval(self, approval_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:approval:{approval_id}", json.dumps(value))

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:approval:{approval_id}")
        return json.loads(value) if value else None

    def transition_approval(
        self, approval_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        key = f"canto:approval:{approval_id}"
        while True:
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    current = pipe.get(key)
                    if not current or json.loads(current).get("status") not in expected_statuses:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.set(key, json.dumps(value))
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def set_registry(self, value: dict[str, Any]) -> None:
        self.client.set("canto:registry:snapshot", json.dumps(value))

    def get_registry(self) -> dict[str, Any] | None:
        value = self.client.get("canto:registry:snapshot")
        return json.loads(value) if value else None

    def set_plan(self, plan_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:plan:{plan_id}", json.dumps(value))

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:plan:{plan_id}")
        return json.loads(value) if value else None

    def claim_idempotency(
        self, key: str, value: dict[str, Any]
    ) -> dict[str, Any] | None:
        redis_key = f"canto:idempotency:{key}"
        while True:
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(redis_key)
                    current = pipe.get(redis_key)
                    if current and json.loads(current).get("status") != "failed":
                        pipe.unwatch()
                        return json.loads(current)
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(value))
                    pipe.execute()
                    return None
                except WatchError:
                    continue

    def set_idempotency(self, key: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:idempotency:{key}", json.dumps(value))


class MemoryStateStore:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.artifacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.registry: dict[str, Any] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.lock = RLock()

    def ping(self) -> bool:
        return True

    def set_job(self, job_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.jobs[job_id] = json.loads(json.dumps(value))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.jobs.get(job_id)
            return json.loads(json.dumps(value)) if value else None

    def transition_job(self, job_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool:
        with self.lock:
            current = self.jobs.get(job_id)
            if not current or current.get("status") not in expected_statuses:
                return False
            self.jobs[job_id] = json.loads(json.dumps(value))
            return True

    def append_event(self, job_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.events[job_id].append(json.loads(json.dumps(value)))

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.events[job_id]))

    def set_artifacts(self, job_id: str, value: list[dict[str, Any]]) -> None:
        with self.lock:
            self.artifacts[job_id] = json.loads(json.dumps(value))

    def get_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.artifacts[job_id]))

    def set_approval(self, approval_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.approvals[approval_id] = json.loads(json.dumps(value))

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.approvals.get(approval_id)
            return json.loads(json.dumps(value)) if value else None

    def transition_approval(
        self, approval_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        with self.lock:
            current = self.approvals.get(approval_id)
            if not current or current.get("status") not in expected_statuses:
                return False
            self.approvals[approval_id] = json.loads(json.dumps(value))
            return True

    def set_registry(self, value: dict[str, Any]) -> None:
        with self.lock:
            self.registry = json.loads(json.dumps(value))

    def get_registry(self) -> dict[str, Any] | None:
        with self.lock:
            return json.loads(json.dumps(self.registry)) if self.registry else None

    def set_plan(self, plan_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.plans[plan_id] = json.loads(json.dumps(value))

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.plans.get(plan_id)
            return json.loads(json.dumps(value)) if value else None

    def claim_idempotency(
        self, key: str, value: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self.lock:
            current = self.idempotency.get(key)
            if current and current.get("status") != "failed":
                return json.loads(json.dumps(current))
            self.idempotency[key] = json.loads(json.dumps(value))
            return None

    def set_idempotency(self, key: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.idempotency[key] = json.loads(json.dumps(value))
