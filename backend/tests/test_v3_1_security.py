"""V3.1 security audit regression tests.

Each test maps to a finding in docs/V3_1_AUDIT_REPORT.md — a fix without a
reproducing test is considered not done.
"""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _h(client, email, password="TestPass!23"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def sec_world(client, db):
    """Admin + second admin's project + tester + client owner in an org."""
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    org = client.post("/api/organizations", headers=ah, json={"name": "Sec Org"}).json()
    tester = _register(client, "worker.s@test.dev", "Worker S")
    client.post(f"/api/organizations/{org['id']}/members", headers=ah,
                json={"email": "worker.s@test.dev", "role": "client_owner"})
    th = _h(client, "worker.s@test.dev")
    ch = th  # client_owner role after member add upgrades the bare tester
    # a project belonging to the org, with dataset + rubric + run
    project = client.post("/api/projects", headers=ah,
                          json={"name": "Sec Proj", "organization_id": org["id"]}).json()
    records = [{"record_id": "s1", "prompt": "p", "response": "r", "reference_answer": "ref",
                "expected_label": "pass"}]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    ds = client.post("/api/datasets", headers=ah, json={"name": "Sec DS", "project_id": project["id"]}).json()
    client.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah, files=files)
    from tests.conftest import DEMO_RUBRIC
    rub = client.post("/api/rubrics", headers=ah,
                      json={"name": "Sec Rubric", "definition": DEMO_RUBRIC, "project_id": project["id"]}).json()
    run = client.post("/api/evaluations", headers=ah,
                      json={"name": "Sec Run", "dataset_id": ds["id"], "rubric_id": rub["id"]}).json()
    client.post(f"/api/evaluations/{run['id']}/run", headers=ah)
    return {"client": client, "ah": ah, "th": th, "ch": ch, "org": org,
            "project": project, "ds": ds, "rub": rub, "run": run}


# --- F1: user directory enumeration ----------------------------------------

def test_user_directory_staff_only(sec_world):
    c, th, ah = sec_world["client"], sec_world["th"], sec_world["ah"]
    assert c.get("/api/auth/users", headers=th).status_code == 403
    assert c.get("/api/auth/users", headers=ah).status_code == 200


# --- F2: evaluation run visibility -------------------------------------------

def test_evaluation_runs_hidden_from_non_members(sec_world):
    """A user with no project membership sees no runs and cannot fetch by id."""
    c = sec_world["client"]
    outsider = _register(c, "outsider.s@test.dev", "Outsider")
    oh = {"Authorization": f"Bearer {outsider['access_token']}"}
    r = c.get("/api/evaluations", headers=oh)
    assert r.status_code == 200 and r.json() == []
    assert c.get(f"/api/evaluations/{sec_world['run']['id']}", headers=oh).status_code == 404
    assert c.get(f"/api/evaluations/{sec_world['run']['id']}/results", headers=oh).status_code == 404
    assert c.get(f"/api/evaluations/{sec_world['run']['id']}/findings", headers=oh).status_code == 404


def test_evaluation_run_visible_to_project_staff(sec_world):
    c, ah = sec_world["client"], sec_world["ah"]
    r = c.get(f"/api/evaluations/{sec_world['run']['id']}", headers=ah)
    assert r.status_code == 200 and r.json()["id"] == sec_world["run"]["id"]


def test_run_creation_requires_project_admin(sec_world):
    """A staff member who does not administer the project cannot create runs."""
    c = sec_world["client"]
    _register(c, "pm.s@test.dev", "PM S")
    pmh = _h(c, "pm.s@test.dev")
    # promote to project_manager platform role (staff) but NOT a project member
    ah = sec_world["ah"]
    users = ah  # admin changes role below
    uid = c.get("/api/auth/users", headers=ah).json()
    pm_id = [u for u in uid if u["email"] == "pm.s@test.dev"][0]["id"]
    c.put(f"/api/auth/users/{pm_id}/role", headers=ah, json={"role": "project_manager"})
    r = c.post("/api/evaluations", headers=pmh,
               json={"name": "Hijack Run", "dataset_id": sec_world["ds"]["id"],
                     "rubric_id": sec_world["rub"]["id"]})
    assert r.status_code == 403


# --- F3: rubric visibility + write protection --------------------------------

def test_rubrics_hidden_from_non_members(sec_world):
    c = sec_world["client"]
    outsider = _register(c, "o2.s@test.dev", "Outsider 2")
    oh = {"Authorization": f"Bearer {outsider['access_token']}"}
    assert c.get("/api/rubrics", headers=oh).json() == []
    assert c.get(f"/api/rubrics/{sec_world['rub']['id']}", headers=oh).status_code == 404
    assert c.get(f"/api/rubrics/{sec_world['rub']['id']}/versions", headers=oh).status_code == 404


def test_rubric_update_requires_project_admin(sec_world):
    c = sec_world["client"]
    _register(c, "pm2.s@test.dev", "PM 2")
    pmh = _h(c, "pm2.s@test.dev")
    ah = sec_world["ah"]
    uid = c.get("/api/auth/users", headers=ah).json()
    pm_id = [u for u in uid if u["email"] == "pm2.s@test.dev"][0]["id"]
    c.put(f"/api/auth/users/{pm_id}/role", headers=ah, json={"role": "project_manager"})
    r = c.put(f"/api/rubrics/{sec_world['rub']['id']}", headers=pmh, json={"name": "Hijacked"})
    # fail-closed: non-admins are refused (403 without visibility, 404 without it)
    assert r.status_code in (403, 404)
    # the legitimate admin can still update
    r = c.put(f"/api/rubrics/{sec_world['rub']['id']}", headers=sec_world["ah"], json={"name": "Sec Rubric v2"})
    assert r.status_code == 200


# --- F4: analytics access ------------------------------------------------------

def test_global_analytics_staff_only(sec_world):
    c, th = sec_world["client"], sec_world["th"]
    for path in ("/api/analytics/overview", "/api/analytics/metrics",
                 "/api/analytics/agreement", "/api/analytics/confusion-matrix"):
        assert c.get(path, headers=th).status_code == 403, path


def test_run_scoped_metrics_allowed_for_project_staff(sec_world):
    c, ah = sec_world["client"], sec_world["ah"]
    r = c.get(f"/api/analytics/metrics?run_id={sec_world['run']['id']}", headers=ah)
    assert r.status_code == 200


# --- F5: audit logs restricted to administrators -------------------------------

def test_audit_logs_administrator_only(client, db):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    # promote a project_manager -> must be denied
    _register(client, "pm.a@test.dev", "PM A")
    uid = client.get("/api/auth/users", headers=ah).json()
    pm_id = [u for u in uid if u["email"] == "pm.a@test.dev"][0]["id"]
    client.put(f"/api/auth/users/{pm_id}/role", headers=ah, json={"role": "project_manager"})
    pmh = _h(client, "pm.a@test.dev")
    assert client.get("/api/audit-logs", headers=pmh).status_code == 403
    assert client.get("/api/audit-logs", headers=ah).status_code == 200


# --- F6: reviewer assignment + adjudication cross-project protection ----------

def test_review_assignment_requires_project_admin(sec_world):
    c = sec_world["client"]
    _register(c, "pm3.s@test.dev", "PM 3")
    pmh = _h(c, "pm3.s@test.dev")
    ah = sec_world["ah"]
    uid = c.get("/api/auth/users", headers=ah).json()
    pm_id = [u for u in uid if u["email"] == "pm3.s@test.dev"][0]["id"]
    c.put(f"/api/auth/users/{pm_id}/role", headers=ah, json={"role": "project_manager"})
    results = c.get(f"/api/evaluations/{sec_world['run']['id']}/results", headers=ah).json()["items"]
    assert results
    r = c.post("/api/reviews/assign", headers=pmh,
               json={"reviewer_ids": [1], "result_ids": [results[0]["id"]]})
    assert r.status_code == 403


def test_adjudication_requires_project_admin(sec_world):
    c = sec_world["client"]
    _register(c, "pm4.s@test.dev", "PM 4")
    pmh = _h(c, "pm4.s@test.dev")
    ah = sec_world["ah"]
    uid = c.get("/api/auth/users", headers=ah).json()
    pm_id = [u for u in uid if u["email"] == "pm4.s@test.dev"][0]["id"]
    c.put(f"/api/auth/users/{pm_id}/role", headers=ah, json={"role": "project_manager"})
    results = c.get(f"/api/evaluations/{sec_world['run']['id']}/results", headers=ah).json()["items"]
    r = c.post(f"/api/reviews/results/{results[0]['id']}/adjudicate", headers=pmh,
               json={"final_label": "pass", "rationale": "x"})
    assert r.status_code == 403


# --- F7: projectless datasets are staff-only -----------------------------------

def test_projectless_dataset_staff_only(client, db):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    ds = client.post("/api/datasets", headers=ah, json={"name": "Projectless"}).json()
    tester = _register(client, "w.p@test.dev", "W P")
    th = {"Authorization": f"Bearer {tester['access_token']}"}
    assert client.get(f"/api/datasets/{ds['id']}", headers=th).status_code == 403
    assert client.get(f"/api/datasets/{ds['id']}/records", headers=th).status_code == 403


# --- F8: webhook SSRF hardening -------------------------------------------------

def test_webhook_url_with_embedded_credentials_blocked(client, db):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/admin/webhooks", headers=ah,
                    json={"url": "https://user:secret@example.com/hook", "events": ["project.created"]})
    assert r.status_code == 422


def test_webhook_redirects_not_followed(client, db):
    """A 302 from the receiver must NOT be followed to a private address."""
    from app.models.api_integration import WebhookDelivery, WebhookEndpoint
    from app.services.webhooks import generate_secret, dispatch_event, deliver_due

    hits = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        def log_message(self, *args): pass

    server = HTTPServer(("127.0.0.1", 0), RedirectHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ep = WebhookEndpoint(url=f"http://127.0.0.1:{server.server_address[1]}/hook",
                         secret=generate_secret(), events=["project.created"])
    db.add(ep)
    db.commit()
    db.refresh(ep)
    dispatch_event(db, "project.created", {"n": 1})
    deliver_due(db, allow_private=True)
    server.shutdown()
    # the delivery reached the receiver but the redirect was NOT followed
    assert hits == ["/hook"]
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == ep.id).first()
    assert delivery.response_code == 302


def test_webhook_dns_rebind_blocked_at_delivery(client, db, monkeypatch):
    """A host that resolves to a private address at delivery time is blocked."""
    import socket as _socket
    from app.models.api_integration import WebhookDelivery, WebhookEndpoint
    from app.services import webhooks as wh

    ep = WebhookEndpoint(url="https://rebind.example/hook", secret=wh.generate_secret(),
                         events=["project.created"])
    db.add(ep)
    db.commit()
    db.refresh(ep)
    delivery = WebhookDelivery(endpoint_id=ep.id, event_type="project.created",
                               payload={"event": "project.created", "data": {}},
                               status="pending",
                               next_retry_at=datetime.now(timezone.utc))
    db.add(delivery)
    db.commit()

    real_getaddrinfo = _socket.getaddrinfo
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host == "rebind.example":
            return [(2, 1, 6, "", ("10.0.0.5", port))]
        return real_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(wh.socket, "getaddrinfo", fake_getaddrinfo)

    processed = wh.deliver_due(db)
    assert processed == 1
    db.refresh(delivery)
    assert delivery.status == "failed"
    assert "10.0.0.5" in (delivery.error or "")


# --- F9: production SECRET_KEY validation ----------------------------------------

def test_production_secret_key_validation():
    from app.core.config import Settings
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        Settings(environment="production", secret_key="change-me-in-production")
    with pytest.raises(pydantic.ValidationError):
        Settings(environment="production", secret_key="short")
    ok = Settings(environment="production",
                  secret_key="x" * 48, enable_demo=False)
    assert ok.environment == "production"


def test_production_requires_explicit_demo_opt_in(client, monkeypatch):
    from app.core.config import settings as app_settings
    from app.core.security import hash_password
    from app.models.user import User
    monkeypatch.setattr(app_settings, "environment", "production")
    monkeypatch.setattr(app_settings, "enable_demo", False)
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/demo/load", headers=ah)
    assert r.status_code == 403
    # explicitly opted in -> allowed
    monkeypatch.setattr(app_settings, "enable_demo", True)
    r = client.post("/api/demo/load", headers=ah)
    assert r.status_code == 200


# --- F10: invitation single-use guard (atomic pending->accepted transition) ------

def test_invitation_single_use_across_sessions(client, db):
    """Two independent sessions cannot both accept the same invitation.

    (True parallel races are serialized by SQLite in dev; the atomic
    pending->accepted UPDATE is the guard that makes acceptance single-use
    under PostgreSQL row-level concurrency as well.)
    """
    from sqlalchemy import select as _select

    from app.models.user import User as _User
    from app.services.org_access import accept_invitation

    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    org = client.post("/api/organizations", headers=ah, json={"name": "Race Org"}).json()
    token = client.post(f"/api/organizations/{org['id']}/invitations", headers=ah,
                        json={"email": "racer@test.dev", "role": "client_viewer"}).json()["token"]
    _register(client, "racer@test.dev", "Racer")

    from tests.conftest import _SessionLocal
    s1, s2 = _SessionLocal(), _SessionLocal()
    try:
        u1 = s1.scalar(_select(_User).where(_User.email == "racer@test.dev"))
        u2 = s2.scalar(_select(_User).where(_User.email == "racer@test.dev"))
        accept_invitation(s1, raw_token=token, user=u1)
        with pytest.raises(PermissionError):
            accept_invitation(s2, raw_token=token, user=u2)
    finally:
        s1.close()
        s2.close()
    user_row = db.scalar(_select(_User).where(_User.email == "racer@test.dev"))
    assert user_row.role == "client_viewer"


# --- F11: idempotent writes - replay, conflict rejection, single effect ----------

def test_idempotency_replay_and_conflicting_reuse(client, db):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    project = client.post("/api/projects", headers=ah, json={"name": "Idem Proj"}).json()
    k = client.post("/api/admin/api-keys", headers=ah,
                    json={"name": "idem-race", "scopes": ["tasks:write", "tasks:read"]}).json()
    key = k["key"]
    headers = {"X-API-Key": key, "Idempotency-Key": "race-1"}

    r1 = client.post(f"/api/ext/v1/projects/{project['id']}/tasks", headers=headers,
                     json={"title": "Raced task"})
    assert r1.status_code == 201
    task_id = r1.json()["id"]
    # same key + same body -> replay, no second task
    r2 = client.post(f"/api/ext/v1/projects/{project['id']}/tasks", headers=headers,
                     json={"title": "Raced task"})
    assert r2.status_code == 201 and r2.json()["id"] == task_id
    # same key + different body -> rejected
    r3 = client.post(f"/api/ext/v1/projects/{project['id']}/tasks", headers=headers,
                     json={"title": "Different"})
    assert r3.status_code == 422
    tasks = client.get(f"/api/ext/v1/projects/{project['id']}/tasks",
                       headers={"X-API-Key": key}).json()
    assert tasks["total"] == 1
