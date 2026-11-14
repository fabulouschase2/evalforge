"""Authentication, authorization and role-based access tests."""
from tests.conftest import _register


def test_register_login_me_flow(client, db):
    data = _register(client, "a@test.dev", "Alice", "Password!23")
    assert data["user"]["role"] == "super_admin"  # first user bootstraps as super admin
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "a@test.dev"

    # second user is a worker (tester)
    data2 = _register(client, "b@test.dev", "Bob", "Password!23")
    assert data2["user"]["role"] == "tester"


def test_register_rejects_duplicate_email(client, db):
    _register(client, "a@test.dev", "Alice", "Password!23")
    r = client.post("/api/auth/register", json={"email": "a@test.dev", "name": "Again", "password": "Password!23"})
    assert r.status_code == 409


def test_register_rejects_short_password(client, db):
    r = client.post("/api/auth/register", json={"email": "s@test.dev", "name": "S", "password": "short"})
    assert r.status_code == 422


def test_login_rejects_wrong_password(client, db):
    _register(client, "a@test.dev", "Alice", "Password!23")
    r = client.post("/api/auth/login", json={"email": "a@test.dev", "password": "WrongPass!23"})
    assert r.status_code == 401


def test_me_requires_token(client, db):
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_token_rejected(client, db):
    _register(client, "a@test.dev", "Alice", "Password!23")
    headers = {"Authorization": "Bearer not.a.realtoken"}
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_roles_endpoints(client, db, reviewer_headers):
    """Reviewer role must be denied privileged operations."""
    rev_headers, _ = reviewer_headers
    assert client.post("/api/datasets", headers=rev_headers, json={"name": "x"}).status_code == 403
    assert client.post("/api/rubrics", headers=rev_headers, json={"name": "x", "definition": {}}).status_code == 403
    assert client.get("/api/audit-logs", headers=rev_headers).status_code == 403
    assert client.put("/api/settings", headers=rev_headers, json={"max_upload_mb": 1}).status_code == 403
    # reviewers CAN read datasets/rubrics and see their review queue
    assert client.get("/api/datasets", headers=rev_headers).status_code == 200
    assert client.get("/api/reviews/queue", headers=rev_headers).status_code == 200
