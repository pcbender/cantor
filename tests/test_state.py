from __future__ import annotations

import fakeredis
import pytest

from canto.core.state import MemoryStateStore, RedisStateStore


@pytest.fixture(params=["memory", "redis"])
def store(request):
    if request.param == "memory":
        return MemoryStateStore()
    state = RedisStateStore("redis://unused")
    state.client = fakeredis.FakeRedis(decode_responses=True)
    return state


def test_transition_job_requires_expected_status(store):
    queued = {"job_id": "job_1", "status": "queued"}
    running = {"job_id": "job_1", "status": "running"}
    store.set_job("job_1", queued)

    assert store.transition_job("job_1", {"queued"}, running) is True
    assert store.transition_job("job_1", {"queued"}, queued) is False
    assert store.get_job("job_1") == running
