"""V3 Phase 9: unified platform analytics + exports."""
import pytest


def test_platform_analytics_counts_are_real(client, db):
    r = client.post("/api/auth/register", json={"email": "admin@test.dev", "name": "Admin", "password": "AdminPass!23"})
    ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # empty platform: rates are None, never fabricated
    r = client.get("/api/analytics/platform", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["projects"]["total"] == 0
    assert body["tasks"]["completion_rate"] is None
    assert body["submissions"]["approval_rate"] is None
    assert body["quality"]["golden_accuracy"] is None
    assert "never fabricated" in body["computed_from"]

    # create one project + tester -> counts move
    client.post("/api/projects", headers=ah, json={"name": "P1"})
    client.post("/api/auth/register", json={"email": "w@test.dev", "name": "W", "password": "TestPass!23"})
    r = client.get("/api/analytics/platform", headers=ah)
    body = r.json()
    assert body["projects"]["total"] == 1 and body["projects"]["active"] == 1
    assert body["people"]["workers"] >= 1


def test_platform_analytics_staff_only(client, db):
    client.post("/api/auth/register", json={"email": "admin@test.dev", "name": "Admin", "password": "AdminPass!23"})
    tester = client.post("/api/auth/register", json={"email": "t@test.dev", "name": "T", "password": "TestPass!23"})
    th = {"Authorization": f"Bearer {tester.json()['access_token']}"}
    assert client.get("/api/analytics/platform", headers=th).status_code == 403


def test_quality_export_csv_and_json(client, db):
    client.post("/api/auth/register", json={"email": "admin@test.dev", "name": "Admin", "password": "AdminPass!23"})
    ah = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "admin@test.dev", "password": "AdminPass!23"}).json()["access_token"]}
    r = client.get("/api/analytics/export?kind=quality&format=csv", headers=ah)
    assert r.status_code == 200
    assert b"worker_id" in r.content and b"golden_accuracy" in r.content
    r = client.get("/api/analytics/export?kind=quality&format=json", headers=ah)
    assert r.status_code == 200 and r.json() == []
    # platform export
    r = client.get("/api/analytics/export?kind=platform&format=json", headers=ah)
    assert r.status_code == 200 and "projects" in r.json()
    # audit trail records the export
    r = client.get("/api/audit-logs?action=analytics.export", headers=ah)
    assert r.json()["total"] >= 2
