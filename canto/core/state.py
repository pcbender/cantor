from __future__ import annotations

import json
from collections import defaultdict
from threading import RLock
from typing import Any, Protocol

import redis


class StateStore(Protocol):
    def ping(self) -> bool: ...
    def set_job(self, job_id: str, value: dict[str, Any]) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def append_event(self, job_id: str, value: dict[str, Any]) -> None: ...
    def get_events(self, job_id: str) -> list[dict[str, Any]]: ...
    def set_artifacts(self, job_id: str, value: list[dict[str, Any]]) -> None: ...
    def get_artifacts(self, job_id: str) -> list[dict[str, Any]]: ...
    def set_approval(self, approval_id: str, value: dict[str, Any]) -> None: ...
    def get_approval(self, approval_id: str) -> dict[str, Any] | None: ...
    def set_registry(self, value: dict[str, Any]) -> None: ...


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

    def set_registry(self, value: dict[str, Any]) -> None:
        self.client.set("canto:registry:snapshot", json.dumps(value))


class MemoryStateStore:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.artifacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.registry: dict[str, Any] = {}
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

    def set_registry(self, value: dict[str, Any]) -> None:
        with self.lock:
            self.registry = json.loads(json.dumps(value))
