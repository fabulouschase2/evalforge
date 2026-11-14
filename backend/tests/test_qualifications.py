"""V3 Phase 4: qualifications — attempts, grading, skills, eligibility, overrides."""
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


MCQ_ASSESSMENT = {
    "title": "AI response evaluation basics",
    "assessment_type": "mcq",
    "skill_tags": ["AI response evaluation"],
    "time_limit_minutes": 30,
    "max_attempts": 2,
    "passing_score": 0.7,
    "questions": [
        {"question_type": "mcq", "prompt": "What does hallucination mean?",
         "options": ["Made-up content", "Fast answers", "Cheap hosting"],
         "correct_answer": {"value": "Made-up content"}, "points": 1},
        {"question_type": "mcq", "prompt": "Which is a factual claim?",
         "options": ["Paris is in France", "Cats are robots"],
         "correct_answer": {"value": "Paris is in France"}, "points": 1},
        {"question_type": "numeric", "prompt": "How many continents are there (number)?",
         "correct_answer": {"value": 7}, "points": 1},
    ],
}


@pytest.fixture()
def qual_world(client, db):
    ah = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {ah['access_token']}"}
    project = client.post("/api/projects", headers=ah, json={"name": "Qual Proj"}).json()
    tester = _register(client, "worker.q@test.dev", "Worker Q")
    client.post(f"/api/projects/{project['id']}/members", headers=ah,
                json={"email": "worker.q@test.dev", "role": "tester"})
    th = _login(client, "worker.q@test.dev", "TestPass!23")
    assessment = client.post("/api/qualifications", headers=ah, json=MCQ_ASSESSMENT)
    assert assessment.status_code == 201, assessment.text
    body = assessment.json()
    assert len(body["questions"]) == 3
    # worker view must NOT include correct answers
    worker_view = client.get(f"/api/qualifications/{body['id']}", headers=th).json()
    assert all("correct_answer" not in q for q in worker_view["questions"])
    return {"client": client, "ah": ah, "th": th, "project": project,
            "assessment": body, "tester_id": tester["user"]["id"]}


def test_auto_grading_pass(qual_world):
    c, th = qual_world["client"], qual_world["th"]
    aid = qual_world["assessment"]["id"]
    qs = qual_world["assessment"]["questions"]
    start = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    assert start.status_code == 201, start.text
    attempt_id = start.json()["attempt_id"]
    answers = {str(qs[0]["id"]): "Made-up content", str(qs[1]["id"]): "Paris is in France",
               str(qs[2]["id"]): "7"}
    r = c.post(f"/api/qualifications/attempts/{attempt_id}/submit", headers=th,
               json={"answers": answers})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["passed"] is True and body["auto_graded"] is True
    assert body["score"] == 1.0

    # passing grants the verified skill
    skills = c.get("/api/workers/me/skills", headers=th).json()["skills"]
    verified = [s for s in skills if s["source"] == "verified"]
    assert any(s["skill"] == "AI response evaluation" for s in verified)

    # re-taking a passed assessment is blocked
    r = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    assert r.status_code == 409


def test_auto_grading_fail_and_retry(qual_world):
    c, th = qual_world["client"], qual_world["th"]
    aid = qual_world["assessment"]["id"]
    qs = qual_world["assessment"]["questions"]
    start = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    attempt_id = start.json()["attempt_id"]
    answers = {str(qs[0]["id"]): "Fast answers", str(qs[1]["id"]): "Cats are robots",
               str(qs[2]["id"]): "5"}
    r = c.post(f"/api/qualifications/attempts/{attempt_id}/submit", headers=th, json={"answers": answers})
    assert r.json()["passed"] is False and r.json()["status"] == "failed"
    # second attempt allowed (max_attempts=2)
    start2 = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    assert start2.status_code == 201
    # after failing twice, no more attempts
    attempt2 = start2.json()["attempt_id"]
    c.post(f"/api/qualifications/attempts/{attempt2}/submit", headers=th, json={"answers": answers})
    r = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    assert r.status_code == 409


def test_text_questions_route_to_manual_grading(qual_world):
    c, ah, th = qual_world["client"], qual_world["ah"], qual_world["th"]
    payload = {
        "title": "Text evaluation exercise",
        "assessment_type": "text_grading",
        "skill_tags": ["Factuality verification"],
        "passing_score": 0.8,
        "questions": [
            {"question_type": "text",
             "prompt": "Explain why the response is misleading.",
             "correct_answer": {"value": "rubric reference"}, "points": 1},
        ],
    }
    a = c.post("/api/qualifications", headers=ah, json=payload).json()
    start = c.post(f"/api/qualifications/{a['id']}/attempts", headers=th)
    attempt_id = start.json()["attempt_id"]
    r = c.post(f"/api/qualifications/attempts/{attempt_id}/submit", headers=th,
               json={"answers": {str(a["questions"][0]["id"]): "Because it contradicts the reference."}})
    assert r.json()["auto_graded"] is False and r.json()["status"] == "under_review"

    # appears in the manual grading queue
    queue = c.get("/api/quality/qualifications", headers=ah).json()
    item = [x for x in queue if x["id"] == attempt_id]
    assert item and item[0]["assessment_title"] == "Text evaluation exercise"
    # grade it
    r = c.post(f"/api/quality/qualifications/{attempt_id}/grade", headers=ah, json={"score": 0.9})
    assert r.status_code == 200 and r.json()["status"] == "passed"
    skills = c.get("/api/workers/me/skills", headers=th).json()["skills"]
    assert any(s["skill"] == "Factuality verification" and s["source"] == "verified" for s in skills)


def test_project_eligibility_gate_and_override(qual_world):
    c, ah, th = qual_world["client"], qual_world["ah"], qual_world["th"]
    pid = qual_world["project"]["id"]
    aid = qual_world["assessment"]["id"]

    # dataset + rubric + tasks
    records = [{"record_id": "e1", "prompt": "p", "response": "r", "reference_answer": "ref"}]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    ds = c.post("/api/datasets", headers=ah, json={"name": "E DS", "project_id": pid}).json()
    c.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah, files=files)
    from tests.conftest import DEMO_RUBRIC
    rub = c.post("/api/rubrics", headers=ah, json={"name": "E Rubric", "definition": DEMO_RUBRIC}).json()
    c.post("/api/tasks/generate", headers=ah, json={
        "project_id": pid, "dataset_id": ds["id"], "rubric_id": rub["id"]})

    # require the qualification with a min score of 100%
    r = c.put(f"/api/qualifications/eligibility/{pid}", headers=ah,
              json={"requirements": [{"assessment_id": aid, "min_score": 1.0}]})
    assert r.status_code == 200

    items = c.get("/api/tasks/available", headers=th).json()["items"]
    assert items
    blocked = c.post(f"/api/tasks/{items[0]['id']}/claim", headers=th)
    assert blocked.status_code == 403
    assert "unmet" in blocked.json()["detail"]

    # pass the assessment -> eligible
    qs2 = qual_world["assessment"]["questions"]
    start = c.post(f"/api/qualifications/{aid}/attempts", headers=th)
    answers = {str(qs2[0]["id"]): "Made-up content", str(qs2[1]["id"]): "Paris is in France",
               str(qs2[2]["id"]): "7"}
    c.post(f"/api/qualifications/attempts/{start.json()['attempt_id']}/submit", headers=th,
           json={"answers": answers})
    ok = c.post(f"/api/tasks/{items[0]['id']}/claim", headers=th)
    assert ok.status_code == 200, ok.text


def test_eligibility_override_with_reason(qual_world):
    c, ah, th = qual_world["client"], qual_world["ah"], qual_world["th"]
    pid = qual_world["project"]["id"]
    aid = qual_world["assessment"]["id"]
    c.put(f"/api/qualifications/eligibility/{pid}", headers=ah,
          json={"requirements": [{"assessment_id": aid, "min_score": 1.0}]})
    # seed tasks for the project
    records = [{"record_id": "o1", "prompt": "p", "response": "r", "reference_answer": "ref"}]
    files = {"file": ("records.json", json.dumps(records).encode(), "application/json")}
    ds = c.post("/api/datasets", headers=ah, json={"name": "O DS", "project_id": pid}).json()
    c.post(f"/api/datasets/{ds['id']}/upload/commit", headers=ah, files=files)
    from tests.conftest import DEMO_RUBRIC
    rub = c.post("/api/rubrics", headers=ah, json={"name": "O Rubric", "definition": DEMO_RUBRIC}).json()
    c.post("/api/tasks/generate", headers=ah, json={
        "project_id": pid, "dataset_id": ds["id"], "rubric_id": rub["id"]})
    # override requires a reason
    r = c.post(f"/api/qualifications/eligibility/{pid}/override", headers=ah,
               json={"email": "worker.q@test.dev"})
    assert r.status_code == 422
    r = c.post(f"/api/qualifications/eligibility/{pid}/override", headers=ah,
               json={"email": "worker.q@test.dev", "reason": "Senior worker, grandfathered in."})
    assert r.status_code == 201
    items = c.get("/api/tasks/available", headers=th).json()["items"]
    assert c.post(f"/api/tasks/{items[0]['id']}/claim", headers=th).status_code == 200


def test_worker_skills_and_performance(qual_world):
    c, th = qual_world["client"], qual_world["th"]
    r = c.post("/api/workers/me/skills", headers=th, json={"skill": "Python"})
    assert r.status_code == 201 and r.json()["source"] == "self_reported"
    dup = c.post("/api/workers/me/skills", headers=th, json={"skill": "Python"})
    assert dup.status_code == 409
    perf = c.get("/api/workers/me/performance", headers=th).json()
    assert perf["submissions"]["total"] == 0
    assert perf["tier"]["tier"] in ("beginner", "qualified", "advanced", "specialist")
    # self-reported and verified skills are distinguishable
    skills = c.get("/api/workers/me/skills", headers=th).json()["skills"]
    assert any(s["source"] == "self_reported" for s in skills)
