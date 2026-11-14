"""V3 Phase 8: API credentials, external endpoints, webhooks, idempotency."""
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def _admin(client):
    r = client.post("/api/auth/register", json={"email": "admin@test.dev", "name": "Admin", "password": "AdminPass!23"})
    assert r.status_code in (200, 201)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def api_world(client, db):
    ah = _admin(client)
    project = client.post("/api/projects", headers=ah, json={"name": "API Proj"}).json()
    return {"client": client, "ah": ah, "db": db, "project": project}


def _ext_headers(key: str) -> dict:
    return {"X-API-Key": key}


def test_key_lifecycle_and_scope_enforcement(api_world):
    c, ah = api_world["client"], api_world["ah"]
    # create with a narrow scope
    r = c.post("/api/admin/api-keys", headers=ah, json={
        "name": "integration", "scopes": ["projects:read"]})
    assert r.status_code == 201, r.text
    body = r.json()
    key = body["key"]
    assert key.startswith("ef_")
    assert "key_hash" not in json.dumps(body)  # hash never serialized

    eh = _ext_headers(key)
    # allowed: projects list
    r = c.get("/api/ext/v1/projects", headers=eh)
    assert r.status_code == 200
    assert any(p["id"] == api_world["project"]["id"] for p in r.json())
    # denied: a scope the key lacks (403, not 401 — authenticated but unauthorized)
    r = c.post("/api/ext/v1/projects/%s/tasks" % api_world["project"]["id"],
               headers=eh, json={"title": "nope"})
    assert r.status_code == 403

    # invalid key format / value
    assert c.get("/api/ext/v1/projects", headers=_ext_headers("junk")).status_code == 401
    assert c.get("/api/ext/v1/projects", headers=_ext_headers("ef_wrongkeyvalue")).status_code == 401
    assert c.get("/api/ext/v1/projects").status_code == 401

    # activity log records the calls
    r = c.get(f"/api/admin/api-keys/{body['id']}/activity", headers=ah)
    assert r.status_code == 200 and r.json()["total"] >= 2

    # revoke -> immediate 401
    assert c.delete(f"/api/admin/api-keys/{body['id']}", headers=ah).status_code == 200
    assert c.get("/api/ext/v1/projects", headers=eh).status_code == 401


def test_rotate_issues_new_key_and_revokes_old(api_world):
    c, ah = api_world["client"], api_world["ah"]
    k1 = c.post("/api/admin/api-keys", headers=ah,
                json={"name": "rot", "scopes": ["projects:read"]}).json()
    k2 = c.post(f"/api/admin/api-keys/{k1['id']}/rotate", headers=ah).json()
    assert k2["key"] != k1["key"]
    assert c.get("/api/ext/v1/projects", headers=_ext_headers(k1["key"])).status_code == 401
    assert c.get("/api/ext/v1/projects", headers=_ext_headers(k2["key"])).status_code == 200


def test_external_dataset_ingestion_and_records(api_world):
    c, ah = api_world["client"], api_world["ah"]
    k = c.post("/api/admin/api-keys", headers=ah,
               json={"name": "ingest", "scopes": ["datasets:read", "datasets:write"]}).json()
    eh = _ext_headers(k["key"])
    pid = api_world["project"]["id"]
    r = c.post("/api/ext/v1/datasets", headers=eh, json={"project_id": pid, "name": "API DS"})
    assert r.status_code == 201, r.text
    ds_id = r.json()["id"]
    r = c.post(f"/api/ext/v1/datasets/{ds_id}/records", headers=eh, json={
        "records": [
            {"record_id": "a1", "prompt": "p1", "response": "r1"},
            {"record_id": "a2", "prompt": "p2", "response": "r2"},
        ]})
    assert r.status_code == 201, r.text
    assert r.json()["report"]["valid_count"] == 2
    # visible to staff through the regular surface (org-scoped)
    r = c.get("/api/datasets", headers=ah)
    assert any(d["id"] == ds_id for d in r.json())
    # read scope works
    r = c.get(f"/api/ext/v1/datasets/{ds_id}", headers=eh)
    assert r.status_code == 200 and r.json()["record_count"] == 2


def test_idempotency_replay(api_world):
    c, ah = api_world["client"], api_world["ah"]
    k = c.post("/api/admin/api-keys", headers=ah,
               json={"name": "idem", "scopes": ["tasks:write", "tasks:read"]}).json()
    eh = {**_ext_headers(k["key"]), "Idempotency-Key": "create-42"}
    pid = api_world["project"]["id"]
    r1 = c.post(f"/api/ext/v1/projects/{pid}/tasks", headers=eh,
                json={"title": "Idempotent task"})
    assert r1.status_code == 201
    task_id = r1.json()["id"]
    # same key + same body -> same response, no second task
    r2 = c.post(f"/api/ext/v1/projects/{pid}/tasks", headers=eh,
                json={"title": "Idempotent task"})
    assert r2.status_code == 201 and r2.json()["id"] == task_id
    # same key, different body -> 422
    r3 = c.post(f"/api/ext/v1/projects/{pid}/tasks", headers=eh,
                json={"title": "Different task"})
    assert r3.status_code == 422
    # without the key -> a new task
    r4 = c.post(f"/api/ext/v1/projects/{pid}/tasks",
                headers=_ext_headers(k["key"]), json={"title": "Idempotent task"})
    assert r4.status_code == 201 and r4.json()["id"] != task_id


def test_rate_limit_returns_429(api_world, db):
    from app.core import api_auth
    c, ah = api_world["client"], api_world["ah"]
    k = c.post("/api/admin/api-keys", headers=ah,
               json={"name": "ratelimited", "scopes": ["projects:read"]}).json()
    eh = _ext_headers(k["key"])
    # drain the bucket directly (fast and deterministic)
    api_auth._buckets[k["id"]] = {"tokens": 0.5, "ts": time.monotonic()}
    r = c.get("/api/ext/v1/projects", headers=eh)
    assert r.status_code == 429
    api_auth._buckets.pop(k["id"], None)


# ---------------------------------------------------------------------------
# Webhooks: signing, SSRF, delivery + retries via a local HTTP receiver
# ---------------------------------------------------------------------------

class _Receiver(BaseHTTPRequestHandler):
    received: list = []
    fail_next = 0

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _Receiver.received.append({
            "body": json.loads(body),
            "signature": self.headers.get("X-EvalForge-Signature"),
            "event": self.headers.get("X-EvalForge-Event"),
        })
        if _Receiver.fail_next > 0:
            _Receiver.fail_next -= 1
            self.send_response(500)
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def receiver():
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def test_webhook_delivery_signature_and_events(api_world, receiver, db):
    c, ah = api_world["client"], api_world["ah"]
    url = f"http://127.0.0.1:{receiver.server_address[1]}/hook"
    # loopback URLs are blocked by the SSRF guard — allow this test receiver by
    # creating the endpoint through the service (validation bypassed intentionally)
    from app.models.api_integration import WebhookEndpoint
    from app.services.webhooks import generate_secret, dispatch_event, deliver_due
    secret = generate_secret()
    ep = WebhookEndpoint(url=url, secret=secret, events=["submission.approved", "review.completed"])
    db.add(ep)
    db.commit()
    db.refresh(ep)
    n = dispatch_event(db, "submission.approved", {"submission_id": 999})
    assert n == 1
    processed = deliver_due(db, allow_private=True)
    assert processed == 1
    assert _Receiver.received, "receiver got nothing"
    last = _Receiver.received[-1]
    assert last["event"] == "submission.approved"
    assert last["body"]["data"]["submission_id"] == 999
    # signature verifies: HMAC_SHA256(secret, "t.body")
    sig = dict(pair.split("=", 1) for pair in last["signature"].split(","))
    ts, v1 = sig["t"], sig["v1"]
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + json.dumps(
        last["body"], default=str).encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(v1, expected)


def test_webhook_ssrf_guard():
    from app.services.webhooks import validate_webhook_url, SSRFError
    for url in ("http://localhost/hook", "http://127.0.0.1/x", "http://10.0.0.5/x",
                "http://169.254.169.254/latest/meta-data", "ftp://example.com",
                "http://192.168.1.1/router"):
        try:
            validate_webhook_url(url)
            raise AssertionError(f"{url} should have been blocked")
        except SSRFError:
            pass


def test_webhook_endpoint_crud_blocks_private_urls(api_world):
    c, ah = api_world["client"], api_world["ah"]
    r = c.post("/api/admin/webhooks", headers=ah, json={
        "url": "http://localhost:9000/hook", "events": ["project.created"]})
    assert r.status_code == 422  # SSRF guard blocks loopback at the API layer
    r = c.post("/api/admin/webhooks", headers=ah, json={
        "url": "https://hooks.example.com/evalforge", "events": ["project.created", "bogus.event"]})
    assert r.status_code == 422  # unknown event
