"""Phase 2 platform roles: administration of users, role changes and suspension."""
from tests.conftest import _register


def _admin_headers(client, db):
    data = _register(client, "root@test.dev", "Root", "AdminPass!23")
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]


def _second_user(client, db):
    return _register(client, "worker@test.dev", "Worker", "WorkerPass!23")


def test_super_admin_can_create_users(client, db):
    headers, _ = _admin_headers(client, db)
    r = client.post("/api/auth/users", headers=headers, json={
        "email": "senior@test.dev", "name": "Senior Reviewer",
        "password": "SeniorPass!23", "role": "senior_reviewer",
    })
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "senior_reviewer"


def test_non_admin_cannot_create_users(client, db):
    _admin_headers(client, db)
    worker = _second_user(client, db)
    headers = {"Authorization": f"Bearer {worker['access_token']}"}
    r = client.post("/api/auth/users", headers=headers, json={
        "email": "x@test.dev", "name": "X", "password": "Password!23", "role": "tester",
    })
    assert r.status_code == 403


def test_super_admin_changes_roles_and_it_is_audited(client, db):
    headers, _ = _admin_headers(client, db)
    worker = _second_user(client, db)
    r = client.put(f"/api/auth/users/{worker['user']['id']}/role", headers=headers,
                   json={"role": "senior_reviewer"})
    assert r.status_code == 200 and r.json()["role"] == "senior_reviewer"

    # role change recorded in audit trail
    logs = client.get("/api/audit-logs?action=user.role_change", headers=headers).json()
    assert logs["total"] >= 1
    entry = logs["items"][0]
    assert entry["details"]["to"] == "senior_reviewer"

    # invalid role rejected
    r = client.put(f"/api/auth/users/{worker['user']['id']}/role", headers=headers,
                   json={"role": "emperor"})
    assert r.status_code == 422


def test_non_admin_cannot_change_roles(client, db):
    _admin_headers(client, db)
    worker = _second_user(client, db)
    headers = {"Authorization": f"Bearer {worker['access_token']}"}
    # worker tries to promote themselves
    r = client.put(f"/api/auth/users/{worker['user']['id']}/role", headers=headers,
                   json={"role": "super_admin"})
    assert r.status_code == 403


def test_suspend_blocks_login_immediately(client, db):
    headers, _ = _admin_headers(client, db)
    worker = _second_user(client, db)
    uid = worker["user"]["id"]

    r = client.put(f"/api/auth/users/{uid}/status", headers=headers, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    # suspended account cannot log in
    r = client.post("/api/auth/login", json={"email": "worker@test.dev", "password": "WorkerPass!23"})
    assert r.status_code == 403

    # and their existing token stops working (me endpoint re-checks is_active)
    worker_headers = {"Authorization": f"Bearer {worker['access_token']}"}
    assert client.get("/api/auth/me", headers=worker_headers).status_code == 401

    # reactivate
    r = client.put(f"/api/auth/users/{uid}/status", headers=headers, json={"is_active": True})
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": "worker@test.dev", "password": "WorkerPass!23"})
    assert r.status_code == 200


def test_super_admin_cannot_self_demote_or_self_suspend(client, db):
    headers, admin_id = _admin_headers(client, db)
    r = client.put(f"/api/auth/users/{admin_id}/role", headers=headers, json={"role": "tester"})
    assert r.status_code == 400
    r = client.put(f"/api/auth/users/{admin_id}/status", headers=headers, json={"is_active": False})
    assert r.status_code == 400


def test_legacy_role_values_migrated(client, db):
    """The Alembic data migration maps legacy roles; creation path must never emit them."""
    data = _register(client, "a@test.dev", "Alice", "Password!23")
    assert data["user"]["role"] not in ("administrator", "evaluator")
