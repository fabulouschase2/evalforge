"""Phase 3: data collection — manual records, bulk paste, custom fields, archive/export."""
from app.models.task import Task
from tests.conftest import _register


def _setup(client, db, dataset_name="Collection DS", definitions=None):
    admin = _register(client, "admin@test.dev", "Admin", "AdminPass!23")
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/projects", headers=ah, json={"name": "Collection Project"})
    project_id = r.json()["id"]
    r = client.post("/api/datasets", headers=ah, json={"name": dataset_name, "project_id": project_id})
    assert r.status_code == 201
    dataset_id = r.json()["id"]
    if definitions is not None:
        r = client.put(f"/api/datasets/{dataset_id}/custom-fields", headers=ah,
                       json={"definitions": definitions})
        assert r.status_code == 200, r.text
    return ah, dataset_id, project_id


BASE_RECORD = {
    "record_id": "m1",
    "prompt": "Summarize the refund policy.",
    "response": "Refunds are available within 30 days of purchase.",
    "reference_answer": "30-day refund window.",
    "expected_label": "pass",
    "content_category": "billing",
    "difficulty_level": "easy",
    "language": "en",
    "supporting_evidence": "Policy doc section 4.2",
    "source_url": "https://example.com/policy",
}


def test_manual_record_creation_and_listing(client, db):
    ah, dataset_id, _ = _setup(client, db)
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["record_id"] == "m1"
    assert body["collection_status"] == "collected"
    assert body["content_category"] == "billing"

    r = client.get(f"/api/datasets/{dataset_id}/records", headers=ah)
    assert r.json()["total"] == 1

    # auto-generated record ids
    rec2 = dict(BASE_RECORD, record_id="", prompt="Second prompt?")
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=rec2)
    assert r.status_code == 201
    assert r.json()["record_id"] == "manual_00002"

    # duplicate id rejected
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    assert r.status_code == 422


def test_record_validation_requires_prompt_and_response(client, db):
    ah, dataset_id, _ = _setup(client, db)
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah,
                    json={"record_id": "bad1", "prompt": "", "response": ""})
    assert r.status_code == 422
    errors = r.json()["detail"]["errors"]
    assert any("prompt" in e for e in errors) and any("response" in e for e in errors)


def test_custom_fields_validation(client, db):
    definitions = [
        {"key": "tone", "label": "Tone", "type": "select", "options": ["formal", "casual"], "required": True},
        {"key": "score_mult", "label": "Multiplier", "type": "number"},
    ]
    ah, dataset_id, _ = _setup(client, db, definitions=definitions)

    # missing required custom field
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    assert r.status_code == 422
    assert any("tone" in e for e in r.json()["detail"]["errors"])

    # bad option value
    rec = dict(BASE_RECORD, custom_fields={"tone": "salty"})
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=rec)
    assert r.status_code == 422

    # bad number
    rec = dict(BASE_RECORD, custom_fields={"tone": "formal", "score_mult": "abc"})
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=rec)
    assert r.status_code == 422

    # valid
    rec = dict(BASE_RECORD, custom_fields={"tone": "formal", "score_mult": 1.5})
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=rec)
    assert r.status_code == 201
    assert r.json()["custom_fields"]["tone"] == "formal"

    # unknown field rejected
    rec = dict(BASE_RECORD, record_id="m9", custom_fields={"tone": "formal", "nonsense": 1})
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=rec)
    assert r.status_code == 422

    # invalid definitions rejected at schema level
    r = client.put(f"/api/datasets/{dataset_id}/custom-fields", headers=ah,
                   json={"definitions": [{"key": "tone", "type": "select"}]})
    assert r.status_code == 422


def test_bulk_paste_records(client, db):
    ah, dataset_id, _ = _setup(client, db)
    rows = [
        dict(BASE_RECORD, record_id="b1"),
        dict(BASE_RECORD, record_id="b2", prompt="Second?"),
        dict(BASE_RECORD, record_id="b1"),            # duplicate in batch
        {"record_id": "b3", "prompt": "", "response": ""},  # invalid
    ]
    r = client.post(f"/api/datasets/{dataset_id}/records/bulk", headers=ah, json={"rows": rows})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["added"] == 2
    assert len(report["rejected"]) == 2
    assert client.get(f"/api/datasets/{dataset_id}/records", headers=ah).json()["total"] == 2


def test_record_edit_and_freeze_after_task_reference(client, db):
    ah, dataset_id, _ = _setup(client, db)
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    record_pk = r.json()["id"]

    r = client.patch(f"/api/datasets/{dataset_id}/records/{record_pk}", headers=ah,
                     json={"response": "Updated response.", "collection_status": "verified"})
    assert r.status_code == 200
    assert r.json()["response"] == "Updated response."

    # simulate a task referencing the record -> edits must be refused
    from sqlalchemy import select
    from app.models.dataset import DatasetRecord
    record = db.get(DatasetRecord, record_pk)
    db.add(Task(project_id=record.dataset.project_id, dataset_record_id=record.id,
                title="T", status="available"))
    db.commit()

    r = client.patch(f"/api/datasets/{dataset_id}/records/{record_pk}", headers=ah,
                     json={"response": "Nope."})
    assert r.status_code == 409
    r = client.delete(f"/api/datasets/{dataset_id}/records/{record_pk}", headers=ah)
    assert r.status_code == 409


def test_record_delete(client, db):
    ah, dataset_id, _ = _setup(client, db)
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    record_pk = r.json()["id"]
    r = client.delete(f"/api/datasets/{dataset_id}/records/{record_pk}", headers=ah)
    assert r.status_code == 204
    assert client.get(f"/api/datasets/{dataset_id}/records", headers=ah).json()["total"] == 0


def test_records_filters_and_search(client, db):
    ah, dataset_id, _ = _setup(client, db)
    client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)
    client.post(f"/api/datasets/{dataset_id}/records", headers=ah,
                json=dict(BASE_RECORD, record_id="m2", prompt="What is shipping cost?",
                          content_category="shipping", language="de", collection_status="verified"))
    r = client.get(f"/api/datasets/{dataset_id}/records", headers=ah,
                   params={"category": "shipping"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/datasets/{dataset_id}/records", headers=ah,
                   params={"status": "verified"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/datasets/{dataset_id}/records", headers=ah,
                   params={"language": "de"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/datasets/{dataset_id}/records", headers=ah,
                   params={"search": "shipping"})
    assert r.json()["total"] == 1


def test_archive_blocks_edits_and_export_works(client, db):
    ah, dataset_id, _ = _setup(client, db)
    client.post(f"/api/datasets/{dataset_id}/records", headers=ah, json=BASE_RECORD)

    r = client.get(f"/api/datasets/{dataset_id}/export", headers=ah, params={"format": "csv"})
    assert r.status_code == 200
    assert "record_id,prompt,response" in r.text
    r = client.get(f"/api/datasets/{dataset_id}/export", headers=ah, params={"format": "json"})
    assert r.status_code == 200
    body = r.json()
    assert body["dataset"]["record_count"] == 1
    assert body["records"][0]["record_id"] == "m1"

    r = client.post(f"/api/datasets/{dataset_id}/archive", headers=ah)
    assert r.status_code == 204
    # archived datasets reject edits
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah,
                    json=dict(BASE_RECORD, record_id="m3"))
    assert r.status_code == 409
    # restore
    r = client.post(f"/api/datasets/{dataset_id}/restore", headers=ah)
    assert r.status_code == 204
    r = client.post(f"/api/datasets/{dataset_id}/records", headers=ah,
                    json=dict(BASE_RECORD, record_id="m3"))
    assert r.status_code == 201


def test_export_is_audited(client, db):
    ah, dataset_id, _ = _setup(client, db)
    client.get(f"/api/datasets/{dataset_id}/export", headers=ah)
    logs = client.get("/api/audit-logs?action=dataset.export", headers=ah).json()
    assert logs["total"] >= 1
