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
                policy=Policy(allow_network=True, approved_domains=["127.0.0.1"]),
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


def test_crawler_refuses_cross_host_redirect(runtime):
    requests_to_redirect_target = 0

    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal requests_to_redirect_target
            if self.path == "/target":
                requests_to_redirect_target += 1
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><title>Unexpected</title></html>")
                return
            self.send_response(302)
            self.send_header(
                "location",
                f"http://localhost:{self.server.server_port}/target",
            )
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, _, store, service = runtime
        job = service.create_job(
            JobRequest(
                skill="source_inventory",
                provider="public_html_crawler",
                inputs={"source_url": f"http://127.0.0.1:{server.server_port}/"},
                policy=Policy(allow_network=True, approved_domains=["127.0.0.1"]),
            )
        )
        completed = service.process_job(job.job_id)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert completed.status == "completed"
    inventory_meta = next(
        item for item in store.get_artifacts(job.job_id) if item["name"] == "inventory_json"
    )
    inventory = json.loads(read_artifact(inventory_meta)["content"])
    assert inventory["pages"] == []
    assert requests_to_redirect_target == 0
    assert "Refused redirect outside source domain" in inventory["warnings"][0]
