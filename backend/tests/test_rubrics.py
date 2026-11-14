"""Rubric validation and immutable versioning tests."""
from tests.conftest import DEMO_RUBRIC, make_rubric


def test_valid_rubric_accepted(client, db, auth_headers):
    headers, _ = auth_headers
    rid = make_rubric(client, headers)
    assert rid > 0


def test_duplicate_criterion_ids_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    bad = {"name": "Bad", "criteria": [
        {"id": "c1", "name": "A", "weight": 1.0, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
        {"id": "c1", "name": "B", "weight": 1.0, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
    ], "passing_threshold": 0.7}
    r = client.post("/api/rubrics", headers=headers, json={"name": "Bad", "definition": bad})
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any("Duplicate criterion id" in e["message"] for e in errors)


def test_invalid_weights_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    bad = dict(DEMO_RUBRIC)
    bad["criteria"] = [
        {"id": "c1", "name": "A", "weight": -1, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
    ]
    bad["passing_threshold"] = 0.7
    r = client.post("/api/rubrics", headers=headers, json={"name": "Bad", "definition": bad})
    assert r.status_code == 422


def test_unknown_check_type_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    bad = dict(DEMO_RUBRIC)
    bad["criteria"] = [
        {"id": "c1", "name": "A", "weight": 1.0, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "psychic_intuition"}]},
    ]
    bad["passing_threshold"] = 0.7
    r = client.post("/api/rubrics", headers=headers, json={"name": "Bad", "definition": bad})
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any("Unknown check type" in e["message"] for e in errors)


def test_invalid_threshold_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    bad = dict(DEMO_RUBRIC)
    bad["passing_threshold"] = 1.5
    r = client.post("/api/rubrics", headers=headers, json={"name": "Bad", "definition": bad})
    assert r.status_code == 422


def test_likert_scale_validation(client, db, auth_headers):
    headers, _ = auth_headers
    bad = dict(DEMO_RUBRIC)
    bad["criteria"] = [
        {"id": "c1", "name": "A", "weight": 1.0, "scoring_scale": {"type": "likert", "min": 4, "max": 2},
         "pass_threshold": 2, "checks": [{"type": "completeness"}]},
    ]
    bad["passing_threshold"] = 0.7
    r = client.post("/api/rubrics", headers=headers, json={"name": "Bad", "definition": bad})
    assert r.status_code == 422


def test_validate_endpoint_reports_issues(client, db, auth_headers):
    headers, _ = auth_headers
    r = client.post("/api/rubrics/validate", headers=headers, json={"definition": {"name": ""}})
    body = r.json()
    assert body["valid"] is False
    assert len(body["errors"]) >= 2
    assert all(e["level"] == "error" for e in body["errors"])


def test_rubric_versions_immutable_and_incrementing(client, db, auth_headers):
    headers, _ = auth_headers
    rid = make_rubric(client, headers)

    r = client.get(f"/api/rubrics/{rid}/versions", headers=headers)
    assert len(r.json()) == 1
    original = r.json()[0]["definition"]

    # Update definition -> new version, original untouched
    changed = dict(DEMO_RUBRIC)
    changed["passing_threshold"] = 0.9
    r = client.put(f"/api/rubrics/{rid}", headers=headers, json={"definition": changed})
    assert r.status_code == 200
    assert r.json()["current_version"] == 2

    r = client.get(f"/api/rubrics/{rid}/versions", headers=headers)
    versions = {v["version_number"]: v["definition"] for v in r.json()}
    assert versions[1] == original  # immutable
    assert versions[2]["passing_threshold"] == 0.9

    # Identical update must NOT create a third version
    r = client.put(f"/api/rubrics/{rid}", headers=headers, json={"definition": changed})
    assert r.json()["current_version"] == 2


def test_delete_rubric_blocked_when_used(client, db, auth_headers):
    from tests.conftest import make_dataset, make_run
    headers, _ = auth_headers
    rid = make_rubric(client, headers)
    dataset_id, _ = make_dataset(client, headers)
    make_run(client, headers, dataset_id, rid)
    r = client.delete(f"/api/rubrics/{rid}", headers=headers)
    assert r.status_code == 409
