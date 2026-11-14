"""Phase 5: dynamic rubric forms, drafts, submission validation, resubmission."""
import json

from app.core.security import hash_password
from app.models.task import Task
from app.models.user import User
from tests.conftest import _register

FORM_RUBRIC = {
    "name": "Form Rubric",
    "criteria": [{
        "id": "c1", "name": "Compliance", "weight": 1,
        "scoring_scale": {"type": "binary", "min": 0, "max": 1}, "pass_threshold": 1,
        "checks": [{"type": "completeness", "params": {}}],
    }],
    "passing_threshold": 0.6,
    "form": {
        "fields": [
            {"id": "accurate", "type": "yes_no", "label": "Is the response accurate?", "required": True},
            {"id": "severity", "type": "likert", "label": "Severity of issues", "required": True,
             "scale": {"min": 1, "max": 5}},
            {"id": "error_type", "type": "single_select", "label": "Main issue",
             "options": ["none", "factual", "formatting", "other"], "required": True},
            {"id": "sub_issues", "type": "multi_select", "label": "Also present",
             "options": ["tone", "citations", "length"]},
            {"id": "why_inaccurate", "type": "text", "label": "Explain the inaccuracy",
             "required": True, "conditional_on": {"field_id": "accurate", "values": ["no"]}},
            {"id": "sources", "type": "evidence", "label": "Evidence links"},
        ]
    },
}


def _setup(client, db, rubric=None):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    tester = User(email="t1@test.dev", name="T1", hashed_password=hash_password("TestPass!23"), role="tester")
    db.add(tester)
    db.commit()
    p = client.post("/api/projects", headers=ah, json={"name": "Sub Project"}).json()
    ds = client.post("/api/datasets", headers=ah, json={"name": "Sub DS", "project_id": p["id"]}).json()
    client.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah, files={
        "file": ("r.json", json.dumps([{"record_id": "s1", "prompt": "P", "response": "R"}]).encode(), "application/json")})
    ru = client.post("/api/rubrics", headers=ah, json={"name": "Sub Rubric", "definition": rubric or FORM_RUBRIC}).json()
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"user_id": tester.id, "role": "tester"})
    client.post("/api/tasks/generate", headers=ah, json={
        "project_id": p["id"], "dataset_id": ds["id"], "rubric_id": ru["id"]})
    th = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 't1@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    task = client.get("/api/tasks/available", headers=th).json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/claim", headers=th)
    client.post(f"/api/tasks/{task['id']}/start", headers=th)
    return admin, ah, th, tester, p, ds, ru, task


GOOD_PAYLOAD = {
    "accurate": "no", "severity": 3, "error_type": "factual",
    "sub_issues": ["tone"], "why_inaccurate": "The number contradicts the policy.",
    "sources": [{"kind": "url", "value": "https://example.com/policy"}],
}


def test_form_rubric_validates_definition(client, db):
    r = _register(client, "v@test.dev", "V", "AdminPass!23")
    h = {"Authorization": f"Bearer {r['access_token']}"}
    good = dict(FORM_RUBRIC)
    res = client.post("/api/rubrics/validate", headers=h, json={"definition": good})
    assert res.json()["valid"] is True, res.json()

    bad = dict(FORM_RUBRIC, form={"fields": [
        {"id": "a", "type": "yes_no", "label": "A"},
        {"id": "a", "type": "yes_no", "label": "dup"},
        {"id": "b", "type": "single_select", "label": "B"},   # missing options
        {"id": "c", "type": "likert", "label": "C", "scale": {"min": 5, "max": 1}},
        {"id": "d", "type": "text", "label": "D",
         "conditional_on": {"field_id": "zzz", "values": ["x"]}},
    ]})
    res = client.post("/api/rubrics/validate", headers=h, json={"definition": bad})
    body = res.json()
    assert body["valid"] is False
    msgs = [e["message"] for e in body["errors"]]
    assert any("Duplicate form field id" in m for m in msgs)
    assert any("options list" in m for m in msgs)
    assert any("min < max" in m for m in msgs)
    assert any("EARLIER" in m for m in msgs)


def test_workspace_returns_dynamic_form(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    r = client.get(f"/api/submissions/tasks/{task['id']}/workspace", headers=th)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [f["id"] for f in body["form_fields"]]
    assert ids == ["accurate", "severity", "error_type", "sub_issues", "why_inaccurate", "sources"]
    assert body["can_submit"] is True
    assert body["record"]["prompt"] == "P"


def test_draft_autosave_and_restore(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    r = client.post(f"/api/submissions/tasks/{task['id']}/draft", headers=th,
                    json={"payload": {"accurate": "yes", "severity": 2}})
    assert r.status_code == 200

    ws = client.get(f"/api/submissions/tasks/{task['id']}/workspace", headers=th).json()
    assert ws["draft_payload"]["accurate"] == "yes"

    # another tester cannot overwrite the draft
    db.add(User(email="t2@test.dev", name="T2", hashed_password=hash_password("TestPass!23"), role="tester"))
    db.commit()
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"user_id": 0} if False else {"email": "t2@test.dev", "role": "tester"})
    th2 = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 't2@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r = client.post(f"/api/submissions/tasks/{task['id']}/draft", headers=th2, json={"payload": {}})
    assert r.status_code == 403


def test_submission_validation_and_duplicate_prevention(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)

    # missing required fields (why_inaccurate is required because accurate=no)
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": {"accurate": "no", "severity": 9, "error_type": "nope"}})
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]["errors"]
    assert any("required" in e for e in errors)          # conditional field
    assert any("Severity" in e or "severity" in e for e in errors)  # likert out of range
    assert any("error_type" in e or "Main issue" in e for e in errors)  # bad option

    # unknown field rejected
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": {**GOOD_PAYLOAD, "hacker_field": "x"}, "explanation": "x"})
    assert r.status_code == 422
    assert any("Unknown form fields" in e for e in r.json()["detail"]["errors"])

    # valid submission
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD, "explanation": "Found factual errors.",
                          "evidence": [{"kind": "url", "value": "https://example.com"}],
                          "time_spent_seconds": 480})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["attempt_number"] == 1
    assert body["label"] == "fail"  # derived from accurate=no
    assert body["status"] == "submitted"

    # duplicate submission refused (task now submitted)
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD})
    assert r.status_code == 422
    assert any("cannot be submitted" in e for e in r.json()["detail"]["errors"])

    # the payload's hidden-branch value is stripped when condition flips
    r = client.post("/api/rubrics/validate", headers=ah, json={"definition": FORM_RUBRIC})
    assert r.json()["valid"] is True


def test_conditional_fields_hidden_branch_not_required(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    payload = {**GOOD_PAYLOAD, "accurate": "yes", "why_inaccurate": None}
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": payload, "explanation": "All good."})
    assert r.status_code == 201, r.text
    # hidden branch value not stored
    assert "why_inaccurate" not in r.json()["payload"]


def test_resubmission_after_revision_and_attempt_limit(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD, "explanation": "v1"})
    submission_id = r.json()["id"]

    # reviewer requests revision (staff acts as reviewer proxy here via service-level guard tested in phase 6;
    # here we drive the task status directly to simulate a revision request)
    client.post(f"/api/submissions/{submission_id}/review", headers=ah, json={
        "decision": "revision_requested", "comments": "Please check the numbers."})
    # task returned to revision_required and still assigned to the tester
    t = db.get(Task, task["id"])
    assert t.status == "revision_required"

    # resubmit -> attempt 2
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD, "explanation": "v2 fixed"})
    assert r.status_code == 201
    assert r.json()["attempt_number"] == 2

    # attempt limit: max_attempts=2 reached after revision
    client.post(f"/api/submissions/{r.json()['id']}/review", headers=ah, json={
        "decision": "revision_requested", "comments": "again"})
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD, "explanation": "v3"})
    assert r.status_code == 422
    assert any("Attempt limit" in e for e in r.json()["detail"]["errors"])


def test_tester_cannot_submit_others_task(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    db.add(User(email="t9@test.dev", name="T9", hashed_password=hash_password("TestPass!23"), role="tester"))
    db.commit()
    client.post(f"/api/projects/{p['id']}/members", headers=ah, json={"email": "t9@test.dev", "role": "tester"})
    th9 = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 't9@test.dev', 'password': 'TestPass!23'}).json()['access_token']}"}
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th9,
                    json={"payload": GOOD_PAYLOAD})
    assert r.status_code == 422  # not assigned to t9


def test_my_submissions_and_feedback(client, db):
    admin, ah, th, tester, p, ds, ru, task = _setup(client, db)
    r = client.post(f"/api/submissions/tasks/{task['id']}/submit", headers=th,
                    json={"payload": GOOD_PAYLOAD, "explanation": "v1"})
    sid = r.json()["id"]
    client.post(f"/api/submissions/{sid}/review", headers=ah, json={
        "decision": "rejected", "comments": "Wrong severity interpretation."})

    r = client.get("/api/submissions/mine", headers=th)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "rejected"

    ws = client.get(f"/api/submissions/tasks/{task['id']}/workspace", headers=th).json()
    assert any(f["decision"] == "rejected" and "severity" in (f["comments"] or "") for f in ws["feedback"])
