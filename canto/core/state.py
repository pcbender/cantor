from __future__ import annotations

import json
import re
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
    def set_ai_record(self, record_type: str, record_id: str, value: dict[str, Any]) -> None: ...
    def get_ai_record(self, record_type: str, record_id: str) -> dict[str, Any] | None: ...
    def list_ai_records(self, record_type: str) -> list[dict[str, Any]]: ...
    def delete_ai_record(self, record_type: str, record_id: str) -> bool: ...
    def set_memory_item(self, memory_id: str, value: dict[str, Any]) -> None: ...
    def get_memory_item(self, memory_id: str) -> dict[str, Any] | None: ...
    def list_memory_items(self) -> list[dict[str, Any]]: ...
    def search_memory_items(self, query: str) -> list[dict[str, Any]]: ...
    def transition_memory_item(self, memory_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool: ...
    def delete_memory_item(self, memory_id: str) -> bool: ...
    def append_memory_event(self, memory_id: str, value: dict[str, Any]) -> None: ...
    def get_memory_events(self, memory_id: str | None = None) -> list[dict[str, Any]]: ...
    def set_memory_project(self, project_id: str, value: dict[str, Any]) -> None: ...
    def get_memory_project(self, project_id: str) -> dict[str, Any] | None: ...
    def list_memory_projects(self) -> list[dict[str, Any]]: ...
    def transition_memory_approval(
        self,
        approval_id: str,
        memory_id: str,
        approval_expected: set[str],
        memory_expected: set[str],
        approval_value: dict[str, Any],
        memory_value: dict[str, Any],
    ) -> bool: ...


class SqliteStateStore:
    """Durable single-user state store backed by SQLite."""

    SCHEMA_VERSION = 2

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
                    CREATE TABLE IF NOT EXISTS ai_records (
                        record_type TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        PRIMARY KEY(record_type, record_id)
                    );
                    CREATE INDEX IF NOT EXISTS ai_records_type
                        ON ai_records(record_type, record_id);
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
                    ("schema_version", "1"),
                )
                version = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                current = int(version[0]) if version else 0
                if current > self.SCHEMA_VERSION:
                    raise RuntimeError(
                        "Unsupported SQLite state schema version: "
                        f"{current}"
                    )
                connection.commit()
                self._migrate(connection, current)
            self.path.chmod(0o600)
            self._initialized = True

    def _migrate(self, connection: sqlite3.Connection, current: int) -> None:
        migrations: dict[int, tuple[str, ...]] = {
            2: (
                """CREATE TABLE memory_items (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    repo_id TEXT,
                    project_id TEXT,
                    value_json TEXT NOT NULL
                )""",
                "CREATE INDEX memory_items_scope_status ON memory_items(scope, status)",
                "CREATE INDEX memory_items_type_status ON memory_items(type, status)",
                """CREATE TABLE memory_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    memory_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
                )""",
                "CREATE INDEX memory_events_memory_sequence ON memory_events(memory_id, sequence)",
                """CREATE TABLE memory_links (
                    link_id TEXT PRIMARY KEY,
                    from_memory_id TEXT NOT NULL,
                    to_memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    FOREIGN KEY(from_memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE,
                    FOREIGN KEY(to_memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
                )""",
                """CREATE TABLE memory_aliases (
                    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    UNIQUE(memory_id, normalized_alias),
                    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
                )""",
                "CREATE INDEX memory_aliases_normalized ON memory_aliases(normalized_alias)",
                """CREATE TABLE memory_tags (
                    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    normalized_tag TEXT NOT NULL,
                    UNIQUE(memory_id, normalized_tag),
                    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
                )""",
                """CREATE TABLE memory_projects (
                    project_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    value_json TEXT NOT NULL
                )""",
                """CREATE TABLE memory_project_repositories (
                    project_id TEXT NOT NULL,
                    repo_id TEXT NOT NULL,
                    PRIMARY KEY(project_id, repo_id),
                    FOREIGN KEY(project_id) REFERENCES memory_projects(project_id) ON DELETE CASCADE
                )""",
                """CREATE VIRTUAL TABLE memory_fts USING fts5(
                    memory_id UNINDEXED, title, body, aliases, tags
                )""",
            )
        }
        for target in range(current + 1, self.SCHEMA_VERSION + 1):
            statements = migrations.get(target)
            if not statements:
                raise RuntimeError(f"Missing SQLite state migration: {target}")
            try:
                connection.execute("BEGIN")
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                    (str(target),),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _load(value: str | None) -> Any:
        return json.loads(value) if value is not None else None

    @staticmethod
    def _has_table(connection: sqlite3.Connection, name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        ).fetchone() is not None

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

    def set_ai_record(
        self, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO ai_records(record_type, record_id, value_json)
                VALUES (?, ?, ?) ON CONFLICT(record_type, record_id) DO UPDATE SET
                    value_json=excluded.value_json""",
                (record_type, record_id, self._dump(value)),
            )

    def get_ai_record(
        self, record_type: str, record_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM ai_records WHERE record_type = ? AND record_id = ?",
                (record_type, record_id),
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_ai_records(self, record_type: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value_json FROM ai_records WHERE record_type = ? ORDER BY record_id",
                (record_type,),
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def delete_ai_record(self, record_type: str, record_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM ai_records WHERE record_type = ? AND record_id = ?",
                (record_type, record_id),
            )
        return cursor.rowcount > 0

    def set_memory_item(self, memory_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memory_items(
                    memory_id, scope, type, status, title, body, repo_id, project_id, value_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    scope=excluded.scope, type=excluded.type, status=excluded.status,
                    title=excluded.title, body=excluded.body, repo_id=excluded.repo_id,
                    project_id=excluded.project_id, value_json=excluded.value_json""",
                (
                    memory_id, value["scope"], value["type"], value["status"],
                    value["title"], value["body"], value.get("repo_id"),
                    value.get("project_id"), self._dump(value),
                ),
            )
            self._sync_memory_index(connection, memory_id, value)

    def _sync_memory_index(
        self, connection: sqlite3.Connection, memory_id: str, value: dict[str, Any]
    ) -> None:
        connection.execute("DELETE FROM memory_aliases WHERE memory_id = ?", (memory_id,))
        connection.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory_id,))
        for alias in value.get("aliases", []):
            connection.execute(
                "INSERT INTO memory_aliases(memory_id, alias, normalized_alias) VALUES (?, ?, ?)",
                (memory_id, alias, alias.casefold().strip()),
            )
        for tag in value.get("tags", []):
            connection.execute(
                "INSERT INTO memory_tags(memory_id, tag, normalized_tag) VALUES (?, ?, ?)",
                (memory_id, tag, tag.casefold().strip()),
            )
        connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        connection.execute(
            "INSERT INTO memory_fts(memory_id, title, body, aliases, tags) VALUES (?, ?, ?, ?, ?)",
            (memory_id, value["title"], value["body"], " ".join(value.get("aliases", [])), " ".join(value.get("tags", []))),
        )

    def get_memory_item(self, memory_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            if not self._has_table(connection, "memory_items"):
                return None
            row = connection.execute(
                "SELECT value_json FROM memory_items WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_memory_items(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if not self._has_table(connection, "memory_items"):
                return []
            rows = connection.execute(
                "SELECT value_json FROM memory_items ORDER BY memory_id"
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def search_memory_items(self, query: str) -> list[dict[str, Any]]:
        terms = [term for term in re.findall(r"[a-z0-9_@.-]+", query.casefold()) if len(term) > 1]
        if not terms:
            return self.list_memory_items()
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self._connect() as connection:
            if not self._has_table(connection, "memory_fts"):
                return []
            rows = connection.execute(
                """SELECT item.value_json FROM memory_fts fts
                JOIN memory_items item ON item.memory_id = fts.memory_id
                WHERE memory_fts MATCH ? ORDER BY rank, item.memory_id""",
                (expression,),
            ).fetchall()
        return [self._load(row[0]) for row in rows]

    def transition_memory_item(
        self, memory_id: str, expected_statuses: set[str], value: dict[str, Any]
    ) -> bool:
        if not expected_statuses:
            return False
        placeholders = ",".join("?" for _ in expected_statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""UPDATE memory_items SET scope=?, type=?, status=?, title=?, body=?,
                    repo_id=?, project_id=?, value_json=?
                    WHERE memory_id=? AND status IN ({placeholders})""",
                (
                    value["scope"], value["type"], value["status"], value["title"],
                    value["body"], value.get("repo_id"), value.get("project_id"),
                    self._dump(value), memory_id, *sorted(expected_statuses),
                ),
            )
            if cursor.rowcount == 1:
                self._sync_memory_index(connection, memory_id, value)
        return cursor.rowcount == 1

    def delete_memory_item(self, memory_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            cursor = connection.execute("DELETE FROM memory_items WHERE memory_id = ?", (memory_id,))
        return cursor.rowcount == 1

    def append_memory_event(self, memory_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_events(event_id, memory_id, event_type, value_json) VALUES (?, ?, ?, ?)",
                (value["event_id"], memory_id, value["event_type"], self._dump(value)),
            )

    def get_memory_events(self, memory_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if not self._has_table(connection, "memory_events"):
                return []
            if memory_id:
                rows = connection.execute(
                    "SELECT value_json FROM memory_events WHERE memory_id=? ORDER BY sequence", (memory_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT value_json FROM memory_events ORDER BY sequence").fetchall()
        return [self._load(row[0]) for row in rows]

    def set_memory_project(self, project_id: str, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memory_projects(project_id, label, value_json) VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET label=excluded.label, value_json=excluded.value_json""",
                (project_id, value["label"], self._dump(value)),
            )
            connection.execute("DELETE FROM memory_project_repositories WHERE project_id=?", (project_id,))
            for repo_id in value.get("repository_ids", []):
                connection.execute(
                    "INSERT INTO memory_project_repositories(project_id, repo_id) VALUES (?, ?)",
                    (project_id, repo_id),
                )

    def get_memory_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            if not self._has_table(connection, "memory_projects"):
                return None
            row = connection.execute(
                "SELECT value_json FROM memory_projects WHERE project_id=?", (project_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list_memory_projects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if not self._has_table(connection, "memory_projects"):
                return []
            rows = connection.execute("SELECT value_json FROM memory_projects ORDER BY project_id").fetchall()
        return [self._load(row[0]) for row in rows]

    def transition_memory_approval(
        self,
        approval_id: str,
        memory_id: str,
        approval_expected: set[str],
        memory_expected: set[str],
        approval_value: dict[str, Any],
        memory_value: dict[str, Any],
    ) -> bool:
        if not approval_expected or not memory_expected:
            return False
        approval_marks = ",".join("?" for _ in approval_expected)
        memory_marks = ",".join("?" for _ in memory_expected)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approval_cursor = connection.execute(
                f"""UPDATE approvals SET status=?, value_json=?
                WHERE approval_id=? AND status IN ({approval_marks})""",
                (approval_value["status"], self._dump(approval_value), approval_id, *sorted(approval_expected)),
            )
            memory_cursor = connection.execute(
                f"""UPDATE memory_items SET scope=?, type=?, status=?, title=?, body=?,
                    repo_id=?, project_id=?, value_json=?
                WHERE memory_id=? AND status IN ({memory_marks})""",
                (
                    memory_value["scope"], memory_value["type"], memory_value["status"],
                    memory_value["title"], memory_value["body"], memory_value.get("repo_id"),
                    memory_value.get("project_id"), self._dump(memory_value), memory_id,
                    *sorted(memory_expected),
                ),
            )
            if approval_cursor.rowcount != 1 or memory_cursor.rowcount != 1:
                connection.rollback()
                return False
            self._sync_memory_index(connection, memory_id, memory_value)
            connection.commit()
        return True


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

    def set_ai_record(
        self, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        self.client.set(f"canto:ai:{record_type}:{record_id}", json.dumps(value))
        self.client.sadd(f"canto:ai:{record_type}:ids", record_id)

    def get_ai_record(
        self, record_type: str, record_id: str
    ) -> dict[str, Any] | None:
        value = self.client.get(f"canto:ai:{record_type}:{record_id}")
        return json.loads(value) if value else None

    def list_ai_records(self, record_type: str) -> list[dict[str, Any]]:
        return [
            value
            for record_id in sorted(self.client.smembers(f"canto:ai:{record_type}:ids"))
            if (value := self.get_ai_record(record_type, record_id)) is not None
        ]

    def delete_ai_record(self, record_type: str, record_id: str) -> bool:
        key = f"canto:ai:{record_type}:{record_id}"
        deleted = bool(self.client.delete(key))
        self.client.srem(f"canto:ai:{record_type}:ids", record_id)
        return deleted

    def set_memory_item(self, memory_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:memory:{memory_id}", json.dumps(value))
        self.client.sadd("canto:memories", memory_id)

    def get_memory_item(self, memory_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:memory:{memory_id}")
        return json.loads(value) if value else None

    def list_memory_items(self) -> list[dict[str, Any]]:
        return [value for memory_id in sorted(self.client.smembers("canto:memories")) if (value := self.get_memory_item(memory_id))]

    def search_memory_items(self, query: str) -> list[dict[str, Any]]:
        terms = [term for term in re.findall(r"[a-z0-9_@.-]+", query.casefold()) if len(term) > 1]
        return [
            value for value in self.list_memory_items()
            if not terms or any(term in json.dumps(value, sort_keys=True).casefold() for term in terms)
        ]

    def transition_memory_item(self, memory_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool:
        key = f"canto:memory:{memory_id}"
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
                    pipe.sadd("canto:memories", memory_id)
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def delete_memory_item(self, memory_id: str) -> bool:
        deleted = bool(self.client.delete(f"canto:memory:{memory_id}"))
        self.client.srem("canto:memories", memory_id)
        self.client.delete(f"canto:memory:{memory_id}:events")
        return deleted

    def append_memory_event(self, memory_id: str, value: dict[str, Any]) -> None:
        self.client.rpush(f"canto:memory:{memory_id}:events", json.dumps(value))
        self.client.rpush("canto:memory:events", json.dumps(value))

    def get_memory_events(self, memory_id: str | None = None) -> list[dict[str, Any]]:
        key = f"canto:memory:{memory_id}:events" if memory_id else "canto:memory:events"
        return [json.loads(value) for value in self.client.lrange(key, 0, -1)]

    def set_memory_project(self, project_id: str, value: dict[str, Any]) -> None:
        self.client.set(f"canto:memory:project:{project_id}", json.dumps(value))
        self.client.sadd("canto:memory:projects", project_id)

    def get_memory_project(self, project_id: str) -> dict[str, Any] | None:
        value = self.client.get(f"canto:memory:project:{project_id}")
        return json.loads(value) if value else None

    def list_memory_projects(self) -> list[dict[str, Any]]:
        return [value for project_id in sorted(self.client.smembers("canto:memory:projects")) if (value := self.get_memory_project(project_id))]

    def transition_memory_approval(
        self, approval_id: str, memory_id: str, approval_expected: set[str],
        memory_expected: set[str], approval_value: dict[str, Any], memory_value: dict[str, Any]
    ) -> bool:
        approval_key = f"canto:approval:{approval_id}"
        memory_key = f"canto:memory:{memory_id}"
        while True:
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(approval_key, memory_key)
                    approval_raw = pipe.get(approval_key)
                    memory_raw = pipe.get(memory_key)
                    if (
                        not approval_raw or json.loads(approval_raw).get("status") not in approval_expected
                        or not memory_raw or json.loads(memory_raw).get("status") not in memory_expected
                    ):
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.set(approval_key, json.dumps(approval_value))
                    pipe.set(memory_key, json.dumps(memory_value))
                    pipe.execute()
                    return True
                except WatchError:
                    continue


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
        self.ai_records: dict[tuple[str, str], dict[str, Any]] = {}
        self.memory_items: dict[str, dict[str, Any]] = {}
        self.memory_events: list[dict[str, Any]] = []
        self.memory_projects: dict[str, dict[str, Any]] = {}
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

    def set_ai_record(
        self, record_type: str, record_id: str, value: dict[str, Any]
    ) -> None:
        with self.lock:
            self.ai_records[(record_type, record_id)] = json.loads(json.dumps(value))

    def get_ai_record(
        self, record_type: str, record_id: str
    ) -> dict[str, Any] | None:
        with self.lock:
            value = self.ai_records.get((record_type, record_id))
            return json.loads(json.dumps(value)) if value else None

    def list_ai_records(self, record_type: str) -> list[dict[str, Any]]:
        with self.lock:
            return [
                json.loads(json.dumps(value))
                for (kind, _), value in sorted(self.ai_records.items())
                if kind == record_type
            ]

    def delete_ai_record(self, record_type: str, record_id: str) -> bool:
        with self.lock:
            return self.ai_records.pop((record_type, record_id), None) is not None

    def set_memory_item(self, memory_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.memory_items[memory_id] = json.loads(json.dumps(value))

    def get_memory_item(self, memory_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.memory_items.get(memory_id)
            return json.loads(json.dumps(value)) if value else None

    def list_memory_items(self) -> list[dict[str, Any]]:
        with self.lock:
            return [json.loads(json.dumps(self.memory_items[key])) for key in sorted(self.memory_items)]

    def search_memory_items(self, query: str) -> list[dict[str, Any]]:
        terms = [term for term in re.findall(r"[a-z0-9_@.-]+", query.casefold()) if len(term) > 1]
        return [
            value for value in self.list_memory_items()
            if not terms or any(term in json.dumps(value, sort_keys=True).casefold() for term in terms)
        ]

    def transition_memory_item(self, memory_id: str, expected_statuses: set[str], value: dict[str, Any]) -> bool:
        with self.lock:
            current = self.memory_items.get(memory_id)
            if not current or current.get("status") not in expected_statuses:
                return False
            self.memory_items[memory_id] = json.loads(json.dumps(value))
            return True

    def delete_memory_item(self, memory_id: str) -> bool:
        with self.lock:
            return self.memory_items.pop(memory_id, None) is not None

    def append_memory_event(self, memory_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.memory_events.append(json.loads(json.dumps(value)))

    def get_memory_events(self, memory_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            values = self.memory_events
            if memory_id:
                values = [value for value in values if value.get("memory_id") == memory_id]
            return json.loads(json.dumps(values))

    def set_memory_project(self, project_id: str, value: dict[str, Any]) -> None:
        with self.lock:
            self.memory_projects[project_id] = json.loads(json.dumps(value))

    def get_memory_project(self, project_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.memory_projects.get(project_id)
            return json.loads(json.dumps(value)) if value else None

    def list_memory_projects(self) -> list[dict[str, Any]]:
        with self.lock:
            return [json.loads(json.dumps(self.memory_projects[key])) for key in sorted(self.memory_projects)]

    def transition_memory_approval(
        self, approval_id: str, memory_id: str, approval_expected: set[str],
        memory_expected: set[str], approval_value: dict[str, Any], memory_value: dict[str, Any]
    ) -> bool:
        with self.lock:
            approval = self.approvals.get(approval_id)
            memory = self.memory_items.get(memory_id)
            if (
                not approval or approval.get("status") not in approval_expected
                or not memory or memory.get("status") not in memory_expected
            ):
                return False
            self.approvals[approval_id] = json.loads(json.dumps(approval_value))
            self.memory_items[memory_id] = json.loads(json.dumps(memory_value))
            return True
