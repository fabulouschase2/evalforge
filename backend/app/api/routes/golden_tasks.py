"""Golden task management, quality reports and alerts.

Permissions: project admins manage golden tasks and config for their projects;
quality leads (senior_reviewer/super_admin) read reports and resolve alerts.
Tester-facing surfaces never include golden identity or reference answers.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.golden import (
    GoldenTask, GoldenTaskResult, GoldenTaskVersion, QualityAlert,
    SCORING_METHODS, DIFFICULTIES,
)
from app.models.project import Project
from app.models.user import UserRole
from app.services import access as acl
from app.services import golden as gs
from app.services.audit import log_action

router = APIRouter(prefix="/api/golden-tasks", tags=["golden-tasks"])
quality_router = APIRouter(prefix="/api/quality/golden", tags=["golden-tasks"])


def _require_project_admin(db: DbSession, user, project_id: int) -> Project:
    try:
        project = acl.require_project(db, user, project_id)
        acl.require_project_admin(db, user, project)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return project


def _require_quality_lead(user) -> None:
    if user.role not in UserRole.PLATFORM_WIDE:
        raise HTTPException(status_code=403, detail="Quality lead access required.")


def _golden_out(g: GoldenTask, include_reference: bool = True) -> dict:
    data = {
        "id": g.id,
        "project_id": g.project_id,
        "source_record_id": g.source_record_id,
        "title": g.title,
        "instructions": g.instructions,
        "payload": g.payload,
        "scoring_method": g.scoring_method,
        "scoring_config": g.scoring_config or {},
        "difficulty": g.difficulty,
        "version": g.version,
        "is_active": g.is_active,
        "created_by": g.created_by,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "has_variations": bool(g.accepted_variations),
    }
    if include_reference:
        data["reference_answer"] = g.reference_answer
        data["accepted_variations"] = g.accepted_variations or []
        data["explanation"] = g.explanation
    return data


# ---------------------------------------------------------------------------
# CRUD (staff)
# ---------------------------------------------------------------------------

@router.get("")
def list_golden_tasks(db: DbSession, user: AdminPM, project_id: int | None = None):
    stmt = select(GoldenTask)
    ids = acl.visible_project_ids(db, user)
    if ids is not None:
        stmt = stmt.where(GoldenTask.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(GoldenTask.project_id == project_id)
    rows = db.scalars(stmt.order_by(GoldenTask.created_at.desc())).all()
    return [_golden_out(g) for g in rows]


@router.post("", status_code=201)
def create_golden_task(payload: dict, db: DbSession, user: AdminPM, request: Request):
    project = _require_project_admin(db, user, int(payload.get("project_id", 0)))
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is required.")
    method = payload.get("scoring_method") or "exact"
    if method not in SCORING_METHODS:
        raise HTTPException(status_code=422, detail=f"Unknown scoring method; allowed: {SCORING_METHODS}")
    difficulty = payload.get("difficulty") or "medium"
    if difficulty not in DIFFICULTIES:
        raise HTTPException(status_code=422, detail=f"Unknown difficulty; allowed: {DIFFICULTIES}")
    reference = payload.get("reference_answer")
    if not isinstance(reference, dict) or not reference:
        raise HTTPException(status_code=422, detail="reference_answer object is required (e.g. {\"answer\": \"...\"}).")

    golden = GoldenTask(
        project_id=project.id,
        source_record_id=payload.get("source_record_id"),
        title=title,
        instructions=payload.get("instructions"),
        payload=payload.get("payload") or {},
        reference_answer=reference,
        accepted_variations=payload.get("accepted_variations") or [],
        scoring_method=method,
        scoring_config=payload.get("scoring_config") or {},
        explanation=payload.get("explanation"),
        difficulty=difficulty,
        version=1,
        created_by=user.id,
    )
    db.add(golden)
    db.flush()
    db.add(GoldenTaskVersion(
        golden_task_id=golden.id, version=1,
        reference_answer=reference,
        accepted_variations=golden.accepted_variations,
        scoring_method=method, scoring_config=golden.scoring_config,
        changed_by=user.id, change_note="initial reference",
    ))
    db.commit()
    db.refresh(golden)
    log_action(db, user_id=user.id, action="golden.create", entity_type="golden_task",
               entity_id=golden.id, details={"title": title, "method": method}, request=request)
    return _golden_out(golden)


@router.post("/import", status_code=201)
def import_golden_tasks(payload: dict, db: DbSession, user: AdminPM, request: Request):
    """Bulk import: {"project_id": N, "tasks": [{title, reference_answer, ...}]}"""
    project = _require_project_admin(db, user, int(payload.get("project_id", 0)))
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise HTTPException(status_code=422, detail="tasks list is required.")
    created, errors = [], []
    for i, row in enumerate(tasks):
        title = (row.get("title") or "").strip()
        reference = row.get("reference_answer")
        method = row.get("scoring_method") or "exact"
        if not title or not isinstance(reference, dict):
            errors.append({"row": i, "error": "title and reference_answer are required."})
            continue
        if method not in SCORING_METHODS:
            errors.append({"row": i, "error": f"unknown scoring_method '{method}'"})
            continue
        golden = GoldenTask(
            project_id=project.id,
            title=title[:255],
            instructions=row.get("instructions"),
            payload=row.get("payload") or {},
            reference_answer=reference,
            accepted_variations=row.get("accepted_variations") or [],
            scoring_method=method,
            scoring_config=row.get("scoring_config") or {},
            explanation=row.get("explanation"),
            difficulty=row.get("difficulty") if row.get("difficulty") in DIFFICULTIES else "medium",
            version=1,
            created_by=user.id,
        )
        db.add(golden)
        db.flush()
        db.add(GoldenTaskVersion(
            golden_task_id=golden.id, version=1, reference_answer=reference,
            accepted_variations=golden.accepted_variations, scoring_method=method,
            scoring_config=golden.scoring_config, changed_by=user.id,
            change_note="imported",
        ))
        created.append(golden.id)
    db.commit()
    log_action(db, user_id=user.id, action="golden.import", entity_type="project",
               entity_id=project.id,
               details={"imported": len(created), "errors": len(errors)}, request=request)
    return {"imported": len(created), "ids": created, "errors": errors}


@router.put("/{golden_id}")
def update_golden_task(golden_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    golden = db.get(GoldenTask, golden_id)
    if golden is None:
        raise HTTPException(status_code=404, detail="Golden task not found.")
    _require_project_admin(db, user, golden.project_id)

    reference = payload.get("reference_answer")
    variations = payload.get("accepted_variations")
    method = payload.get("scoring_method", golden.scoring_method)
    config = payload.get("scoring_config", golden.scoring_config)
    version_bumped = False
    if reference is not None or variations is not None or method != golden.scoring_method:
        # reference answers are immutable: a change creates a NEW version
        new_version = golden.version + 1
        golden.version = new_version
        if reference is not None:
            golden.reference_answer = reference
        if variations is not None:
            golden.accepted_variations = variations
        golden.scoring_method = method if method in SCORING_METHODS else golden.scoring_method
        golden.scoring_config = config
        db.add(GoldenTaskVersion(
            golden_task_id=golden.id, version=new_version,
            reference_answer=golden.reference_answer,
            accepted_variations=golden.accepted_variations,
            scoring_method=golden.scoring_method, scoring_config=golden.scoring_config,
            changed_by=user.id, change_note=payload.get("change_note"),
        ))
        version_bumped = True
    for field in ("title", "instructions", "explanation", "payload"):
        if field in payload and payload[field] is not None:
            setattr(golden, field, payload[field])
    if payload.get("difficulty") in DIFFICULTIES:
        golden.difficulty = payload["difficulty"]
    if isinstance(payload.get("is_active"), bool):
        golden.is_active = payload["is_active"]
    db.commit()
    db.refresh(golden)
    log_action(db, user_id=user.id, action="golden.update", entity_type="golden_task",
               entity_id=golden.id, details={"version_bumped": version_bumped}, request=request)
    return _golden_out(golden)


@router.get("/{golden_id}/versions")
def golden_versions(golden_id: int, db: DbSession, user: AdminPM):
    golden = db.get(GoldenTask, golden_id)
    if golden is None:
        raise HTTPException(status_code=404, detail="Golden task not found.")
    _require_project_admin(db, user, golden.project_id)
    rows = db.scalars(
        select(GoldenTaskVersion).where(GoldenTaskVersion.golden_task_id == golden_id)
        .order_by(GoldenTaskVersion.version)
    ).all()
    return [
        {
            "version": v.version, "reference_answer": v.reference_answer,
            "accepted_variations": v.accepted_variations or [],
            "scoring_method": v.scoring_method, "scoring_config": v.scoring_config or {},
            "change_note": v.change_note, "changed_by": v.changed_by,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in rows
    ]


@router.post("/preview-score")
def preview_score(payload: dict, db: DbSession, user: AdminPM):
    """Score a sample answer against a golden task (for building tasks)."""
    golden = db.get(GoldenTask, int(payload.get("golden_id", 0)))
    if golden is None:
        raise HTTPException(status_code=404, detail="Golden task not found.")
    _require_project_admin(db, user, golden.project_id)
    score, passed, reasons = gs.score_answer(golden, payload.get("answer"))
    return {"score": score, "passed": passed, "failure_reasons": reasons}


# ---------------------------------------------------------------------------
# Project golden config
# ---------------------------------------------------------------------------

@router.get("/config/{project_id}")
def get_golden_config(project_id: int, db: DbSession, user: AdminPM):
    project = _require_project_admin(db, user, project_id)
    return gs.project_golden_config(project)


@router.put("/config/{project_id}")
def set_golden_config(project_id: int, payload: dict, db: DbSession, user: AdminPM, request: Request):
    project = _require_project_admin(db, user, project_id)
    current = gs.project_golden_config(project)
    for key in ("percentage", "fixed_count", "min_spacing", "difficulty_mix",
                "pass_score", "min_attempts_for_accuracy", "accuracy_alert_below",
                "consecutive_failures_alert", "sudden_decline_drop", "min_seconds_per_task"):
        if key in payload:
            current[key] = payload[key]
    project.golden_task_config = current
    db.commit()
    log_action(db, user_id=user.id, action="golden.config_update", entity_type="project",
               entity_id=project_id, details={"config": current}, request=request)
    return current


# ---------------------------------------------------------------------------
# Quality reports + alerts
# ---------------------------------------------------------------------------

@quality_router.get("/report")
def golden_report(db: DbSession, user: CurrentUser, project_id: int | None = None):
    _require_quality_lead(user)
    stmt = select(GoldenTaskResult)
    ids = acl.visible_project_ids(db, user)
    if ids is not None:
        stmt = stmt.where(GoldenTaskResult.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(GoldenTaskResult.project_id == project_id)
    results = db.scalars(stmt.order_by(GoldenTaskResult.scored_at)).all()

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_difficulty: dict[str, dict] = {}
    difficulties = {g.id: g.difficulty for g in db.scalars(select(GoldenTask)).all()}
    for r in results:
        d = difficulties.get(r.golden_task_id, "unknown")
        bucket = by_difficulty.setdefault(d, {"attempts": 0, "passed": 0})
        bucket["attempts"] += 1
        bucket["passed"] += 1 if r.passed else 0
    for d, bucket in by_difficulty.items():
        bucket["accuracy"] = round(bucket["passed"] / bucket["attempts"], 4) if bucket["attempts"] else None

    by_worker: dict[int, dict] = {}
    for r in results:
        w = by_worker.setdefault(r.worker_id, {"attempts": 0, "passed": 0})
        w["attempts"] += 1
        w["passed"] += 1 if r.passed else 0
    workers_out = []
    for worker_id, w in by_worker.items():
        workers_out.append({
            "worker_id": worker_id,
            "attempts": w["attempts"],
            "passed": w["passed"],
            "accuracy": round(w["passed"] / w["attempts"], 4) if w["attempts"] else None,
        })
    workers_out.sort(key=lambda x: -(x["accuracy"] or 0))

    return {
        "attempts": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 4) if total else None,
        "insufficient_reason": "No golden task attempts recorded yet." if not total else None,
        "by_difficulty": by_difficulty,
        "by_worker": workers_out[:50],
        "calculation": {
            "method": "passed / attempts over stored golden_task_results rows",
            "source": "golden_task_results",
            "golden_task_versions": "result pinned to golden_task_version at score time",
            "computed_at": None,  # filled below
        },
        "note": "Accuracy covers only golden (known-answer) tasks; it must not be "
                "presented as overall task quality.",
    }


@quality_router.get("/alerts")
def list_alerts(db: DbSession, user: CurrentUser, project_id: int | None = None,
                include_resolved: bool = False):
    _require_quality_lead(user)
    stmt = select(QualityAlert)
    ids = acl.visible_project_ids(db, user)
    if ids is not None:
        stmt = stmt.where(QualityAlert.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(QualityAlert.project_id == project_id)
    if not include_resolved:
        stmt = stmt.where(QualityAlert.resolved.is_(False))
    rows = db.scalars(stmt.order_by(QualityAlert.created_at.desc())).all()
    return [
        {
            "id": a.id, "project_id": a.project_id, "worker_id": a.worker_id,
            "alert_type": a.alert_type, "severity": a.severity, "message": a.message,
            "evidence": a.evidence or {}, "resolved": a.resolved,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@quality_router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, payload: dict, db: DbSession, user: CurrentUser, request: Request):
    _require_quality_lead(user)
    alert = db.get(QualityAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.resolved = True
    alert.resolved_by = user.id
    alert.resolution_note = (payload.get("note") or "").strip() or None
    from app.models.user import utcnow
    alert.resolved_at = utcnow()
    db.commit()
    log_action(db, user_id=user.id, action="quality.alert_resolve", entity_type="quality_alert",
               entity_id=alert.id, request=request)
    return {"ok": True}


@quality_router.get("/worker/{worker_id}")
def worker_golden_history(worker_id: int, db: DbSession, user: CurrentUser):
    """Per-worker golden history for quality leads."""
    _require_quality_lead(user)
    rows = db.scalars(
        select(GoldenTaskResult).where(GoldenTaskResult.worker_id == worker_id)
        .order_by(GoldenTaskResult.scored_at.desc())
    ).all()
    return [
        {
            "id": r.id, "golden_task_id": r.golden_task_id, "project_id": r.project_id,
            "task_id": r.task_id, "attempt_version": r.golden_task_version,
            "scoring_method": r.scoring_method, "score": r.score, "passed": r.passed,
            "failure_reasons": r.failure_reasons or [],
            "time_spent_seconds": r.time_spent_seconds,
            "scored_at": r.scored_at.isoformat() if r.scored_at else None,
        }
        for r in rows
    ]
