"""Data collection: manual record creation, bulk paste, editing, export.

Integrity rules:
- records referenced by tasks cannot be edited or deleted (traceability)
- manual additions append to the dataset's current version and are audited
- custom fields are validated against the dataset's field definitions
- exports are permission-checked at the router and audited
"""
import csv
import io
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetRecord
from app.models.task import Task
from app.models.user import User

CUSTOM_FIELD_TYPES = {"text", "number", "select", "url"}


def validate_custom_field_definitions(definitions: Any) -> list[str]:
    errors = []
    if not definitions:
        return errors
    if not isinstance(definitions, list):
        return ["custom_field_definitions must be a list."]
    seen = set()
    for i, d in enumerate(definitions):
        if not isinstance(d, dict) or not d.get("key"):
            errors.append(f"custom_field_definitions[{i}]: 'key' is required.")
            continue
        key = d["key"]
        if key in seen:
            errors.append(f"custom_field_definitions[{i}]: duplicate key '{key}'.")
        seen.add(key)
        if d.get("type") not in CUSTOM_FIELD_TYPES:
            errors.append(f"custom_field_definitions[{i}]: type must be one of {sorted(CUSTOM_FIELD_TYPES)}.")
        if d.get("type") == "select" and not isinstance(d.get("options"), list):
            errors.append(f"custom_field_definitions[{i}]: select fields need an options list.")
    return errors


def validate_custom_values(definitions: list | None, values: dict | None) -> list[str]:
    errors: list[str] = []
    values = values or {}
    defs = {d["key"]: d for d in (definitions or []) if isinstance(d, dict) and d.get("key")}
    for key, val in values.items():
        d = defs.get(key)
        if d is None:
            errors.append(f"Unknown custom field '{key}' (not defined on this dataset).")
            continue
        if d.get("type") == "number":
            try:
                float(val)
            except (TypeError, ValueError):
                errors.append(f"Custom field '{key}' must be a number.")
        if d.get("type") == "select" and val not in (d.get("options") or []):
            errors.append(f"Custom field '{key}' must be one of {d.get('options')}.")
    for key, d in defs.items():
        if d.get("required") and (values.get(key) in (None, "")):
            errors.append(f"Custom field '{key}' is required.")
    return errors


def _record_from_payload(dataset: Dataset, payload: dict, version_id: int, record_id: str) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=dataset.id,
        dataset_version_id=version_id,
        record_id=record_id,
        prompt=str(payload["prompt"]),
        response=str(payload["response"]),
        reference_answer=payload.get("reference_answer"),
        reference_sources=payload.get("reference_sources") or [],
        expected_label=payload.get("expected_label"),
        gold_explanation=payload.get("gold_explanation"),
        record_metadata=payload.get("metadata") or {},
        supporting_evidence=payload.get("supporting_evidence"),
        source_url=payload.get("source_url"),
        content_category=payload.get("content_category"),
        difficulty_level=payload.get("difficulty_level"),
        language=payload.get("language") or "en",
        instructions=payload.get("instructions"),
        collection_status=payload.get("collection_status") or "collected",
        custom_fields=payload.get("custom_fields") or {},
    )


def create_manual_record(db: Session, dataset: Dataset, payload: dict, user: User) -> tuple[DatasetRecord | None, list[str]]:
    """Append one manually collected record to the current version."""
    errors: list[str] = []
    prompt = (payload.get("prompt") or "").strip()
    response = (payload.get("response") or "").strip()
    if not prompt:
        errors.append("'prompt' is required.")
    if not response:
        errors.append("'response' is required.")
    record_id = (payload.get("record_id") or "").strip()
    if not record_id:
        # generate a sequential id based on existing records
        n = (db.scalar(select(func.count()).select_from(DatasetRecord).where(DatasetRecord.dataset_id == dataset.id)) or 0) + 1
        record_id = f"manual_{n:05d}"
    errors.extend(validate_custom_values(dataset.custom_field_definitions, payload.get("custom_fields")))
    if errors:
        return None, errors

    duplicate = db.scalar(select(DatasetRecord.id).where(
        DatasetRecord.dataset_id == dataset.id, DatasetRecord.record_id == record_id))
    if duplicate:
        return None, [f"A record with id '{record_id}' already exists in this dataset."]

    record = _record_from_payload(dataset, payload, dataset.current_version, record_id)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, []


def bulk_add_records(db: Session, dataset: Dataset, rows: list[dict], user: User) -> dict:
    """Paste-import rows into the current version with full validation report."""
    added, rejected = [], []
    seen_ids: set[str] = set()
    for i, payload in enumerate(rows):
        errors: list[str] = []
        prompt = (payload.get("prompt") or "").strip()
        response = (payload.get("response") or "").strip()
        if not prompt:
            errors.append("'prompt' is required.")
        if not response:
            errors.append("'response' is required.")
        record_id = (payload.get("record_id") or "").strip() or f"manual_{i + 1:05d}"
        if record_id in seen_ids:
            errors.append(f"Duplicate record_id '{record_id}' in this batch.")
        seen_ids.add(record_id)
        errors.extend(validate_custom_values(dataset.custom_field_definitions, payload.get("custom_fields")))
        if errors:
            rejected.append({"row": i, "record_id": record_id, "errors": errors})
            continue
        duplicate = db.scalar(select(DatasetRecord.id).where(
            DatasetRecord.dataset_id == dataset.id, DatasetRecord.record_id == record_id))
        if duplicate:
            rejected.append({"row": i, "record_id": record_id, "errors": [f"record_id '{record_id}' already exists in the dataset."]})
            continue
        added.append(_record_from_payload(dataset, payload, dataset.current_version, record_id))
    for r in added:
        db.add(r)
    db.commit()
    return {"added": len(added), "rejected": rejected, "total": len(rows)}


def record_editable(db: Session, record: DatasetRecord) -> bool:
    """Records referenced by tasks are frozen for traceability."""
    used = db.scalar(select(func.count()).select_from(Task).where(Task.dataset_record_id == record.id)) or 0
    return used == 0


def apply_record_edit(record: DatasetRecord, payload: dict, dataset: Dataset) -> list[str]:
    errors: list[str] = []
    if "prompt" in payload and not (payload["prompt"] or "").strip():
        errors.append("'prompt' cannot be empty.")
    if "response" in payload and not (payload["response"] or "").strip():
        errors.append("'response' cannot be empty.")
    errors.extend(validate_custom_values(dataset.custom_field_definitions, payload.get("custom_fields", record.custom_fields)))
    if errors:
        return errors
    for field in ("prompt", "response", "reference_answer", "expected_label", "gold_explanation",
                  "supporting_evidence", "source_url", "content_category", "difficulty_level",
                  "language", "instructions", "collection_status"):
        if field in payload:
            setattr(record, field, payload[field])
    if "reference_sources" in payload:
        record.reference_sources = payload["reference_sources"] or []
    if "metadata" in payload:
        record.record_metadata = payload["metadata"] or {}
    if "custom_fields" in payload:
        record.custom_fields = payload["custom_fields"] or {}
    return []


def export_dataset(db: Session, dataset: Dataset, fmt: str) -> tuple[str, str, str]:
    """Returns (content, media_type, suggested_filename)."""
    records = db.scalars(
        select(DatasetRecord).where(DatasetRecord.dataset_id == dataset.id).order_by(DatasetRecord.id)
    ).all()
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["record_id", "prompt", "response", "reference_answer", "reference_sources",
                         "expected_label", "supporting_evidence", "source_url", "content_category",
                         "difficulty_level", "language", "collection_status"])
        for r in records:
            writer.writerow([
                r.record_id, r.prompt, r.response, r.reference_answer or "",
                json.dumps(r.reference_sources or []), r.expected_label or "",
                r.supporting_evidence or "", r.source_url or "", r.content_category or "",
                r.difficulty_level or "", r.language or "en", r.collection_status or "collected",
            ])
        return buf.getvalue(), "text/csv", f"{dataset.name}.csv"
    payload = {
        "dataset": {"id": dataset.id, "name": dataset.name, "current_version": dataset.current_version,
                    "status": dataset.status, "record_count": len(records)},
        "records": [
            {
                "record_id": r.record_id, "prompt": r.prompt, "response": r.response,
                "reference_answer": r.reference_answer, "reference_sources": r.reference_sources or [],
                "expected_label": r.expected_label, "supporting_evidence": r.supporting_evidence,
                "source_url": r.source_url, "content_category": r.content_category,
                "difficulty_level": r.difficulty_level, "language": r.language,
                "instructions": r.instructions, "collection_status": r.collection_status,
                "custom_fields": r.custom_fields or {}, "metadata": r.record_metadata or {},
            }
            for r in records
        ],
    }
    return json.dumps(payload, indent=2, default=str), "application/json", f"{dataset.name}.json"
