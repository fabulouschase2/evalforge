"""Audit logging and settings tests."""
from tests.conftest import make_dataset, make_rubric, make_run


def test_audit_records_key_actions(client, db, auth_headers):
    headers, _ = auth_headers
    ds, _ = make_dataset(client, headers)
    rid = make_rubric(client, headers)
    make_run(client, headers, ds, rid)

    logs = client.get("/api/audit-logs?page=1&page_size=100", headers=headers).json()
    actions = {i["action"] for i in logs["items"]}
    assert "dataset.create" in actions
    assert "dataset.import" in actions
    assert "rubric.create" in actions
    assert "evaluation.create" in actions
    assert "evaluation.execute" in actions
    assert "evaluation.completed" in actions
    assert logs["total"] >= 6


def test_audit_entries_have_user_and_ip(client, db, auth_headers):
    headers, _ = auth_headers
    make_dataset(client, headers)
    logs = client.get("/api/audit-logs", headers=headers).json()["items"]
    entry = next(i for i in logs if i["action"] == "dataset.create")
    assert entry["user_id"] is not None
    assert entry["ip"] is not None
    assert entry["details"]


def test_audit_filtering(client, db, auth_headers):
    headers, _ = auth_headers
    make_dataset(client, headers)
    make_dataset(client, headers)
    r = client.get("/api/audit-logs?action=dataset.create", headers=headers).json()
    assert r["total"] == 2
    r = client.get("/api/audit-logs?entity_type=dataset", headers=headers).json()
    assert all(i["entity_type"] == "dataset" for i in r["items"])


def test_settings_roundtrip_and_defaults(client, db, auth_headers):
    headers, _ = auth_headers
    s = client.get("/api/settings", headers=headers).json()
    assert s["review_blind_by_default"] is True
    assert 0 <= s["borderline_confidence_below"] <= 1

    s2 = client.put("/api/settings", headers=headers, json={"reviewers_per_result": 3}).json()
    assert s2["reviewers_per_result"] == 3
    assert s2["review_blind_by_default"] is True  # unchanged fields preserved

    s3 = client.put("/api/settings", headers=headers, json={"borderline_confidence_below": 2.0})
    assert s3.status_code == 422  # out of range


def test_demo_data_is_clearly_labeled(client, db, auth_headers):
    headers, _ = auth_headers
    r = client.post("/api/demo/load", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["is_demo"] is True
    assert "not production" in body["note"].lower() or "demonstration" in body["note"].lower()
    ds = client.get(f"/api/datasets/{body['dataset_id']}", headers=headers).json()
    assert ds["is_demo"] is True
    assert "[DEMO]" in ds["name"]
