"""Phase 4: task generation, atomic claiming, assignment, reassignment, expiry."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.dataset import DatasetRecord
from app.models.rubric import RubricVersion
from app.models.task import Task
from app.models.user import User
from app.core.security import hash_password
from tests.conftest import _register, DEMO_RUBRIC


def _setup(client, db, records=3):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    tester = User(email="t1@test.dev", name="Tester One", hashed_password=hash_password("TestPass!23"), role="tester")
    tester2 = User(email="t2@test.dev", name="Tester Two", hashed_password=hash_password("TestPass!23"), role="tester")
    db.add_all([tester, tester2])
    db.commit()
    p = client.post("/api/projects", headers=ah, json={"name": "Task Project"}).json()
    ds = client.post("/api/datasets", headers=ah, json={"name": "Task DS", "project_id": p["id"]}).json()
    rows = [
        {"record_id": f"g{i}", "prompt": f"Prompt {i}", "response": f"Response {i}"}
        for i in range(records)
    ]
    import json
    client.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah,
                files={"file": ("r.json", json.dumps(rows).encode(), "application/json")})
    ru = client.post("/api/rubrics", headers=ah, json={"name": "Task Rubric", "definition": DEMO_RUBRIC}).json()
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"user_id": tester.id, "role": "tester"})
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"user_id": tester2.id, "role": "tester"})
    return admin, ah, tester, tester2, p, ds, ru


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_generate_tasks_from_dataset(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db)
    r = client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"],
        "priority": "high", "estimated_minutes": 10,
    })
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["created"] == 3

    # skip already-generated records
    r2 = client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    assert r2.json()["created"] == 0
    assert r2.json()["skipped_existing"] == 3

    # archived datasets rejected
    client.post(f"/api/datasets/{ds['id']}/archive", headers=ah)
    r3 = client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    assert r3.status_code == 409


def test_generate_respects_limit(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=5)
    r = client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"], "limit": 2})
    assert r.json()["created"] == 2


def test_manual_and_bulk_task_creation(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db)
    r = client.post("/api/tasks/manual", headers=ah, json={
        "project_id": p["id"], "title": "Manual review task", "instructions": "Do it carefully",
        "priority": "urgent", "max_attempts": 3,
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "available"

    r = client.post("/api/tasks/bulk-manual", headers=ah, json={
        "project_id": p["id"],
        "tasks": [{"title": "Bulk 1"}, {"title": "Bulk 2"}, {"title": ""}],
    })
    assert r.status_code == 201
    assert r.json()["created"] == 2 and len(r.json()["rejected"]) == 1


def test_atomic_claim_only_one_winner(client, db):
    """Two testers race for one task: exactly one claim wins."""
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]

    t1h = _login(client, "t1@test.dev", "TestPass!23")
    t2h = _login(client, "t2@test.dev", "TestPass!23")

    r1 = client.post(f"/api/tasks/{task['id']}/claim", headers=t1h)
    assert r1.status_code == 200, r1.text
    # the loser is rejected either by the route guard or the atomic claim guard
    r2 = client.post(f"/api/tasks/{task['id']}/claim", headers=t2h)
    assert r2.status_code == 409
    assert "claimed" in r2.json()["detail"] or "available" in r2.json()["detail"]

    body = client.get(f"/api/tasks/{task['id']}", headers=ah).json()
    assert body["assigned_tester_id"] == tester.id
    assert body["attempt_count"] == 1


def test_assign_and_start_flow(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=2)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]

    r = client.post(f"/api/tasks/{task['id']}/assign", headers=ah, json={"tester_id": tester.id})
    assert r.status_code == 200
    assert r.json()["status"] == "assigned"

    # second assignment fails (not available)
    r = client.post(f"/api/tasks/{task['id']}/assign", headers=ah, json={"tester_id": tester2.id})
    assert r.status_code == 409

    # assigned tester starts work
    t1h = _login(client, "t1@test.dev", "TestPass!23")
    r = client.post(f"/api/tasks/{task['id']}/start", headers=t1h)
    assert r.status_code == 200 and r.json()["status"] == "in_progress"

    # a non-assigned tester cannot start
    r = client.post(f"/api/tasks/{task['id']}/start", headers=_login(client, "t2@test.dev", "TestPass!23"))
    assert r.status_code == 403


def test_reassignment_history_preserved(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/assign", headers=ah, json={"tester_id": tester.id})
    r = client.post(f"/api/tasks/{task['id']}/reassign", headers=ah, json={"tester_id": tester2.id})
    assert r.status_code == 200 and r.json()["assigned_tester_id"] == tester2.id

    body = client.get(f"/api/tasks/{task['id']}", headers=ah).json()
    actions = [a["action"] for a in body["assignment_history"]]
    assert actions == ["assigned", "released", "reassigned"]
    assert body["attempt_count"] == 2


def test_release_returns_task_to_pool(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/assign", headers=ah, json={"tester_id": tester.id})
    r = client.post(f"/api/tasks/{task['id']}/release", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "available"
    # another tester can now claim it
    r = client.post(f"/api/tasks/{task['id']}/claim", headers=_login(client, "t2@test.dev", "TestPass!23"))
    assert r.status_code == 200


def test_pause_unpause_cancel(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]

    r = client.post(f"/api/tasks/{task['id']}/pause", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    # paused tasks are not visible in the marketplace
    r = client.post(f"/api/tasks/{task['id']}/claim", headers=_login(client, "t1@test.dev", "TestPass!23"))
    assert r.status_code == 409
    r = client.post(f"/api/tasks/{task['id']}/unpause", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "available"
    r = client.post(f"/api/tasks/{task['id']}/cancel", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_assignment_expiry(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/assign", headers=ah, json={"tester_id": tester.id})

    # force expiry in the past
    t = db.scalar(select(Task).where(Task.id == task["id"]))
    t.assignment_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    r = client.post("/api/tasks/maintenance/expire-assignments", headers=ah)
    assert r.json()["expired"] == 1
    body = client.get(f"/api/tasks/{task['id']}", headers=ah).json()
    assert body["status"] == "available"


def test_tester_marketplace_and_my_tasks(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=2)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})

    t1h = _login(client, "t1@test.dev", "TestPass!23")
    r = client.get("/api/tasks/available", headers=t1h)
    assert r.json()["total"] == 2

    # claim one -> mine shows it, available drops to 1
    task = r.json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/claim", headers=t1h)
    r = client.get("/api/tasks/available", headers=t1h)
    assert r.json()["total"] == 1
    r = client.get("/api/tasks/mine", headers=t1h)
    assert r.json()["total"] == 1


def test_tester_cannot_see_tasks_outside_projects(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=1)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    task = client.get("/api/tasks", headers=ah, params={"project_id": p["id"]}).json()["items"][0]

    # tester3 not a member
    db.add(User(email="t3@test.dev", name="T3", hashed_password=hash_password("TestPass!23"), role="tester"))
    db.commit()
    t3h = _login(client, "t3@test.dev", "TestPass!23")
    r = client.get(f"/api/tasks/{task['id']}", headers=t3h)
    assert r.status_code == 403
    r = client.post(f"/api/tasks/{task['id']}/claim", headers=t3h)
    assert r.status_code == 403
    # and cannot claim via generation-project mismatch either
    r = client.get("/api/tasks/available", headers=t3h)
    assert r.json()["total"] == 0


def test_staff_sees_task_list_with_filters(client, db):
    admin, ah, tester, tester2, p, ds, ru = _setup(client, db, records=3)
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"], "priority": "urgent"})
    r = client.get("/api/tasks", headers=ah, params={"priority": "urgent"})
    assert r.json()["total"] == 3
    r = client.get("/api/tasks", headers=ah, params={"status": "available"})
    assert r.json()["total"] == 3
    r = client.get("/api/tasks", headers=ah, params={"search": "Prompt 1"})
    assert r.json()["total"] == 1
