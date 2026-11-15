"""Analytics routes: overview, metrics, agreement, confusion matrix, admin overview.

V3 additions: platform rollups (staff) and CSV/JSON exports of quality
analytics. Every number is computed from stored records; unavailable metrics
carry an explicit reason instead of a fabricated value.

V3.1: aggregate endpoints are staff-only; run-scoped metrics are visible to
anyone who can see the run's dataset project.
"""
from fastapi import APIRouter, HTTPException, Query, Response, Request
from sqlalchemy import func, select

from app.core.security import AdminPM, CurrentUser, DbSession
from app.models.client import Deliverable, ProjectRequest
from app.models.dataset import Dataset, DatasetRecord
from app.models.evaluation import EvaluationRun
from app.models.golden import GoldenTaskResult, QualityAlert
from app.models.organization import Organization
from app.models.project import Project
from app.models.qualification import QualificationAttempt
from app.models.submission import Submission
from app.models.task import Task
from app.models.user import User, UserRole
from app.services import access as acl
from app.services import analytics as an
from app.services.audit import log_action

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _require_analytics_access(db: DbSession, user, run_id: int | None) -> None:
    """Global aggregates are staff-only; run-scoped metrics follow run visibility."""
    if user.role in UserRole.STAFF or user.role in UserRole.PLATFORM_WIDE:
        return
    if run_id is None:
        raise HTTPException(status_code=403, detail="Staff access required for global analytics.")
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    dataset = db.get(Dataset, run.dataset_id)
    if dataset is None or dataset.project_id is None:
        raise HTTPException(status_code=403, detail="Staff access required for these metrics.")
    try:
        acl.require_project(db, user, dataset.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/overview")
def overview(db: DbSession, user: AdminPM):
    """Dashboard aggregates — staff only (V3.1: was open to any authenticated user)."""
    return an.overview(db)


@router.get("/admin-overview")
def admin_overview(db: DbSession, user: AdminPM, days: int = Query(14, ge=1, le=90)):
    return an.admin_overview(db, days)


@router.get("/platform")
def platform_analytics(db: DbSession, user: AdminPM):
    """Unified platform rollups (staff only)."""
    def count(model, *conditions):
        stmt = select(func.count()).select_from(model)
        for c in conditions:
            stmt = stmt.where(c)
        return db.scalar(stmt) or 0

    orgs = count(Organization)
    projects = count(Project)
    projects_active = count(Project, Project.status == "active")
    datasets = count(Dataset)
    records = count(DatasetRecord)
    tasks_total = count(Task)
    tasks_approved = count(Task, Task.status == "approved")
    submissions_total = count(Submission)
    submissions_approved = count(Submission, Submission.status == "approved")
    submissions_rejected = count(Submission, Submission.status == "rejected")
    workers = count(User, User.role == UserRole.TESTER, User.is_active.is_(True))
    reviewers = count(User, User.role.in_([UserRole.REVIEWER, UserRole.SENIOR_REVIEWER]),
                      User.is_active.is_(True))
    client_users = count(User, User.role.in_(UserRole.CLIENT_ROLES), User.is_active.is_(True))
    requests_pending = count(ProjectRequest, ProjectRequest.status.in_(
        ["submitted", "under_review", "more_info_required"]))
    deliverables = count(Deliverable)
    golden_attempts = count(GoldenTaskResult)
    golden_passed = count(GoldenTaskResult, GoldenTaskResult.passed.is_(True))
    open_alerts = count(QualityAlert, QualityAlert.resolved.is_(False))
    quals_passed = count(QualificationAttempt, QualificationAttempt.status == "passed")

    return {
        "organizations": orgs,
        "projects": {"total": projects, "active": projects_active},
        "datasets": {"total": datasets, "records": records},
        "tasks": {"total": tasks_total, "approved": tasks_approved,
                  "completion_rate": round(tasks_approved / tasks_total, 4) if tasks_total else None},
        "submissions": {"total": submissions_total, "approved": submissions_approved,
                        "rejected": submissions_rejected,
                        "approval_rate": round(submissions_approved / submissions_total, 4)
                        if submissions_total else None},
        "people": {"workers": workers, "reviewers": reviewers, "client_users": client_users},
        "client_requests": {"pending": requests_pending},
        "deliverables": deliverables,
        "quality": {
            "golden_attempts": golden_attempts,
            "golden_accuracy": round(golden_passed / golden_attempts, 4) if golden_attempts else None,
            "open_alerts": open_alerts,
            "qualifications_passed": quals_passed,
        },
        "computed_from": "live counts over stored records; rates are None when the "
                         "denominator is zero (never fabricated)",
    }


@router.get("/export")
def export_analytics(db: DbSession, user: AdminPM, request: Request,
                     kind: str = Query("quality", pattern="^(quality|platform)$"),
                     format: str = Query("csv", pattern="^(csv|json)$"),
                     project_id: int | None = None):
    """Downloadable analytics: quality rows (per worker) or platform rollups."""
    ids = acl.visible_project_ids(db, user)
    if kind == "platform":
        data = platform_analytics(db, user)
        if format == "json":
            return data
        rows = [("metric", "value")]

        def flatten(prefix, obj):
            for k, v in obj.items():
                if isinstance(v, dict):
                    flatten(f"{prefix}{k}.", v)
                else:
                    rows.append((f"{prefix}{k}", v))

        flatten("", data)
        body = "\n".join(f"{a},{b}" for a, b in rows)
        log_action(db, user_id=user.id, action="analytics.export", entity_type="analytics",
                   entity_id=None, details={"kind": kind, "format": format}, request=request)
        return Response(content=body, media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="platform_analytics.csv"'})

    # quality: per-worker aggregates over visible projects
    stmt = select(Submission)
    if ids is not None:
        stmt = stmt.where(Submission.project_id.in_(ids or {0}))
    if project_id:
        stmt = stmt.where(Submission.project_id == project_id)
    submissions = db.scalars(stmt).all()
    per_worker: dict[int, dict] = {}
    for s in submissions:
        w = per_worker.setdefault(s.tester_id, {"worker_id": s.tester_id, "submitted": 0,
                                                "approved": 0, "rejected": 0, "revisions": 0})
        w["submitted"] += 1
        if s.status == "approved":
            w["approved"] += 1
        elif s.status == "rejected":
            w["rejected"] += 1
        elif s.status == "revision_required":
            w["revisions"] += 1
    gstmt = select(GoldenTaskResult)
    if ids is not None:
        gstmt = gstmt.where(GoldenTaskResult.project_id.in_(ids or {0}))
    for r in db.scalars(gstmt).all():
        w = per_worker.setdefault(r.worker_id, {"worker_id": r.worker_id, "submitted": 0,
                                                "approved": 0, "rejected": 0, "revisions": 0})
        w.setdefault("golden_attempts", 0)
        w.setdefault("golden_passed", 0)
        w["golden_attempts"] += 1
        w["golden_passed"] += 1 if r.passed else 0
    rows = sorted(per_worker.values(), key=lambda x: x["worker_id"])
    if format == "json":
        log_action(db, user_id=user.id, action="analytics.export", entity_type="analytics",
                   entity_id=None, details={"kind": kind, "format": format}, request=request)
        return rows
    import csv as _csv
    import io
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["worker_id", "submitted", "approved", "rejected", "revisions",
                     "golden_attempts", "golden_passed", "golden_accuracy"])
    for w in rows:
        ga, gp = w.get("golden_attempts", 0), w.get("golden_passed", 0)
        writer.writerow([w["worker_id"], w["submitted"], w["approved"], w["rejected"],
                         w["revisions"], ga, gp,
                         round(gp / ga, 4) if ga else ""])
    log_action(db, user_id=user.id, action="analytics.export", entity_type="analytics",
               entity_id=None, details={"kind": kind, "format": format}, request=request)
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="quality_analytics.csv"'})


@router.get("/metrics")
def metrics(db: DbSession, user: CurrentUser, run_id: int | None = None):
    _require_analytics_access(db, user, run_id)
    return an.run_metrics(db, run_id)


@router.get("/agreement")
def agreement(db: DbSession, user: CurrentUser, run_id: int | None = None):
    _require_analytics_access(db, user, run_id)
    return an.agreement_metrics(db, run_id)


@router.get("/confusion-matrix")
def confusion_matrix(db: DbSession, user: CurrentUser, run_id: int | None = None):
    _require_analytics_access(db, user, run_id)
    data = an.run_metrics(db, run_id)
    cm = data.get("confusion_matrix")
    if cm is None:
        return {
            "labels": [],
            "matrix": [],
            "gold_total": data.get("gold_labeled_count", 0),
            "reason": data.get("insufficient_reason") or "No confusion matrix available.",
        }
    return {
        "labels": cm["labels"],
        "matrix": cm["matrix"],
        "gold_total": data.get("gold_labeled_count", 0),
        "reason": None,
    }
