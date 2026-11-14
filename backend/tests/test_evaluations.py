"""Evaluation run flow, findings traceability and gold-label metric tests."""
from tests.conftest import DEMO_RUBRIC, make_dataset, make_rubric, make_run


def _sample_records():
    return [
        {"record_id": "g1", "prompt": "What is 2+2?", "response": "2+2 equals 4.",
         "reference_answer": "2+2 equals 4.", "expected_label": "pass"},
        {"record_id": "g2", "prompt": "Capital of France?", "response": "The capital of France is Berlin.",
         "reference_answer": "Paris is the capital of France.", "expected_label": "fail"},
        {"record_id": "g3", "prompt": "Capital of France?", "response": "The capital of France is Paris.",
         "reference_answer": "Paris is the capital of France.", "expected_label": "pass"},
    ]


def test_run_completes_with_findings(client, db, auth_headers):
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers, records=_sample_records())
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    assert run["status"] == "completed"
    assert run["total_records"] == 3
    assert run["passed_count"] + run["failed_count"] + run["borderline_count"] == 3
    assert run["avg_score"] is not None


def test_findings_traceability_fields(client, db, auth_headers):
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers, records=_sample_records())
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    results = client.get(f"/api/evaluations/{run['id']}/results?page=1&page_size=10", headers=headers).json()["items"]
    detail = client.get(f"/api/evaluations/{run['id']}/results/{results[0]['id']}", headers=headers).json()
    assert len(detail["findings"]) > 0
    f = detail["findings"][0]
    for key in ("rule_id", "check_type", "passed", "evidence",
                "evaluator_version", "rubric_version", "executed_at"):
        assert key in f and f[key] is not None
    # explanation is optional (set for failures/inconclusive, None when passing)
    assert "explanation" in f


def test_metrics_require_gold_labels(client, db, auth_headers):
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers, records=_sample_records())
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    r = client.get(f"/api/analytics/metrics?run_id={run['id']}", headers=headers)
    body = r.json()
    assert body["gold_labeled_count"] == 3
    assert body["accuracy"] is not None
    assert body["confusion_matrix"]["labels"] == ["fail", "pass"]
    # 1 predicted error (g2 says Berlin -> automated fail matches gold fail? g2 response mentions Berlin only)
    # gold pass: g1, g3; gold fail: g2


def test_metrics_insufficient_without_gold(client, db, auth_headers):
    headers, _ = auth_headers
    records = [{"record_id": "n1", "prompt": "p", "response": "some response text here"}]
    ds, _ = make_dataset(client, headers, records=records)
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    r = client.get(f"/api/analytics/metrics?run_id={run['id']}", headers=headers)
    body = r.json()
    assert body["accuracy"] is None
    assert body["insufficient_reason"] is not None
    assert "gold" in body["insufficient_reason"].lower()


def test_completed_run_cannot_rerun(client, db, auth_headers):
    """Re-running must create a new run — historical results are preserved."""
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers, records=_sample_records())
    rid = make_rubric(client, headers)
    run = make_run(client, headers, ds, rid)
    r = client.post(f"/api/evaluations/{run['id']}/run", headers=headers)
    assert r.status_code == 409


def test_new_rubric_version_used_by_new_run(client, db, auth_headers):
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers, records=_sample_records())
    rid = make_rubric(client, headers)
    run1 = make_run(client, headers, ds, rid)
    assert run1["rubric_version_id"] > 0

    # bump rubric
    changed = dict(DEMO_RUBRIC)
    changed["passing_threshold"] = 0.9
    client.put(f"/api/rubrics/{rid}", headers=headers, json={"definition": changed})

    r = client.post("/api/evaluations", headers=headers, json={"name": "Run 2", "dataset_id": ds, "rubric_id": rid})
    run2_id = r.json()["id"]
    client.post(f"/api/evaluations/{run2_id}/run", headers=headers)
    r2 = client.get(f"/api/evaluations/{run2_id}", headers=headers).json()
    assert r2["rubric_version_id"] != run1["rubric_version_id"]
