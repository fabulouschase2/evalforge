"""Evaluation routes: create, run, list, results, findings."""
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.core.security import AdminPM, AdminPMEvaluator, CurrentUser, DbSession
from app.models.dataset import Dataset, DatasetRecord, DatasetVersion
from app.models.evaluation import EvaluationFinding, EvaluationResult, EvaluationRun
from app.models.rubric import Rubric, RubricVersion
from app.schemas import EvaluationCreate, EvaluationOut, PaginatedOut, ResultDetailOut, ResultOut
from app.engine.runner import run_evaluation
from app.services.audit import log_action

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.post("", response_model=EvaluationOut, status_code=201)
def create_evaluation(payload: EvaluationCreate, db: DbSession, user: AdminPMEvaluator, request: Request):
    dataset = db.get(Dataset, payload.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    rubric = db.get(Rubric, payload.rubric_id)
    if rubric is None:
        raise HTTPException(status_code=404, detail="Rubric not found.")

    dataset_version = None
    if payload.dataset_version_id:
        dataset_version = db.get(DatasetVersion, payload.dataset_version_id)
        if dataset_version is None or dataset_version.dataset_id != dataset.id:
            raise HTTPException(status_code=422, detail="dataset_version_id does not belong to the dataset.")
    else:
        dataset_version = db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).order_by(
            DatasetVersion.version_number.desc()).first()
        if dataset_version is None:
            raise HTTPException(status_code=422, detail="Dataset has no imported version yet; upload records first.")

    rubric_version = None
    if payload.rubric_version_id:
        rubric_version = db.get(RubricVersion, payload.rubric_version_id)
        if rubric_version is None or rubric_version.rubric_id != rubric.id:
            raise HTTPException(status_code=422, detail="rubric_version_id does not belong to the rubric.")
    else:
        rubric_version = db.query(RubricVersion).filter(RubricVersion.rubric_id == rubric.id).order_by(
            RubricVersion.version_number.desc()).first()
        if rubric_version is None:
            raise HTTPException(status_code=422, detail="Rubric has no versions; create a definition first.")

    run = EvaluationRun(
        name=payload.name.strip(),
        dataset_id=dataset.id,
        dataset_version_id=dataset_version.id,
        rubric_id=rubric.id,
        rubric_version_id=rubric_version.id,
        config=payload.config or {},
        created_by=user.id,
        is_demo=dataset.is_demo,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    log_action(db, user_id=user.id, action="evaluation.create", entity_type="evaluation", entity_id=run.id,
               details={
                   "name": run.name,
                   "dataset_version_id": dataset_version.id,
                   "rubric_version_id": rubric_version.id,
               }, request=request)
    return run


@router.get("", response_model=list[EvaluationOut])
def list_evaluations(db: DbSession, user: CurrentUser, status: str | None = None, limit: int = Query(50, ge=1, le=200)):
    stmt = select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(EvaluationRun.status == status)
    return list(db.scalars(stmt).all())


@router.get("/{run_id}", response_model=EvaluationOut)
def get_evaluation(run_id: int, db: DbSession, user: CurrentUser):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return run


@router.post("/{run_id}/run", response_model=EvaluationOut)
def execute_run(run_id: int, db: DbSession, user: AdminPMEvaluator, request: Request):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    if run.status == "completed":
        raise HTTPException(status_code=409, detail="Run already completed. Create a new run to re-evaluate (results are preserved for traceability).")
    if run.status == "running":
        raise HTTPException(status_code=409, detail="Run is already in progress.")

    rubric_version = db.get(RubricVersion, run.rubric_version_id)
    records = list(db.scalars(
        select(DatasetRecord).where(DatasetRecord.dataset_version_id == run.dataset_version_id).order_by(DatasetRecord.id)
    ).all())
    if not records:
        raise HTTPException(status_code=422, detail="Dataset version contains no records.")

    log_action(db, user_id=user.id, action="evaluation.execute", entity_type="evaluation", entity_id=run.id,
               details={"records": len(records), "rubric_version_id": run.rubric_version_id}, request=request)

    try:
        run_evaluation(db, run, records, rubric_version.definition)
    except Exception:
        db.rollback()
        db.refresh(run)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {run.error}")

    db.refresh(run)
    log_action(db, user_id=user.id, action="evaluation.completed", entity_type="evaluation", entity_id=run.id,
               details={
                   "passed": run.passed_count, "failed": run.failed_count,
                   "borderline": run.borderline_count, "needs_review": run.needs_review_count,
               }, request=request)
    return run


@router.get("/{run_id}/results")
def list_results(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    needs_review: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    stmt = select(EvaluationResult).where(EvaluationResult.run_id == run_id)
    if status:
        stmt = stmt.where(EvaluationResult.status == status)
    if needs_review is not None:
        stmt = stmt.where(EvaluationResult.needs_review.is_(needs_review))
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(EvaluationResult.id).offset((page - 1) * page_size).limit(page_size)).all()
    return PaginatedOut(items=[ResultOut.model_validate(r).model_dump(mode="json") for r in items], total=int(total), page=page, page_size=page_size)


@router.get("/{run_id}/results/{result_id}", response_model=ResultDetailOut)
def get_result(run_id: int, result_id: int, db: DbSession, user: CurrentUser):
    result = db.get(EvaluationResult, result_id)
    if result is None or result.run_id != run_id:
        raise HTTPException(status_code=404, detail="Result not found in this run.")
    out = ResultDetailOut.model_validate(result)
    out.findings = list(db.scalars(
        select(EvaluationFinding).where(EvaluationFinding.result_id == result_id).order_by(EvaluationFinding.id)
    ).all())
    return out


@router.get("/{run_id}/findings")
def run_findings(run_id: int, db: DbSession, user: CurrentUser, passed: bool | None = None, limit: int = Query(100, ge=1, le=500)):
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    stmt = (
        select(EvaluationFinding)
        .join(EvaluationResult, EvaluationFinding.result_id == EvaluationResult.id)
        .where(EvaluationResult.run_id == run_id)
    )
    if passed is not None:
        stmt = stmt.where(EvaluationFinding.passed.is_(passed))
    findings = db.scalars(stmt.order_by(EvaluationFinding.id).limit(limit)).all()
    return [
        {
            "id": f.id, "result_id": f.result_id, "rule_id": f.rule_id, "rule_name": f.rule_name,
            "check_type": f.check_type, "criterion_id": f.criterion_id, "passed": f.passed,
            "uncertain": f.uncertain, "explanation": f.explanation, "evidence": f.evidence,
            "severity": f.severity, "evaluator_version": f.evaluator_version, "rubric_version": f.rubric_version,
        }
        for f in findings
    ]
