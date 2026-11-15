"""Rate limiting on authentication endpoints."""
from app.core.config import settings as app_settings
from tests.conftest import _register


def test_login_rate_limited_after_burst(client, db):
    limit = app_settings.login_rate_limit
    # register one account (inside the 10/5min register budget)
    _register(client, "rl@test.dev", "RL", "Password!23")
    # failed logins fill the login bucket (limit: login_rate_limit per 5 min per IP)
    for _ in range(limit):
        r = client.post("/api/auth/login", json={"email": "rl@test.dev", "password": "WrongPass!23"})
        assert r.status_code == 401
    # the next attempt is rate limited regardless of correctness
    r = client.post("/api/auth/login", json={"email": "rl@test.dev", "password": "Password!23"})
    assert r.status_code == 429


def test_register_rate_limited_after_burst(client, db):
    for i in range(10):
        r = client.post("/api/auth/register", json={
            "email": f"burst{i}@test.dev", "name": f"B{i}", "password": "Password!23"})
        assert r.status_code == 201
    r = client.post("/api/auth/register", json={
        "email": "burst11@test.dev", "name": "B11", "password": "Password!23"})
    assert r.status_code == 429
