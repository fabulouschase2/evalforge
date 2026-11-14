"""Dataset upload, parsing, validation, duplicate detection and versioning tests."""
import json

from tests.conftest import make_dataset


def _commit(client, headers, dataset_id, content: bytes, filename="records.json"):
    return client.post(
        f"/api/datasets/{dataset_id}/upload/commit",
        headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_json_import_and_records(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, version = make_dataset(client, headers)
    assert version["record_count"] == 2
    assert version["version_number"] == 1

    r = client.get(f"/api/datasets/{dataset_id}/records", headers=headers)
    body = r.json()
    assert body["total"] == 2
    rec = body["items"][0]
    for key in ("record_id", "prompt", "response", "reference_answer", "reference_sources", "expected_label", "metadata"):
        assert key in rec


def test_jsonl_import(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    lines = "\n".join([
        json.dumps({"record_id": "j1", "prompt": "p1", "response": "r1"}),
        json.dumps({"record_id": "j2", "prompt": "p2", "response": "r2"}),
    ]).encode()
    r = _commit(client, headers, dataset_id, lines, "records.jsonl")
    assert r.status_code == 201
    assert r.json()["record_count"] == 2


def test_csv_import_with_column_mapping(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    csv_content = "id,question,answer,sources\n1,What is A?,A is X,src1\n2,What is B?,B is Y,src2\n".encode()
    r = client.post(
        f"/api/datasets/{dataset_id}/upload/commit",
        headers=headers,
        files={"file": ("records.csv", csv_content, "text/csv")},
        data={"column_mapping": json.dumps({"record_id": "id", "prompt": "question", "response": "answer"})},
    )
    assert r.status_code == 201, r.text
    assert r.json()["record_count"] == 2

    r = client.get(f"/api/datasets/{dataset_id}/records", headers=headers)
    prompts = [i["prompt"] for i in r.json()["items"]]
    assert "What is A?" in prompts


def test_invalid_dataset_missing_required_fields(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    content = json.dumps([{"record_id": "x1", "prompt": "only prompt"}]).encode()
    r = _commit(client, headers, dataset_id, content)
    assert r.status_code == 422  # zero valid rows


def test_partial_invalid_rows_are_skipped(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    rows = [
        {"record_id": "ok1", "prompt": "p", "response": "r"},
        {"record_id": "bad1", "prompt": "", "response": "r"},  # missing prompt -> invalid
        {"record_id": "ok2", "prompt": "p2", "response": "r2"},
    ]
    r = _commit(client, headers, dataset_id, json.dumps(rows).encode())
    assert r.status_code == 201
    assert r.json()["record_count"] == 2


def test_duplicate_detection(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    rows = [
        {"record_id": "d1", "prompt": "same prompt", "response": "same response"},
        {"record_id": "d1", "prompt": "different prompt", "response": "different response"},  # dup id
        {"record_id": "d3", "prompt": "same prompt", "response": "same response"},            # dup content
    ]
    r = client.post(
        f"/api/datasets/{dataset_id}/upload/preview",
        headers=headers,
        files={"file": ("dup.json", json.dumps(rows).encode(), "application/json")},
    )
    assert r.status_code == 200
    report = r.json()
    assert report["duplicate_count"] >= 2
    assert any("Duplicate record_id" in d["reason"] for d in report["duplicate_records"])


def test_preview_does_not_commit(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    rows = [{"record_id": "pv1", "prompt": "p", "response": "r"}]
    r = client.post(
        f"/api/datasets/{dataset_id}/upload/preview",
        headers=headers,
        files={"file": ("pv.json", json.dumps(rows).encode(), "application/json")},
    )
    assert r.status_code == 200
    assert r.json()["valid_count"] == 1
    r = client.get(f"/api/datasets/{dataset_id}/records", headers=headers)
    assert r.json()["total"] == 2  # unchanged


def test_dataset_versioning(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    rows2 = [{"record_id": "v2r1", "prompt": "p", "response": "r"}]
    r = _commit(client, headers, dataset_id, json.dumps(rows2).encode())
    assert r.json()["version_number"] == 2

    r = client.get(f"/api/datasets/{dataset_id}/versions", headers=headers)
    versions = r.json()
    assert [v["version_number"] for v in versions] == [2, 1]


def test_oversized_file_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    big = b"x" * (26 * 1024 * 1024)
    r = _commit(client, headers, dataset_id, big)
    assert r.status_code in (413, 422)


def test_unsupported_extension_rejected(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    r = _commit(client, headers, dataset_id, b"hello", "malware.exe")
    assert r.status_code == 415


def test_missing_value_reporting(client, db, auth_headers):
    headers, _ = auth_headers
    dataset_id, _v = make_dataset(client, headers)
    rows = [{"record_id": "m1", "prompt": "p", "response": "r"}]  # no reference_answer
    r = client.post(
        f"/api/datasets/{dataset_id}/upload/preview",
        headers=headers,
        files={"file": ("m.json", json.dumps(rows).encode(), "application/json")},
    )
    report = r.json()
    assert report["missing_value_count"] == 1


def test_delete_dataset_blocked_when_used_by_runs(client, db, auth_headers):
    """Datasets referenced by evaluation runs must stay (traceability)."""
    from tests.conftest import make_run, make_rubric
    headers, _ = auth_headers
    dataset_id, _ = make_dataset(client, headers)
    rubric_id = make_rubric(client, headers)
    make_run(client, headers, dataset_id, rubric_id)
    r = client.delete(f"/api/datasets/{dataset_id}", headers=headers)
    assert r.status_code == 409
