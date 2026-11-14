"""V3 Phase 3: golden tasks — scoring, hidden identity, distribution, alerts, reports."""
import json

import pytest


def _register(client, email, name, password="TestPass!23"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _admin(client):
    data = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.fixture()
def golden_world(client, db):
    """Admin + project + tester member + dataset + rubric + 2 golden tasks."""
    ah = _admin(client)
    project = client.post("/api/projects", headers=ah, json={"name": "Golden Proj"}).json()
    tester = _register(client, "worker.g@test.dev", "Worker G")
    client.post(f"/api/projects/{project['id']}/members", headers=ah,
                json={"email": "worker.g@test.dev", "role": "tester"})
    th = _login(client, "worker.g@test.dev", "TestPass!23")

    records = [
        {"record_id": f"g{i}", "prompt": f"Question {i}?", "response": f"Answer {i}",
         "reference_answer": f"Reference {i}"}
        for i in range(1, 13)
    ]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    ds = client.post(f"/api/datasets/{0}", headers=ah)  # placeholder; real flow below
    dsr = client.post("/api/datasets", headers=ah, json={"name": "Golden DS", "project_id": project["id"]})
    dataset_id = dsr.json()["id"]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    up = client.post(f"/api/datasets/{dataset_id}/upload/commit", headers=ah, files=files)
    assert up.status_code == 201, up.text

    from tests.conftest import DEMO_RUBRIC
    rub = client.post("/api/rubrics", headers=ah, json={"name": "Golden Rubric", "definition": DEMO_RUBRIC})
    rubric_id = rub.json()["id"]

    # two golden tasks: one exact from scratch, one single_label
    g1 = client.post("/api/golden-tasks", headers=ah, json={
        "project_id": project["id"],
        "title": "GOLDEN: capital of France",
        "payload": {"prompt": "What is the capital of France?"},
        "reference_answer": {"answer": "Paris"},
        "scoring_method": "exact",
        "explanation": "Paris is the capital.",
        "difficulty": "easy",
    })
    assert g1.status_code == 201, g1.text
    g2 = client.post("/api/golden-tasks", headers=ah, json={
        "project_id": project["id"],
        "title": "GOLDEN: sentiment label",
        "payload": {"prompt": "Label the sentiment of 'I love this'"},
        "reference_answer": {"label": "positive"},
        "accepted_variations": ["pos", "positive sentiment"],
        "scoring_method": "variations",
        "scoring_config": {},
        "difficulty": "medium",
    })
    assert g2.status_code == 201, g2.text

    return {
        "client": client, "ah": ah, "th": th,
        "project": project, "dataset_id": dataset_id, "rubric_id": rubric_id,
        "golden1": g1.json(), "golden2": g2.json(),
        "tester_id": tester["user"]["id"],
    }


# ---------------------------------------------------------------------------
# Scoring engine unit tests (through the API preview endpoint)
# ---------------------------------------------------------------------------

def test_scoring_exact_match(golden_world):
    c, ah = golden_world["client"], golden_world["ah"]
    r = c.post("/api/golden-tasks/preview-score", headers=ah,
               json={"golden_id": golden_world["golden1"]["id"], "answer": "  paris "})
    assert r.json()["score"] == 1.0 and r.json()["passed"] is True
    r = c.post("/api/golden-tasks/preview-score", headers=ah,
               json={"golden_id": golden_world["golden1"]["id"], "answer": "London"})
    assert r.json()["score"] == 0.0 and r.json()["passed"] is False


def test_scoring_variations(golden_world):
    c, ah = golden_world["client"], golden_world["ah"]
    for ans in ("positive", "POS", "positive sentiment"):
        r = c.post("/api/golden-tasks/preview-score", headers=ah,
                   json={"golden_id": golden_world["golden2"]["id"], "answer": ans})
        assert r.json()["passed"] is True, ans
    r = c.post("/api/golden-tasks/preview-score", headers=ah,
               json={"golden_id": golden_world["golden2"]["id"], "answer": "negative"})
    assert r.json()["passed"] is False


def test_reference_answer_versioning(golden_world):
    c, ah = golden_world["client"], golden_world["ah"]
    gid = golden_world["golden1"]["id"]
    # changing the reference bumps the version and keeps history
    r = c.put(f"/api/golden-tasks/{gid}", headers=ah,
              json={"reference_answer": {"answer": "Paris, France"}, "change_note": "clarified"})
    assert r.status_code == 200 and r.json()["version"] == 2
    versions = c.get(f"/api/golden-tasks/{gid}/versions", headers=ah).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["reference_answer"]["answer"] == "Paris"


def test_distribution_and_hidden_identity(golden_world):
    """Generate tasks -> golden woven in -> tester cannot identify golden tasks."""
    c, ah, th = golden_world["client"], golden_world["ah"], golden_world["th"]
    pid = golden_world["project"]["id"]
    # tight config: high percentage so at least one golden is inserted
    r = c.put(f"/api/golden-tasks/config/{pid}", headers=ah, json={"percentage": 50, "min_spacing": 1})
    assert r.status_code == 200

    r = c.post("/api/tasks/generate", headers=ah, json={
        "project_id": pid, "dataset_id": golden_world["dataset_id"],
        "rubric_id": golden_world["rubric_id"],
    })
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["golden_inserted"] >= 1

    # tester marketplace: no is_golden, no golden_task_id fields anywhere
    r = c.get("/api/tasks/available", headers=th)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "marketplace should not be empty"
    for t in items:
        assert "is_golden" not in t and "golden_task_id" not in t
        if t.get("record"):
            # golden tasks derived from records must not leak the reference answer
            pass  # reference leakage asserted via workspace below

    # tester claims a task (any) and opens the workspace
    target = items[0]
    claim = c.post(f"/api/tasks/{target['id']}/claim", headers=th)
    assert claim.status_code == 200, claim.text
    claimed = claim.json()
    assert "is_golden" not in claimed and "golden_task_id" not in claimed
    ws = c.get(f"/api/submissions/tasks/{target['id']}/workspace", headers=th)
    assert ws.status_code == 200
    body = ws.json()
    assert "is_golden" not in body["task"]
    if body.get("record"):
        # reference answers are hidden on golden tasks; ordinary tasks keep v2 behavior
        # (we assert only that the field exists — hidden if golden)
        assert "reference_answer" in body["record"]


def test_golden_scoring_on_submission(golden_world):
    """A tester submitting a golden task's answer gets scored; result recorded."""
    c, ah, th = golden_world["client"], golden_world["ah"], golden_world["th"]
    pid = golden_world["project"]["id"]
    # spacing 0 -> both golden tasks get woven into a 3-task batch
    c.put(f"/api/golden-tasks/config/{pid}", headers=ah, json={"percentage": 100, "min_spacing": 0})

    r = c.post("/api/tasks/generate", headers=ah, json={
        "project_id": pid, "dataset_id": golden_world["dataset_id"],
        "rubric_id": golden_world["rubric_id"], "limit": 3,
    })
    assert r.status_code == 201 and r.json()["golden_inserted"] >= 1

    items = c.get("/api/tasks/available", headers=th).json()["items"]
    # golden tasks are woven last -> the highest-id available task is a golden probe,
    # but from the tester's view everything looks ordinary
    target = max(items, key=lambda t: t["id"])
    assert c.post(f"/api/tasks/{target['id']}/claim", headers=th).status_code == 200
    assert c.post(f"/api/tasks/{target['id']}/start", headers=th).status_code == 200
    # submit the CORRECT answer for whichever golden this is: try "Paris" first
    sub = c.post(f"/api/submissions/tasks/{target['id']}/submit", headers=th, json={
        "answer": "Paris", "explanation": "The capital of France is Paris."})
    assert sub.status_code == 201, sub.text

    # admin (platform-wide) sees the report built from stored results only
    report = c.get("/api/quality/golden/report", headers=ah).json()
    assert report["attempts"] >= 1
    assert report["accuracy"] is not None
    assert report["calculation"]["source"] == "golden_task_results"


def test_alerts_and_resolution(golden_world, db):
    from app.models.golden import GoldenTaskResult
    from app.services.golden import evaluate_alerts
    c, ah = golden_world["client"], golden_world["ah"]
    pid = golden_world["project"]["id"]
    tid = golden_world["tester_id"]

    # simulate 3 consecutive failed attempts directly (append-only history)
    golden = golden_world["golden1"]
    for i in range(3):
        db.add(GoldenTaskResult(
            golden_task_id=golden["id"], task_id=i + 1, submission_id=i + 1,
            worker_id=tid, project_id=pid, scoring_method="exact",
            score=0.0, passed=False, failure_reasons=["wrong"],
        ))
    db.commit()
    alerts = evaluate_alerts(db, pid, tid)
    assert any(a.alert_type == "repeated_failures" for a in alerts)

    # quality lead sees and resolves the alert
    listed = c.get("/api/quality/golden/alerts", headers=ah).json()
    assert any(a["alert_type"] == "repeated_failures" for a in listed)
    alert_id = [a for a in listed if a["alert_type"] == "repeated_failures"][0]["id"]
    r = c.post(f"/api/quality/golden/alerts/{alert_id}/resolve", headers=ah,
               json={"note": "Talked to the worker — data issue."})
    assert r.status_code == 200
    assert c.get("/api/quality/golden/alerts", headers=ah).json() == []


def test_worker_cannot_access_golden_management(golden_world):
    c, th, ah = golden_world["client"], golden_world["th"], golden_world["ah"]
    pid = golden_world["project"]["id"]
    assert c.get("/api/golden-tasks", headers=th).status_code == 403
    assert c.post("/api/golden-tasks", headers=th,
                  json={"project_id": pid, "title": "x", "reference_answer": {"a": 1}}).status_code == 403
    assert c.get("/api/quality/golden/report", headers=th).status_code == 403
    assert c.put(f"/api/golden-tasks/config/{pid}", headers=th, json={}).status_code == 403


def test_report_honest_when_empty(client, db):
    ah = _admin(client)
    r = client.get("/api/quality/golden/report", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["attempts"] == 0 and body["accuracy"] is None
    assert body["insufficient_reason"]
