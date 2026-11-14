"""Phase 3: project management, membership and project-level isolation."""
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.project import ProjectMember
from app.models.user import User
from tests.conftest import _register


def _setup(client, db):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    # worker users with distinct platform roles
    tester_user = User(email="t1@test.dev", name="Tester One", hashed_password=hash_password("TestPass!23"), role="tester")
    tester2 = User(email="t2@test.dev", name="Tester Two", hashed_password=hash_password("TestPass!23"), role="tester")
    reviewer = User(email="r1@test.dev", name="Reviewer One", hashed_password=hash_password("TestPass!23"), role="reviewer")
    pm = User(email="pm@test.dev", name="PM", hashed_password=hash_password("TestPass!23"), role="project_manager")
    db.add_all([tester_user, tester2, reviewer, pm])
    db.commit()
    return admin, ah, tester_user, tester2, reviewer, pm


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_project(client, ah, name="Isolation Project"):
    r = client.post("/api/projects", headers=ah, json={"name": name, "project_type": "data_annotation"})
    assert r.status_code == 201, r.text
    return r.json()


def test_project_create_with_full_configuration(client, db):
    admin, ah, *_ = _setup(client, db)
    r = client.post("/api/organizations", headers=ah, json={"name": "Acme AI", "description": "Client org"})
    assert r.status_code == 201
    org_id = r.json()["id"]

    r = client.post("/api/projects", headers=ah, json={
        "name": "Safety Eval Q1",
        "description": "Evaluate safety behaviors",
        "organization_id": org_id,
        "client": "Acme AI",
        "project_type": "safety_evaluation",
        "instructions": "Follow the safety rubric carefully.",
        "required_skills": ["safety taxonomy"],
        "supported_languages": ["en", "de"],
        "start_date": "2026-11-01T00:00:00Z",
        "deadline": "2026-12-31T00:00:00Z",
        "quality_requirements": "95% approval required",
        "target_task_volume": 500,
        "blind_review": False,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project_type"] == "safety_evaluation"
    assert body["organization_name"] == "Acme AI"
    assert body["blind_review"] is False
    assert body["target_task_volume"] == 500
    assert body["is_admin"] is True

    # unknown type rejected
    r = client.post("/api/projects", headers=ah, json={"name": "x", "project_type": "palm_reading"})
    assert r.status_code == 422


def test_membership_and_visibility_isolation(client, db):
    admin, ah, tester1, tester2, reviewer, pm = _setup(client, db)
    p1 = _make_project(client, ah, "Project One")
    p2 = _make_project(client, ah, "Project Two")

    # add tester1 + reviewer to project one only
    r = client.post(f"/api/projects/{p1['id']}/members", headers=ah,
                    json={"user_id": tester1.id, "role": "tester"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/projects/{p1['id']}/members", headers=ah,
                    json={"user_id": reviewer.id, "role": "reviewer"})
    assert r.status_code == 201

    # duplicate membership rejected
    r = client.post(f"/api/projects/{p1['id']}/members", headers=ah,
                    json={"user_id": tester1.id, "role": "tester"})
    assert r.status_code == 409

    # tester1 sees project one, not project two
    t1h = _login(client, "t1@test.dev", "TestPass!23")
    r = client.get("/api/projects", headers=t1h)
    names = [p["name"] for p in r.json()]
    assert names == ["Project One"]

    # tester1 cannot access project two directly
    r = client.get(f"/api/projects/{p2['id']}", headers=t1h)
    assert r.status_code == 403

    # tester cannot be added to a hidden project's members list — and cannot read it either
    r = client.get(f"/api/projects/{p2['id']}/members", headers=t1h)
    assert r.status_code == 403

    # tester1 sees project one's member list
    r = client.get(f"/api/projects/{p1['id']}/members", headers=t1h)
    assert r.status_code == 200
    roles = {m["role"] for m in r.json()}
    assert roles == {"admin", "tester", "reviewer"}

    # super admin sees both projects
    r = client.get("/api/projects", headers=ah)
    assert len(r.json()) == 2


def test_membership_role_must_match_platform_role(client, db):
    admin, ah, tester1, tester2, reviewer, pm = _setup(client, db)
    p = _make_project(client, ah)
    # a platform tester cannot join as reviewer
    r = client.post(f"/api/projects/{p['id']}/members", headers=ah,
                    json={"user_id": tester1.id, "role": "reviewer"})
    assert r.status_code == 422
    # a platform reviewer cannot join as tester
    r = client.post(f"/api/projects/{p['id']}/members", headers=ah,
                    json={"user_id": reviewer.id, "role": "tester"})
    assert r.status_code == 422


def test_owner_cannot_be_removed(client, db):
    admin, ah, *_ = _setup(client, db)
    p = _make_project(client, ah)
    members = client.get(f"/api/projects/{p['id']}/members", headers=ah).json()
    admin_member = next(m for m in members if m["user_id"] == admin["user"]["id"])
    r = client.delete(f"/api/projects/{p['id']}/members/{admin_member['id']}", headers=ah)
    assert r.status_code == 400


def test_remove_member_and_readd(client, db):
    admin, ah, tester1, tester2, reviewer, pm = _setup(client, db)
    p = _make_project(client, ah)
    r = client.post(f"/api/projects/{p['id']}/members", headers=ah,
                    json={"user_id": tester1.id, "role": "tester"})
    member_id = r.status_code and client.get(f"/api/projects/{p['id']}/members", headers=ah).json()[0]["id"] if False else None
    members = client.get(f"/api/projects/{p['id']}/members", headers=ah).json()
    tester_member = next(m for m in members if m["user_id"] == tester1.id)
    r = client.delete(f"/api/projects/{p['id']}/members/{tester_member['id']}", headers=ah)
    assert r.status_code == 204
    t1h = _login(client, "t1@test.dev", "TestPass!23")
    assert client.get(f"/api/projects/{p['id']}", headers=t1h).status_code == 403
    # re-add works
    r = client.post(f"/api/projects/{p['id']}/members", headers=ah,
                    json={"user_id": tester1.id, "role": "tester"})
    assert r.status_code == 201


def test_project_manager_sees_only_administered_projects(client, db):
    admin, ah, tester1, tester2, reviewer, pm = _setup(client, db)
    p1 = _make_project(client, ah, "PM Project")
    _make_project(client, ah, "Other Project")
    client.post(f"/api/projects/{p1['id']}/members", headers=ah, json={"user_id": pm.id, "role": "admin"})
    pmh = _login(client, "pm@test.dev", "TestPass!23")
    r = client.get("/api/projects", headers=pmh)
    names = [p["name"] for p in r.json()]
    assert names == ["PM Project"]
    # PM manages their project's membership
    r = client.post(f"/api/projects/{p1['id']}/members", headers=pmh,
                    json={"user_id": tester1.id, "role": "tester"})
    assert r.status_code == 201


def test_project_archive(client, db):
    admin, ah, *_ = _setup(client, db)
    p = _make_project(client, ah)
    r = client.post(f"/api/projects/{p['id']}/archive", headers=ah)
    assert r.status_code == 204
    body = client.get(f"/api/projects/{p['id']}", headers=ah).json()
    assert body["status"] == "archived"


def test_admin_overview_reports_live_counts(client, db):
    admin, ah, *_ = _setup(client, db)
    _make_project(client, ah, "Overview P1")
    r = client.get("/api/analytics/admin-overview", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["total_projects"] == 1
    assert body["active_projects"] == 1
    assert body["task_total"] == 0
    assert body["tasks_by_status"]["available"] == 0
    assert body["overall_quality_score"] is None  # no decided submissions yet
    assert len(body["daily_submissions"]) == 14


def test_worker_cannot_access_admin_overview(client, db):
    admin, ah, tester1, *_ = _setup(client, db)
    t1h = _login(client, "t1@test.dev", "TestPass!23")
    r = client.get("/api/analytics/admin-overview", headers=t1h)
    assert r.status_code == 403
