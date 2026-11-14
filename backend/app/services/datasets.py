"""Dataset import: CSV / JSON / JSONL parsing, validation, normalization, versioning.

Uploaded content is treated strictly as data. Nothing in a file is ever executed
or interpreted as system instructions.
"""
import csv
import hashlib
import io
import json
import logging
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset, DatasetRecord, DatasetVersion

logger = logging.getLogger("evalforge.datasets")

CANONICAL_FIELDS = ["prompt", "response", "reference_answer", "reference_sources", "metadata"]
REQUIRED_FIELDS = ["prompt", "response"]
ALLOWED_EXTENSIONS = {".csv", ".json", ".jsonl", ".ndjson"}


class DatasetImportError(Exception):
    """Raised when a file cannot be parsed at all."""


def detect_format(filename: str, content: bytes) -> str:
    lower = filename.lower()
    for ext in ALLOWED_EXTENSIONS:
        if lower.endswith(ext):
            return "csv" if ext == ".csv" else ("jsonl" if ext in (".jsonl", ".ndjson") else "json")
    head = content[:512].lstrip()
    if head.startswith(b"[") or head.startswith(b"{"):
        # try to distinguish jsonl
        try:
            text = content.decode("utf-8-sig")
            stripped = text.strip()
            if stripped.startswith("["):
                return "json"
            first = stripped.splitlines()[0].strip()
            json.loads(first)
            return "jsonl"
        except Exception:
            return "json"
    return "csv"


def parse_file(content: bytes, fmt: str) -> list[dict[str, Any]]:
    """Parse file bytes into a list of raw row dicts. Raises DatasetImportError."""
    if len(content) == 0:
        raise DatasetImportError("File is empty.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise DatasetImportError(f"File exceeds the {settings.max_upload_mb} MB upload limit.")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
            logger.warning("File decoded as latin-1 fallback (not valid UTF-8).")
        except UnicodeDecodeError as exc:
            raise DatasetImportError("File is not valid UTF-8 text.") from exc

    try:
        if fmt == "csv":
            df = pd.read_csv(
                io.StringIO(text),
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                on_bad_lines="error",
            )
            rows: list[dict[str, Any]] = df.where(pd.notna(df), None).to_dict(orient="records")
            # normalize None
            rows = [{k: (None if (isinstance(v, float) and pd.isna(v)) or v == "" else v) for k, v in r.items()} for r in rows]
            return rows
        if fmt == "json":
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("records", "data", "items", "examples"):
                    if isinstance(data.get(key), list):
                        return data[key]
                return [data]
            raise DatasetImportError("JSON must be an array of records or an object with a records array.")
        if fmt == "jsonl":
            rows = []
            for line_no, line in enumerate(text.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DatasetImportError(f"Invalid JSON on line {line_no}: {exc.msg}") from exc
                if not isinstance(obj, dict):
                    raise DatasetImportError(f"Line {line_no} is not a JSON object.")
                rows.append(obj)
            return rows
    except DatasetImportError:
        raise
    except Exception as exc:
        raise DatasetImportError(f"Could not parse file: {exc}") from exc
    raise DatasetImportError(f"Unsupported format: {fmt}")


def _ensure_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else [value]
            except json.JSONDecodeError:
                pass
        if ";" in text:
            return [s.strip() for s in text.split(";") if s.strip()]
        return [text]
    return [value]


def _as_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": value}
        except json.JSONDecodeError:
            return {"value": value}
    return {}


def normalize_rows(
    rows: list[dict[str, Any]],
    column_mapping: dict[str, str] | None = None,
    record_id_column: str | None = None,
    expected_label_column: str | None = None,
) -> list[dict[str, Any]]:
    """Apply column mapping and normalize rows to the canonical record schema."""
    mapping = column_mapping or {}
    normalized: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            normalized.append({
                "row": i, "record_id": None, "prompt": None, "response": None,
                "reference_answer": None, "reference_sources": [], "expected_label": None,
                "gold_explanation": None, "metadata": {"import_row": i},
                "errors": ["Row is not an object."],
            })
            continue

        def pick(field: str) -> Any:
            col = mapping.get(field, field)
            return row.get(col, None) if col in row else row.get(field, None)

        prompt = pick("prompt")
        response = pick("response")
        errors: list[str] = []
        if prompt is None or str(prompt).strip() == "":
            errors.append("Missing required field 'prompt'.")
        if response is None or str(response).strip() == "":
            errors.append("Missing required field 'response'.")

        record_id = pick("record_id") if record_id_column is None else row.get(record_id_column)
        if record_id is None or str(record_id).strip() == "":
            record_id = f"row_{i + 1}"
        record_id = str(record_id).strip()

        expected_label = None
        if expected_label_column:
            expected_label = row.get(expected_label_column)
        else:
            expected_label = pick("expected_label")

        normalized.append({
            "row": i,
            "record_id": record_id,
            "prompt": None if prompt is None else str(prompt),
            "response": None if response is None else str(response),
            "reference_answer": None if pick("reference_answer") in (None, "") else str(pick("reference_answer")),
            "reference_sources": _ensure_list(pick("reference_sources")),
            "expected_label": str(expected_label).strip() if expected_label not in (None, "") else None,
            "gold_explanation": None if pick("gold_explanation") in (None, "") else str(pick("gold_explanation")),
            "metadata": _as_metadata(pick("metadata")),
            "errors": errors,
        })
    return normalized


def analyze_import(
    rows: list[dict[str, Any]],
    column_mapping: dict[str, str] | None = None,
    record_id_column: str | None = None,
    expected_label_column: str | None = None,
) -> dict[str, Any]:
    """Full validation report over parsed rows (without writing anything)."""
    normalized = normalize_rows(rows, column_mapping, record_id_column, expected_label_column)

    detected_columns: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            for key in row.keys():
                if key not in detected_columns:
                    detected_columns.append(key)

    invalid_records = [r for r in normalized if r["errors"]]
    missing_value_count = sum(1 for r in normalized if (r["reference_answer"] is None))

    seen_ids: dict[str, int] = {}
    seen_content: dict[tuple[str, str], int] = {}
    duplicate_records: list[dict[str, Any]] = []
    for r in normalized:
        rid = r["record_id"]
        if rid in seen_ids:
            duplicate_records.append({"row": r["row"], "record_id": rid, "reason": f"Duplicate record_id (first seen row {seen_ids[rid]})"})
        else:
            seen_ids[rid] = r["row"]
        content_key = ((r["prompt"] or ""), (r["response"] or ""))
        if content_key in seen_content:
            dup = {"row": r["row"], "record_id": rid, "reason": f"Same prompt+response as row {seen_content[content_key]}"}
            if not any(d["row"] == r["row"] for d in duplicate_records):
                duplicate_records.append(dup)
        else:
            seen_content[content_key] = r["row"]

    preview: list[dict[str, Any]] = []
    for r in normalized[:20]:
        preview.append({
            "record_id": r["record_id"],
            "prompt": (r["prompt"] or "")[:300],
            "response": (r["response"] or "")[:300],
            "reference_answer": r["reference_answer"],
            "expected_label": r["expected_label"],
            "metadata": r["metadata"],
            "errors": r["errors"],
        })

    warnings: list[str] = []
    if len(normalized) > settings.max_records_per_dataset:
        warnings.append(f"Dataset has {len(normalized)} records; limit is {settings.max_records_per_dataset}.")
    mapping = column_mapping or {}
    missing_fields = [f for f in REQUIRED_FIELDS if mapping.get(f, f) not in detected_columns]
    if duplicate_records:
        warnings.append(f"{len(duplicate_records)} duplicate rows detected; duplicates are skipped on commit.")

    return {
        "total_rows": len(normalized),
        "valid_count": len(normalized) - len(invalid_records),
        "invalid_count": len(invalid_records),
        "duplicate_count": len(duplicate_records),
        "missing_value_count": missing_value_count,
        "detected_columns": detected_columns,
        "missing_required_fields": missing_fields,
        "invalid_records": [
            {"row": r["row"], "record_id": r["record_id"], "errors": r["errors"]}
            for r in invalid_records[:100]
        ],
        "duplicate_records": duplicate_records[:100],
        "warnings": warnings,
        "preview": preview,
        "_normalized": normalized,
    }


def commit_import(
    db: Session,
    dataset: Dataset,
    rows: list[dict[str, Any]],
    *,
    column_mapping: dict[str, str] | None = None,
    record_id_column: str | None = None,
    expected_label_column: str | None = None,
    notes: str | None = None,
    fmt: str = "json",
    source_filename: str | None = None,
) -> tuple[DatasetVersion, dict[str, Any]]:
    """Validate and persist a new immutable dataset version."""
    report = analyze_import(rows, column_mapping, record_id_column, expected_label_column)
    if report["valid_count"] == 0:
        raise ValueError("No valid records to import.")

    version_number = (db.scalar(select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset.id)) or 0) + 1
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=version_number,
        record_count=report["valid_count"],
        content_hash=hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
        notes=notes,
    )
    db.add(version)
    db.flush()

    seen: set[str] = set()
    inserted = 0
    for r in report["_normalized"]:
        if r["errors"] or r["record_id"] in seen:
            continue
        seen.add(r["record_id"])
        db.add(DatasetRecord(
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            record_id=r["record_id"],
            prompt=r["prompt"],
            response=r["response"],
            reference_answer=r["reference_answer"],
            reference_sources=r["reference_sources"],
            expected_label=r["expected_label"],
            gold_explanation=r["gold_explanation"],
            record_metadata=r["metadata"],
        ))
        inserted += 1

    dataset.format = fmt
    if source_filename:
        dataset.source_filename = source_filename
    dataset.current_version = version_number
    db.commit()
    db.refresh(version)

    report.pop("_normalized")
    return version, report


def list_records(db: Session, dataset_id: int, version_id: int | None, page: int, page_size: int) -> tuple[list[DatasetRecord], int]:
    stmt = select(DatasetRecord).where(DatasetRecord.dataset_id == dataset_id)
    if version_id:
        stmt = stmt.where(DatasetRecord.dataset_version_id == version_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(DatasetRecord.id).offset((page - 1) * page_size).limit(page_size)).all()
    return list(items), int(total)
