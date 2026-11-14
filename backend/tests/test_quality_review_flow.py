"""Phases 6-8: reviewer workflow depth, adjudication, quality monitoring,
notifications and exports."""
import json

from sqlalchemy import select

from app.core.security import hash_password
from app.models.user import User
from tests.conftest import _register


def _setup(client, db, records=1):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    tester = User(email="t1@test.dev", name="T1", hashed_password=hash_password("TestPass!23"), role="tester")
    reviewer = User(email="r1@test.dev", name="R1", hashed_password=hash_password("TestPass!23"), role="reviewer")
    reviewer2 = User(email="r2@test.dev", name="R2", hashed_password=hash_password("TestPass!23"), role="reviewer")
    senior = User(email="q1@test.dev", name="Q1", hashed_password=hash_password("TestPass!23"), role="senior_reviewer")
    db.add_all([tester, reviewer, reviewer2, senior])
    db.commit()
    p = client.post("/api/projects", headers=ah, json={"name": "Review Project"}).json()
    ds = client.post("/api/datasets", headers=ah, json={"name": "Rev DS", "project_id": p["id"]}).json()
    client.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah, files={
        "file": ("r.json", json.dumps([
            {"record_id": f"c{i}", "prompt": f"P{i}", "response": f"R{i}"} for i in range(records)
        ]).encode(), "application/json")})
    ru = client.post("/api/rubrics", headers=ah, json={"name": "Rev Rubric", "definition": {
        "name": "Rev Rubric",
        "criteria": [{"id": "c", "name": "C", "weight": 1,
                      "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
                      "checks": [{"type": "completeness", "params": {}}]}],
        "passing_threshold": 0.6,
        "form": {"fields": [
            {"id": "verdict", "type": "single_select", "label": "Verdict",
             "options": ["good", "bad"], "required": True},
            {"id": "score", "type": "likert", "label": "Score", "required": True, "scale": {"min": 1, "max": 5}},
        ]},
    }}).json()
    for u in (tester, reviewer, reviewer2):
        client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"user_id": u.id, "role": "tester" if u.role == "tester" else "reviewer"})
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    th = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 't1@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r1h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'r1@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r2h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'r2@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    qh = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'q1@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    return admin, ah, th, r1h, r2h, qh, p, ds, ru


def _submit_one(client, th, payload=None, explanation="My analysis"):
    task = client.get("/api/tasks/available", headers=th).json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/claim", headers=th)
    client.post(f"/api/tasks/{task['id']}/start", headers=th)
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th, json={
        "payload": payload or {"verdict": "good", "score": 4}, "explanation": explanation})
    assert r.status_code == 201, r.text
    return r.json()


def test_reviewer_queue_and_blind_review(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db)
    submission = _submit_one(client, th)

    # reviewer sees the queue with tester identity hidden (blind by default)
    r = client.get("/api/submissions/review-queue", headers=r1h)
    assert r.status_code == 200 and r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["tester_name"] is None  # blind

    # claim -> under_review
    r = client.post(f"/api/submissions/{submission['id']}/claim-review", headers=r1h)
    assert r.status_code == 200 and r.json()["status"] == "under_review"
    # second reviewer cannot claim the same
    r = client.post(f"/api/submissions/{submission['id']}/claim-review", headers=r2h)
    assert r.status_code == 409

    # first approval does not finalize (project has 2 reviewers)
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=r1h, json={
        "decision": "approved", "comments": "Solid work."})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/submissions/{submission['id']}", headers=ah).json()
    assert body["status"] == "under_review"

    # append-only: same reviewer cannot decide again
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=r1h, json={"decision": "rejected"})
    assert r.status_code == 409

    # consensus: second approval finalizes
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=r2h, json={
        "decision": "approved", "comments": "Agreed."})
    assert r.status_code == 200
    task = client.get(f"/api/tasks/{submission['task_id']}", headers=ah).json()
    assert task["status"] == "approved"

    # decided submission cannot be re-decided
    db.add(User(email="r3@test.dev", name="R3", hashed_password=hash_password("TestPass!23"), role="reviewer"))
    db.commit()
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"email": "r3@test.dev", "role": "reviewer"})
    r3h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'r3@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=r3h, json={"decision": "rejected"})
    assert r.status_code == 409

    # tester received the decision + notification
    r = client.get(f"/api/submissions/{submission['id']}", headers=th)
    body = r.json()
    assert body["status"] == "approved"
    assert any(rv["decision"] == "approved" for rv in body["reviews"])
    notes = client.get("/api/notifications", headers=th).json()
    assert any(n["type"] == "review_decision" for n in notes["items"])


def test_reviewer_cannot_review_outside_project(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db)
    submission = _submit_one(client, th)
    # outsider reviewer (not a member)
    db.add(User(email="rx@test.dev", name="RX", hashed_password=hash_password("TestPass!23"), role="reviewer"))
    db.commit()
    rxh = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'rx@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r = client.get("/api/submissions/review-queue", headers=rxh)
    assert r.json()["total"] == 0
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=rxh,
                    json={"decision": "approved"})
    assert r.status_code == 403


def test_revision_request_returns_task_to_tester(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db)
    submission = _submit_one(client, th)
    client.post(f"/api/submissions/{submission['id']}/review", headers=r1h, json={
        "decision": "revision_requested", "comments": "Check the score field."})
    # task back with the tester as revision_required
    task = client.get(f"/api/tasks/{submission['task_id']}", headers=ah).json()
    assert task["status"] == "revision_required"
    assert task["assigned_tester_id"] is not None
    # notification sent
    notes = client.get("/api/notifications", headers=th).json()
    assert any(n["type"] == "revision_requested" for n in notes["items"])


def test_adjudication_flow_with_conflicting_reviews(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db, records=2)
    submission = _submit_one(client, th, payload={"verdict": "good", "score": 3})

    # two reviewers disagree
    client.post(f"/api/submissions/{submission['id']}/claim-review", headers=r1h)
    client.post(f"/api/submissions/{submission['id']}/review", headers=r1h,
                json={"decision": "approved", "comments": "Fine."})
    # second review on the same submission (state is under_review; r2 decides without claiming via queue guard?
    # decide_review allows submitted/under_review states, so r2 can add a conflicting decision)
    r = client.post(f"/api/submissions/{submission['id']}/review", headers=r2h,
                    json={"decision": "rejected", "comments": "Score too generous."})
    assert r.status_code == 200

    # appears in the adjudication queue
    r = client.get("/api/quality/adjudication-queue", headers=qh)
    assert r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["decision_counts"] == {"approved": 1, "rejected": 1}

    # tester cannot adjudicate
    r = client.post(f"/api/quality/submissions/{submission['id']}/adjudicate", headers=th,
                    json={"final_decision": "approved", "rationale": "self-approve"})
    assert r.status_code == 403

    # senior reviewer adjudicates
    r = client.post(f"/api/quality/submissions/{submission['id']}/adjudicate", headers=qh, json={
        "final_decision": "approved", "rationale": "R1's reasoning is grounded in the rubric."})
    assert r.status_code == 200, r.text

    # original reviews preserved + adjudication recorded
    body = client.get(f"/api/submissions/{submission['id']}", headers=ah).json()
    assert body["status"] == "approved"
    assert len(body["reviews"]) == 2
    assert body["adjudication"]["final_decision"] == "approved"
    assert sorted(body["reviews"][i]["decision"] for i in range(2)) == ["approved", "rejected"]

    # double adjudication blocked
    r = client.post(f"/api/quality/submissions/{submission['id']}/adjudicate", headers=qh,
                    json={"final_decision": "rejected", "rationale": "changed my mind"})
    assert r.status_code == 409

    # adjudication requires 2+ reviews
    submission2 = _submit_one(client, th, payload={"verdict": "bad", "score": 2})
    client.post(f"/api/submissions/{submission2['id']}/review", headers=r1h, json={"decision": "rejected"})
    r = client.post(f"/api/quality/submissions/{submission2['id']}/adjudicate", headers=qh,
                    json={"final_decision": "rejected", "rationale": "solo"})
    assert r.status_code == 400


def test_quality_monitoring_endpoints(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db, records=2)
    s1 = _submit_one(client, th)
    client.post(f"/api/submissions/{s1['id']}/claim-review", headers=r1h)
    client.post(f"/api/submissions/{s1['id']}/review", headers=r1h, json={"decision": "approved", "ambiguous": True})
    client.post(f"/api/submissions/{s1['id']}/review", headers=r2h, json={"decision": "rejected", "comments": "No."})

    # tester submits a second one (approved by both reviewers for agreement data)
    s2 = _submit_one(client, th, payload={"verdict": "bad", "score": 2})
    client.post(f"/api/submissions/{s2['id']}/review", headers=r1h, json={"decision": "rejected"})
    client.post(f"/api/submissions/{s2['id']}/review", headers=r2h, json={"decision": "rejected"})

    ov = client.get("/api/quality/overview", headers=qh).json()
    assert ov["multi_review_items"] == 2
    assert ov["disagreement_items"] == 1
    assert ov["disagreement_rate"] == 0.5
    assert ov["ambiguous_reviews"] >= 1

    # tester cannot access quality monitoring
    r = client.get("/api/quality/overview", headers=th)
    assert r.status_code == 403

    consistency = client.get("/api/quality/reviewer-consistency", headers=qh).json()
    names = {rv["name"]: rv for rv in consistency["reviewers"]}
    assert names["R1"]["total_reviews"] == 2

    tester_quality = client.get("/api/quality/tester-quality", headers=qh).json()
    assert tester_quality["testers"][0]["submitted"] == 2

    agreement = client.get("/api/quality/agreement", headers=qh).json()
    assert agreement["items_with_multiple_reviews"] == 2
    assert agreement["full_agreement_items"] == 1
    assert agreement["raw_agreement_rate"] == 0.5
    assert agreement["fleiss_kappa"] is not None

    sample = client.get("/api/quality/sample", headers=qh, params={"n": 1, "status": "approved"})
    assert sample.status_code == 200


def test_notifications_flow(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db)
    submission = _submit_one(client, th)
    client.post(f"/api/submissions/{submission['id']}/review", headers=r1h,
                json={"decision": "approved"})

    r = client.get("/api/notifications/unread-count", headers=th)
    assert r.json()["unread"] >= 1

    items = client.get("/api/notifications", headers=th).json()["items"]
    first = items[0]
    r = client.post(f"/api/notifications/{first['id']}/read", headers=th)
    assert r.json()["ok"] is True

    r = client.post("/api/notifications/read-all", headers=th)
    assert r.json()["ok"] is True
    assert client.get("/api/notifications/unread-count", headers=th).json()["unread"] == 0

    # reviewer got notified of the submission earlier
    notes = client.get("/api/notifications", headers=r1h).json()
    assert any(n["type"] == "submission_received" for n in notes["items"])


def test_exports_permission_and_content(client, db):
    admin, ah, th, r1h, r2h, qh, p, ds, ru = _setup(client, db)
    s = _submit_one(client, th)
    client.post(f"/api/submissions/{s['id']}/review", headers=r1h, json={"decision": "approved"})

    r = client.get("/api/exports/tasks", headers=ah, params={"format": "csv"})
    assert r.status_code == 200
    assert "task_id,project_id,title" in r.text
    r = client.get("/api/exports/submissions", headers=ah, params={"format": "json"})
    assert r.status_code == 200
    assert len(r.json()) == 1

    # tester cannot export
    r = client.get("/api/exports/tasks", headers=th)
    assert r.status_code == 403

    # export audited
    logs = client.get("/api/audit-logs?action=data.export", headers=ah).json()
    assert logs["total"] >= 1
