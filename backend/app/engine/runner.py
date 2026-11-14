"""Evaluation runner: orchestrates checks -> scoring -> factuality -> borderline -> persistence.

Deterministic, synchronous and traceable: every check becomes an immutable
EvaluationFinding with rule id, input excerpt, output, pass/fail/inconclusive,
evidence, explanation, rubric version and evaluator version.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine import borderline as borderline_mod
from app.engine.checks import CheckOutcome, run_check
from app.engine.factuality import analyze_factuality
from app.engine.scoring import score_record
from app.models.dataset import DatasetRecord
from app.models.evaluation import EvaluationFinding, EvaluationResult, EvaluationRun

logger = logging.getLogger("evalforge.engine")


def record_to_dict(record: DatasetRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "prompt": record.prompt or "",
        "response": record.response or "",
        "reference_answer": record.reference_answer,
        "reference_sources": record.reference_sources or [],
        "expected_label": record.expected_label,
        "metadata": record.record_metadata or {},
    }


def _excerpt(text: str | None, limit: int = 400) -> str | None:
    if not text:
        return None
    return text[:limit] + ("…" if len(text) > limit else "")


def evaluate_single_record(
    definition: dict[str, Any],
    rubric_version_number: int,
    record: DatasetRecord,
    evaluator_version: str,
) -> dict[str, Any]:
    """Pure evaluation (no DB): returns a serializable payload for one record."""
    rec = record_to_dict(record)

    outcomes_by_criterion: dict[str, list[CheckOutcome]] = {}
    flat_outcomes: list[CheckOutcome] = []
    for crit in definition.get("criteria", []):
        cid = crit.get("id")
        outs: list[CheckOutcome] = []
        for check in crit.get("checks", []) or []:
            outcome = run_check(rec, check, cid)
            outcome.criterion_id = cid
            outs.append(outcome)
            flat_outcomes.append(outcome)
        outcomes_by_criterion[cid] = outs

    score_result = score_record(definition, outcomes_by_criterion)
    factuality = analyze_factuality(rec["response"], rec["reference_answer"], rec["reference_sources"])
    confidence, confidence_reasons = _confidence(definition, score_result, factuality)

    decision = borderline_mod.classify(
        definition=definition,
        aggregate=score_result.aggregate,
        confidence=confidence,
        factuality=factuality,
        record=rec,
        uncertain_checks=score_result.uncertain_checks,
        failed_checks=score_result.failed_checks,
        total_checks=score_result.total_checks,
    )

    automated_label = "pass" if score_result.passed else "fail"
    status = "borderline" if decision.is_borderline else ("pass" if score_result.passed else "fail")
    needs_review = borderline_mod.review_policy(definition, automated_label, decision.is_borderline) or bool(
        any(c.human_review_required for c in score_result.criterion_results if not c.passed)
    )

    gold = record.expected_label
    gold_label = None
    if gold:
        g = str(gold).strip().lower()
        if g in ("pass", "correct", "good", "yes", "1"):
            gold_label = "pass"
        elif g in ("fail", "incorrect", "bad", "no", "0"):
            gold_label = "fail"
        else:
            gold_label = str(gold).strip().lower()

    findings = []
    for o in flat_outcomes:
        findings.append({
            "rule_id": o.rule_id,
            "rule_name": o.rule_name,
            "check_type": o.check_type,
            "criterion_id": o.criterion_id,
            "input_excerpt": _excerpt(o.signals.get("input") or rec["response"]),
            "output": str(o.value) if o.value is not None else None,
            "passed": o.passed,
            "uncertain": o.uncertain or o.passed is None,
            "evidence": o.evidence,
            "explanation": o.explanation,
            "severity": o.severity,
            "evaluator_version": evaluator_version,
            "rubric_version": rubric_version_number,
        })

    return {
        "record": rec,
        "status": status,
        "automated_label": automated_label,
        "gold_label": gold_label,
        "score": score_result.aggregate,
        "confidence": confidence,
        "borderline_category": decision.category,
        "borderline_explanation": decision.explanation,
        "needs_review": needs_review,
        "criterion_scores": [
            {
                "criterion_id": c.criterion_id,
                "name": c.name,
                "weight": round(c.weight, 4),
                "score": c.score,
                "raw_score": c.raw_score,
                "scale": {"min": c.scale_min, "max": c.scale_max},
                "passed": c.passed,
            }
            for c in score_result.criterion_results
        ],
        "factuality": factuality,
        "confidence_reasons": confidence_reasons,
        "findings": findings,
    }


def _confidence(definition: dict[str, Any], score_result, factuality: dict[str, Any]) -> tuple[float, list[str]]:
    from app.engine.scoring import compute_confidence
    return compute_confidence(definition, score_result, factuality)


def persist_result(db: Session, run: EvaluationRun, payload: dict[str, Any], record: DatasetRecord) -> EvaluationResult:
    result = EvaluationResult(
        run_id=run.id,
        dataset_record_id=record.id,
        record_id=record.record_id,
        status=payload["status"],
        automated_label=payload["automated_label"],
        gold_label=payload["gold_label"],
        score=payload["score"],
        confidence=payload["confidence"],
        borderline_category=payload["borderline_category"],
        needs_review=payload["needs_review"],
        criterion_scores={"criteria": payload["criterion_scores"]},
        factuality={"verdict": payload["factuality"].get("verdict"),
                    "counts": payload["factuality"].get("counts"),
                    "claims": payload["factuality"].get("claims", [])[:10],
                    "note": payload["factuality"].get("note")},
        summary={
            "borderline_explanation": payload["borderline_explanation"],
            "confidence_reasons": payload["confidence_reasons"],
            "findings_passed": sum(1 for f in payload["findings"] if f["passed"] is True),
            "findings_failed": sum(1 for f in payload["findings"] if f["passed"] is False),
            "findings_inconclusive": sum(1 for f in payload["findings"] if f["passed"] is None),
        },
    )
    db.add(result)
    db.flush()

    for f in payload["findings"]:
        db.add(EvaluationFinding(result_id=result.id, **f))
    return result


def run_evaluation(db: Session, run: EvaluationRun, records: list[DatasetRecord], definition: dict[str, Any]) -> None:
    """Execute a full run synchronously and update run aggregates."""
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()

    evaluator_version = settings.evaluator_version
    passed = failed = borderline = needs_review = 0
    scores: list[float] = []

    try:
        for record in records:
            payload = evaluate_single_record(definition, run.rubric_version.version_number, record, evaluator_version)
            result = persist_result(db, run, payload, record)
            scores.append(result.score)
            if result.status == "pass":
                passed += 1
            elif result.status == "fail":
                failed += 1
            else:
                borderline += 1
            if result.needs_review:
                needs_review += 1
        run.status = "completed"
        run.passed_count = passed
        run.failed_count = failed
        run.borderline_count = borderline
        run.needs_review_count = needs_review
        run.total_records = len(records)
        run.avg_score = round(sum(scores) / len(scores), 4) if scores else None
        run.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.exception("Evaluation run %s failed", run.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise
    db.commit()
