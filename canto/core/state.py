from __future__ import annotations

import json
from collections import defaultdict
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
