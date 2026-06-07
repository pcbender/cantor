from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

from canto.core.artifacts import read_artifact
from canto.models.schemas import JobRequest, Policy


def test_crawler_runs_and_artifacts_are_readable(runtime, tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        '<html><head><title>Home</title><meta name="description" content="Test site"></head>'
        '<body><h1>Welcome</h1><a href="/about.html">About</a><img src="/logo.png"></body></html>',
        encoding="utf-8",
    )
    (site / "about.html").write_text(
        '<html><head><title>About us</title></head><body><h1>About</h1></body></html>',
        encoding="utf-8",
    )
    (site / "logo.png").write_bytes(b"not-a-real-png")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, _, store, service = runtime
        source_url = f"http://127.0.0.1:{server.server_port}/"
        job = service.create_job(
            JobRequest(
                skill="source_inventory",
                provider="public_html_crawler",
                inputs={"source_url": source_url, "max_depth": 2},
                policy=Policy(allow_network=True),
            )
        )
        completed = service.process_job(job.job_id)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.status == "completed", completed.error
    artifacts = store.get_artifacts(job.job_id)
    inventory_meta = next(item for item in artifacts if item["name"] == "inventory_json")
    inventory = json.loads(read_artifact(inventory_meta)["content"])
    assert len(inventory["pages"]) == 2
    assert inventory["pages"][0]["title"] == "Home"
    assert len(inventory["media"]) == 1

