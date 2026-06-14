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
    def set_delegation_task(self, task_id: str, value: dict[str, Any]) -> None: ...
    def get_delegation_task(self, task_id: str) -> dict[str, Any] | None: ...
    def list_delegation_tasks(self) -> list[dict[str, Any]]: ...
    def transition_delegation_task(self, task_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool: ...
    def append_delegation_event(self, task_id: str, value: dict[str, Any]) -> None: ...
    def get_delegation_events(self, task_id: str) -> list[dict[str, Any]]: ...
    def set_executor_profile(self, executor_id: str, value: dict[str, Any]) -> None: ...
    def get_executor_profile(self, executor_id: str) -> dict[str, Any] | None: ...
    def list_executor_profiles(self) -> list[dict[str, Any]]: ...
    def append_delegation_record(self, task_id: str, record_type: str, record_id: str, value: dict[str, Any]) -> None: ...
    def get_delegation_records(self, task_id: str, record_type: str) -> list[dict[str, Any]]: ...


class SqliteStateStore:
    """Durable single-user state store backed by SQLite."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = Path(path).expanduser().resolve()
        self.read_only = read_only
        self._init_lock = RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self._ensure_initialized()
        return self._raw_connect()

    def _raw_connect(self) -> sqlite3.Connection:
        if self.read_only:
            wal_path = self.path.with_name(f"{self.path.name}-wal")
            query = "mode=ro" if wal_path.exists() else "mode=ro&immutable=1"
            connection = sqlite3.connect(
                f"{self.path.as_uri()}?{query}",
                timeout=30,
                uri=True,
            )
            connection.execute("PRAGMA query_only = ON")
        else:
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
            if self.read_only:
                if not self.path.is_file():
                    raise sqlite3.OperationalError(
                        f"Canto state database does not exist: {self.path}"
                    )
                self._initialized = True
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
                    CREATE TABLE IF NOT EXISTS delegation_tasks (
                        task_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS delegation_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        FOREIGN KEY(task_id) REFERENCES delegation_tasks(task_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS delegation_events_task_sequence
                        ON delegation_events(task_id, sequence);
                    CREATE TABLE IF NOT EXISTS executor_profiles (
                        executor_id TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS delegation_records (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        record_type TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        UNIQUE(task_id, record_type, record_id),
                        FOREIGN KEY(task_id) REFERENCES delegation_tasks(task_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS delegation_records_task_type_sequence
                        ON delegation_records(task_id, record_type, sequence);
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

    def set_delegation_task(self, task_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO delegation_tasks(task_id, status, value_json)
                VALUES (?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status, value_json=excluded.value_json""",
                (task_id, value["status"], self._dump(value)),
            )

    def get_delegation_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM delegation_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_delegation_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value_json FROM delegation_tasks ORDER BY task_id"
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def transition_delegation_task(
        self, task_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        if not expected_statuses:
            return False
        placeholders = ",".join("?" for _ in expected_statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""UPDATE delegation_tasks SET status = ?, value_json = ?
                WHERE task_id = ? AND status IN ({placeholders})""",
                (value["status"], self._dump(value), task_id, *sorted(expected_statuses)),
            )
        return cursor.rowcount == 1

    def append_delegation_event(self, task_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO delegation_events(task_id, value_json) VALUES (?, ?)",
                (task_id, self._dump(value)),
            )

    def get_delegation_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT value_json FROM delegation_events
                WHERE task_id = ? ORDER BY sequence""",
                (task_id,),
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def set_executor_profile(self, executor_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO executor_profiles(executor_id, value_json) VALUES (?, ?)
                ON CONFLICT(executor_id) DO UPDATE SET value_json=excluded.value_json""",
                (executor_id, self._dump(value)),
            )

    def get_executor_profile(self, executor_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM executor_profiles WHERE executor_id = ?",
                (executor_id,),
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_executor_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value_json FROM executor_profiles ORDER BY executor_id"
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def append_delegation_record(
        self, task_id: str, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO delegation_records(
                    task_id, record_type, record_id, value_json
                ) VALUES (?, ?, ?, ?)""",
                (task_id, record_type, record_id, self._dump(value)),
            )

    def get_delegation_records(
        self, task_id: str, record_type: str
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT value_json FROM delegation_records
                WHERE task_id = ? AND record_type = ? ORDER BY sequence""",
                (task_id, record_type),
            ).fetchall()
        return [self._load(row[0]) for row in rows]


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

    def set_delegation_task(self, task_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:delegation:{task_id}", json.dumps(value))
        self.client.sadd("canto:delegations", task_id)

    def get_delegation_task(self, task_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:delegation:{task_id}")
        return json.loads(value) if value else None

    def list_delegation_tasks(self) -> list[dict[str, Any]]:
        return [
            value
            for task_id in sorted(self.client.smembers("canto:delegations"))
            if (value := self.get_delegation_task(task_id)) is not None
        ]

    def transition_delegation_task(
        self, task_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        key = f"canto:delegation:{task_id}"
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
                    pipe.sadd("canto:delegations", task_id)
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def append_delegation_event(self, task_id: str, value: dict[str, Any]) -> None:
        self.client.rpush(f"canto:delegation:{task_id}:events", json.dumps(value))

    def get_delegation_events(self, task_id: str) -> list[dict[str, Any]]:
        return [
            json.loads(value)
            for value in self.client.lrange(
                f"canto:delegation:{task_id}:events", 0, -1
            )
        ]

    def set_executor_profile(self, executor_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:executor:{executor_id}", json.dumps(value))
        self.client.sadd("canto:executors", executor_id)

    def get_executor_profile(self, executor_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:executor:{executor_id}")
        return json.loads(value) if value else None

    def list_executor_profiles(self) -> list[dict[str, Any]]:
        return [
            value
            for executor_id in sorted(self.client.smembers("canto:executors"))
            if (value := self.get_executor_profile(executor_id)) is not None
        ]

    def append_delegation_record(
        self, task_id: str, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        key = f"canto:delegation:{task_id}:records:{record_type}"
        ids_key = f"{key}:ids"
        if not self.client.sadd(ids_key, record_id):
            raise ValueError(f"Delegation record already exists: {record_id}")
        self.client.rpush(key, json.dumps(value))

    def get_delegation_records(
        self, task_id: str, record_type: str
    ) -> list[dict[str, Any]]:
        return [
            json.loads(value)
            for value in self.client.lrange(
                f"canto:delegation:{task_id}:records:{record_type}", 0, -1
            )
        ]


class MemoryStateStore:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.artifacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.registry: dict[str, Any] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.delegation_tasks: dict[str, dict[str, Any]] = {}
        self.delegation_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.executor_profiles: dict[str, dict[str, Any]] = {}
        self.delegation_records: dict[
            tuple[str, str], list[dict[str, Any]]
        ] = defaultdict(list)
        self.delegation_record_ids: set[tuple[str, str, str]] = set()
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

    def set_delegation_task(self, task_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.delegation_tasks[task_id] = json.loads(json.dumps(value))

    def get_delegation_task(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.delegation_tasks.get(task_id)
            return json.loads(json.dumps(value)) if value else None

    def list_delegation_tasks(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                json.loads(json.dumps(self.delegation_tasks[task_id]))
                for task_id in sorted(self.delegation_tasks)
            ]

    def transition_delegation_task(
        self, task_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        with self.lock:
            current = self.delegation_tasks.get(task_id)
            if not current or current.get("status") not in expected_statuses:
                return False
            self.delegation_tasks[task_id] = json.loads(json.dumps(value))
            return True

    def append_delegation_event(self, task_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.delegation_events[task_id].append(json.loads(json.dumps(value)))

    def get_delegation_events(self, task_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(json.dumps(self.delegation_events[task_id]))

    def set_executor_profile(self, executor_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.executor_profiles[executor_id] = json.loads(json.dumps(value))

    def get_executor_profile(self, executor_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.executor_profiles.get(executor_id)
            return json.loads(json.dumps(value)) if value else None

    def list_executor_profiles(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                json.loads(json.dumps(self.executor_profiles[executor_id]))
                for executor_id in sorted(self.executor_profiles)
            ]

    def append_delegation_record(
        self, task_id: str, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        with self.lock:
            identity = (task_id, record_type, record_id)
            if identity in self.delegation_record_ids:
                raise ValueError(f"Delegation record already exists: {record_id}")
            self.delegation_record_ids.add(identity)
            self.delegation_records[(task_id, record_type)].append(
                json.loads(json.dumps(value))
            )

    def get_delegation_records(
        self, task_id: str, record_type: str
    ) -> list[dict[str, Any]]:
        with self.lock:
            return json.loads(
                json.dumps(self.delegation_records[(task_id, record_type)])
            )
