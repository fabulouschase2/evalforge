"""Analytics: real statistical calculations via scikit-learn / SciPy.

Metrics requiring gold labels (accuracy, precision, recall, F1, confusion
matrix, Cohen's kappa) are only computed when enough gold-standard labels
exist; otherwise the API explicitly reports that the metric is unavailable
and why. Raw agreement vs chance-adjusted (Fleiss) agreement are reported
side by side so users never confuse percentage agreement with kappa.
"""
import math
from collections import Counter
from typing import Any

import numpy as np
from scipy import stats as sps
from sqlalchemy import case as sql_case
from sklearn.metrics import (
    accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.models.review import HumanReview
from app.models.rubric import Rubric


def _binary(v: str | None) -> str | None:
    if v in ("pass", "fail"):
        return v
    if v == "borderline":
        return None
    return None


def classification_metrics(gold: list[str], pred: list[str]) -> dict[str, Any]:
    """Compute binary metrics against gold labels (labels: fail=0, pass=1)."""
    if len(gold) == 0:
        return {"insufficient_reason": "No records have gold-standard labels.", "metrics": None}
    labels = ["fail", "pass"]
    try:
        cm = confusion_matrix(gold, pred, labels=labels)
    except ValueError as exc:
        return {"insufficient_reason": f"Confusion matrix failed: {exc}", "metrics": None}

    metrics: dict[str, Any] = {
        "gold_labeled_count": len(gold),
        "accuracy": round(float(accuracy_score(gold, pred)), 4),
        "precision": round(float(precision_score(gold, pred, labels=labels, average="binary", pos_label="pass", zero_division=0)), 4),
        "recall": round(float(recall_score(gold, pred, labels=labels, average="binary", pos_label="pass", zero_division=0)), 4),
        "f1": round(float(f1_score(gold, pred, labels=labels, average="binary", pos_label="pass", zero_division=0)), 4),
        "confusion_matrix": {"labels": labels, "matrix": cm.astype(int).tolist()},
    }
    # Cohen's kappa needs at least two distinct values on each axis to be meaningful
    if len(set(gold)) > 1 and len(set(pred)) > 1:
        metrics["cohen_kappa"] = round(float(cohen_kappa_score(gold, pred, labels=labels)), 4)
    else:
        metrics["kappa_note"] = "Cohen's kappa undefined when either axis has a single class."
    return {"metrics": metrics}


def run_metrics(db: Session, run_id: int | None = None) -> dict[str, Any]:
    stmt = select(EvaluationResult)
    if run_id:
        stmt = stmt.where(EvaluationResult.run_id == run_id)
    results = list(db.scalars(stmt).all())

    total = len(results)
    if total == 0:
        return {
            "run_id": run_id, "gold_labeled_count": 0,
            "insufficient_reason": "No evaluation results available yet.",
            "pass_rate": None, "avg_score": None, "borderline_rate": None,
            "failure_categories": {},
        }

    pass_count = sum(1 for r in results if r.status == "pass")
    borderline_count = sum(1 for r in results if r.status == "borderline")
    failed_count = sum(1 for r in results if r.status == "fail")
    avg_score = sum(r.score for r in results) / total

    paired = [
        (str(r.gold_label), _binary(r.automated_label))
        for r in results
        if r.gold_label in ("pass", "fail") and _binary(r.automated_label) is not None
    ]
    gold = [g for g, _ in paired]
    pred = [p for _, p in paired]

    out: dict[str, Any] = {
        "run_id": run_id,
        "pass_rate": round(pass_count / total, 4),
        "avg_score": round(avg_score, 4),
        "borderline_rate": round(borderline_count / total, 4),
        "failure_categories": dict(Counter(
            r.borderline_category for r in results
            if r.borderline_category
        )),
        "insufficient_reason": None,
        # Uniform metric keys (None when not computable) so clients can bind safely
        "accuracy": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "cohen_kappa": None,
        "confusion_matrix": None,
        "gold_labeled_count": 0,
    }

    if not paired:
        out["gold_labeled_count"] = 0
        out["insufficient_reason"] = (
            "No records pair a gold-standard label with a binary automated decision. "
            "Import records with expected_label (pass/fail) and run an evaluation to enable "
            "accuracy, precision, recall and F1."
        )
        out["confusion_matrix"] = None
    else:
        result = classification_metrics(gold, pred)
        if result.get("metrics"):
            out.update(result["metrics"])
            out["gold_labeled_count"] = result["metrics"]["gold_labeled_count"]
            cm = result["metrics"].get("confusion_matrix")
            out["confusion_matrix"] = cm
        else:
            out["insufficient_reason"] = result.get("insufficient_reason")
    return out


# ----------------------------- inter-annotator agreement --------------------

def fleiss_kappa(matrix: list[list[int]]) -> float | None:
    """Fleiss' kappa over an items x categories count matrix."""
    arr = np.asarray(matrix, dtype=float)
    if arr.shape[0] == 0:
        return None
    n_per_item = arr.sum(axis=1)
    if (n_per_item < 2).any() or len(set(n_per_item.tolist())) != 1:
        return None
    n = float(n_per_item[0])
    N = float(arr.shape[0])
    k = float(arr.shape[1])

    p_j = arr.sum(axis=0) / (N * n)
    P_i = (np.square(arr).sum(axis=1) - n) / (n * (n - 1))
    P_bar = P_i.mean()
    P_e = float(np.square(p_j).sum())
    if P_e == 1.0:
        return None
    kappa = (P_bar - P_e) / (1 - P_e)
    return round(float(kappa), 4)


def agreement_metrics(db: Session, run_id: int | None = None) -> dict[str, Any]:
    """Reviewer agreement across items (optionally scoped to one run)."""
    stmt = select(HumanReview)
    if run_id:
        stmt = stmt.join(EvaluationResult, HumanReview.result_id == EvaluationResult.id).where(
            EvaluationResult.run_id == run_id
        )
    reviews = list(db.scalars(stmt).all())

    by_result: dict[int, list[HumanReview]] = {}
    for r in reviews:
        by_result.setdefault(r.result_id, []).append(r)

    multi = {rid: revs for rid, revs in by_result.items() if len(revs) >= 2}
    full_agreement = sum(1 for revs in multi.values() if len({rv.label for rv in revs}) == 1)
    disagreement_items = len(multi) - full_agreement

    raw_rate: float | None = None
    kappa: float | None = None
    note: str | None = None

    if multi:
        raw_rate = round(full_agreement / len(multi), 4)
        # Build items x categories matrix over the union of labels used
        label_set = sorted({rv.label for revs in multi.values() for rv in revs})
        label_idx = {label: i for i, label in enumerate(label_set)}
        matrix = []
        for revs in multi.values():
            row = [0] * len(label_set)
            for rv in revs:
                row[label_idx[rv.label]] += 1
            matrix.append(row)
        kappa = fleiss_kappa(matrix)
        if kappa is None:
            note = "Fleiss' kappa requires the same number of reviewers on every item."
        elif abs(kappa) > 1:
            kappa = None
            note = "Fleiss' kappa undefined for this rating distribution."
    else:
        note = (
            "No items have two or more submitted independent reviews yet. Assign multiple "
            "reviewers to the same results and collect their assessments to measure agreement."
        )

    # Reviewer-level agreement with the automated decision
    reviewer_stats: dict[str, Any] = {}
    for r in reviews:
        if r.agrees_with_automated is None:
            continue
        s = reviewer_stats.setdefault(r.reviewer_id, {"total": 0, "agree": 0})
        s["total"] += 1
        if r.agrees_with_automated:
            s["agree"] += 1

    return {
        "reviewer_count": len({r.reviewer_id for r in reviews}),
        "items_with_multiple_reviews": len(multi),
        "full_agreement_items": full_agreement,
        "raw_agreement_rate": raw_rate,
        "fleiss_kappa": kappa,
        "disagreement_items": disagreement_items,
        "reviewer_agreement_with_automated": reviewer_stats,
        "note": note,
    }


def admin_overview(db: Session, days: int = 14) -> dict[str, Any]:
    """Platform-level administration stats (live data only; no fabricated values)."""
    from datetime import datetime, timedelta, timezone as tz

    from app.models.dataset import Dataset, DatasetRecord
    from app.models.project import Project
    from app.models.submission import Submission, SubmissionReview
    from app.models.task import Task
    from app.models.user import User

    total_projects = db.scalar(select(func.count()).select_from(Project)) or 0
    active_projects = db.scalar(select(func.count()).select_from(Project).where(Project.status == "active")) or 0
    total_datasets = db.scalar(select(func.count()).select_from(Dataset)) or 0
    total_records = db.scalar(select(func.count()).select_from(DatasetRecord)) or 0

    task_total = db.scalar(select(func.count()).select_from(Task)) or 0
    tasks_by_status = {
        status: db.scalar(select(func.count()).select_from(Task).where(Task.status == status)) or 0
        for status in ["draft", "available", "assigned", "in_progress", "submitted",
                       "under_review", "revision_required", "approved", "rejected", "cancelled"]
    }

    # Average completion time: claim -> submit on submitted+ submissions
    completion_rows = db.execute(
        select(Task.claimed_at, Submission.submitted_at)
        .join(Submission, Submission.task_id == Task.id)
        .where(Task.claimed_at.is_not(None))
    ).all()
    durations = [
        (s - c).total_seconds() for c, s in completion_rows if s and c and s >= c
    ]
    avg_completion_hours = round(sum(durations) / len(durations) / 3600, 2) if durations else None

    # Tester performance
    tester_rows = db.execute(
        select(
            Submission.tester_id,
            func.count().label("submitted"),
            func.sum(sql_case((Submission.status == "approved", 1), else_=0)).label("approved"),
            func.sum(sql_case((Submission.status == "rejected", 1), else_=0)).label("rejected"),
            func.sum(sql_case((Submission.status == "revision_required", 1), else_=0)).label("revisions"),
        ).group_by(Submission.tester_id)
    ).all()
    tester_performance = []
    for tid, submitted, approved, rejected, revisions in tester_rows:
        u = db.get(User, tid)
        decided = (approved or 0) + (rejected or 0)
        tester_performance.append({
            "tester_id": tid,
            "name": u.name if u else f"user {tid}",
            "submitted": int(submitted or 0),
            "approved": int(approved or 0),
            "rejected": int(rejected or 0),
            "revision_required": int(revisions or 0),
            "approval_rate": round((approved or 0) / decided, 4) if decided else None,
        })
    tester_performance.sort(key=lambda x: -x["submitted"])

    # Reviewer performance
    reviewer_rows = db.execute(
        select(
            SubmissionReview.reviewer_id,
            func.count().label("reviews"),
            func.sum(sql_case((SubmissionReview.decision == "approved", 1), else_=0)).label("approved"),
            func.sum(sql_case((SubmissionReview.decision == "rejected", 1), else_=0)).label("rejected"),
            func.sum(sql_case((SubmissionReview.decision == "revision_requested", 1), else_=0)).label("revisions"),
        ).group_by(SubmissionReview.reviewer_id)
    ).all()
    reviewer_performance = []
    for rid, reviews, approved, rejected, revisions in reviewer_rows:
        u = db.get(User, rid)
        reviewer_performance.append({
            "reviewer_id": rid,
            "name": u.name if u else f"user {rid}",
            "reviews": int(reviews or 0),
            "approved": int(approved or 0),
            "rejected": int(rejected or 0),
            "revision_requested": int(revisions or 0),
        })

    decided_submissions = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.status.in_(["approved", "rejected"]))
    ) or 0
    approved_submissions = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.status == "approved")
    ) or 0
    overall_quality = round(approved_submissions / decided_submissions, 4) if decided_submissions else None

    # Daily submissions (last N days)
    since = datetime.now(tz.utc) - timedelta(days=days - 1)
    daily_rows = db.execute(
        select(Submission.submitted_at).where(Submission.submitted_at >= since)
    ).all()
    daily_counts: dict[str, int] = {}
    for (ts,) in daily_rows:
        day = ts.astimezone(tz.utc).strftime("%Y-%m-%d")
        daily_counts[day] = daily_counts.get(day, 0) + 1
    daily_submissions = []
    for i in range(days):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        daily_submissions.append({"day": day, "count": daily_counts.get(day, 0)})

    # Project progress
    progress_rows = db.execute(
        select(
            Project.id, Project.name,
            func.count(Task.id),
            func.sum(sql_case((Task.status == "approved", 1), else_=0)),
        )
        .outerjoin(Task, Task.project_id == Project.id)
        .group_by(Project.id, Project.name)
        .order_by(Project.created_at.desc())
        .limit(12)
    ).all()
    project_progress = [
        {
            "project_id": pid, "name": name, "total_tasks": int(total or 0),
            "approved": int(approved or 0),
        }
        for pid, name, total, approved in progress_rows
    ]

    return {
        "total_projects": int(total_projects),
        "active_projects": int(active_projects),
        "total_datasets": int(total_datasets),
        "total_records": int(total_records),
        "task_total": int(task_total),
        "tasks_by_status": tasks_by_status,
        "avg_completion_hours": avg_completion_hours,
        "completion_samples": len(durations),
        "tester_performance": tester_performance,
        "reviewer_performance": reviewer_performance,
        "overall_quality_score": overall_quality,
        "decided_submissions": int(decided_submissions),
        "daily_submissions": daily_submissions,
        "project_progress": project_progress,
    }


def overview(db: Session) -> dict[str, Any]:
    total_results = db.scalar(select(func.count()).select_from(EvaluationResult)) or 0
    completed = db.scalar(
        select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status == "completed")
    ) or 0
    active = db.scalar(
        select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status.in_(["pending", "running"]))
    ) or 0
    failed_results = db.scalar(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.status == "fail")
    ) or 0
    borderline = db.scalar(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.status == "borderline")
    ) or 0
    pass_results = db.scalar(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.status == "pass")
    ) or 0
    review_queue = db.scalar(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.needs_review.is_(True))
    ) or 0

    recent_runs = list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(8)).all())

    failure_categories = dict(Counter(
        r.borderline_category
        for r in db.scalars(select(EvaluationResult).where(EvaluationResult.borderline_category.is_not(None))).all()
    ))

    # Trend: pass rate over completed runs, chronological
    runs = list(db.scalars(select(EvaluationRun).where(EvaluationRun.status == "completed").order_by(EvaluationRun.created_at)).all())
    trend = []
    for run in runs:
        denom = run.passed_count + run.failed_count + run.borderline_count
        trend.append({
            "run_id": run.id,
            "name": run.name,
            "created_at": run.created_at.isoformat(),
            "pass_rate": round(run.passed_count / denom, 4) if denom else None,
            "borderline_rate": round(run.borderline_count / denom, 4) if denom else None,
            "avg_score": run.avg_score,
        })

    agreement = agreement_metrics(db)
    dataset_count = db.scalar(select(func.count()).select_from(Dataset)) or 0
    rubric_count = db.scalar(select(func.count()).select_from(Rubric)) or 0

    return {
        "total_records": int(total_results),
        "completed_runs": int(completed),
        "active_runs": int(active),
        "automated_pass_rate": round(pass_results / total_results, 4) if total_results else None,
        "failed_count": int(failed_results),
        "borderline_count": int(borderline),
        "review_queue_size": int(review_queue),
        "reviewer_agreement": agreement.get("raw_agreement_rate"),
        "recent_runs": recent_runs,
        "failure_categories": failure_categories,
        "trend": trend,
        "dataset_count": int(dataset_count),
        "rubric_count": int(rubric_count),
    }
