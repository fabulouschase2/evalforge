"""Scoring: criterion scores, weighted aggregate and confidence estimation."""
from dataclasses import dataclass, field
from typing import Any

from app.engine.checks import CheckOutcome


@dataclass
class CriterionResult:
    criterion_id: str
    name: str
    weight: float
    score: float                 # normalized 0..1 for the criterion
    raw_score: float             # on the criterion scale
    scale_min: float
    scale_max: float
    passed: bool
    human_review_required: bool = False
    outcomes: list[CheckOutcome] = field(default_factory=list)


@dataclass
class ScoreResult:
    aggregate: float             # 0..1
    passed: bool
    criterion_results: list[CriterionResult]
    uncertain_checks: int
    total_checks: int
    failed_checks: int


def score_record(definition: dict[str, Any], outcomes_by_criterion: dict[str, list[CheckOutcome]]) -> ScoreResult:
    criteria = definition.get("criteria", [])
    weights_raw = []
    for c in criteria:
        w = c.get("weight", 1.0)
        if not isinstance(w, (int, float)) or w <= 0:
            w = 1.0
        weights_raw.append(float(w))
    total_weight = sum(weights_raw) or 1.0

    criterion_results: list[CriterionResult] = []
    aggregate = 0.0
    uncertain_checks = 0
    total_checks = 0
    failed_checks = 0

    for crit, w in zip(criteria, weights_raw):
        scale = crit.get("scoring_scale") or {}
        stype = scale.get("type", "binary")
        smin = float(scale.get("min", 0))
        smax = float(scale.get("max", 1)) if stype == "likert" else 1.0
        if smax <= smin:
            smin, smax = 0.0, 1.0
        threshold = crit.get("pass_threshold", smax)
        outcomes = outcomes_by_criterion.get(crit.get("id"), [])

        n = len(outcomes)
        critical_failed = any(
            o.passed is False and o.severity in ("high", "critical") for o in outcomes
        )
        if n == 0:
            raw = smin
        elif critical_failed:
            # A decisive check (json validity, numeric conflicts, forbidden content)
            # failing means the criterion fails outright regardless of other checks.
            raw = smin
        else:
            passed_n = sum(1 for o in outcomes if o.passed is True)
            inconclusive_n = sum(1 for o in outcomes if o.passed is None)
            # Inconclusive checks contribute half credit on likert scales, none on binary,
            # and always reduce confidence downstream.
            raw = passed_n + (0.5 if stype == "likert" else 0.0) * inconclusive_n
            # normalize to scale
            fraction = raw / n
            raw = smin + fraction * (smax - smin)

        normalized = (raw - smin) / (smax - smin) if smax > smin else 0.0
        passed = raw >= threshold

        for o in outcomes:
            total_checks += 1
            if o.passed is None or o.uncertain:
                uncertain_checks += 1
            if o.passed is False:
                failed_checks += 1

        weight = w / total_weight
        aggregate += weight * normalized
        criterion_results.append(CriterionResult(
            criterion_id=crit.get("id", ""),
            name=crit.get("name", ""),
            weight=weight,
            score=round(normalized, 4),
            raw_score=round(raw, 3),
            scale_min=smin,
            scale_max=smax,
            passed=passed,
            human_review_required=bool(crit.get("human_review_required", False)),
            outcomes=outcomes,
        ))

    threshold = definition.get("passing_threshold", 0.7)
    return ScoreResult(
        aggregate=round(min(max(aggregate, 0.0), 1.0), 4),
        passed=aggregate >= threshold,
        criterion_results=criterion_results,
        uncertain_checks=uncertain_checks,
        total_checks=total_checks,
        failed_checks=failed_checks,
    )


def compute_confidence(definition: dict[str, Any], score_result: ScoreResult, factuality: dict[str, Any]) -> tuple[float, list[str]]:
    """Confidence in the AUTOMATED decision (not in the response quality).

    Signals reducing confidence:
    - inconclusive/uncertain checks
    - missing reference data for factuality-sensitive criteria
    - aggregate score close to the passing threshold
    - mixed factuality verdicts
    """
    reasons: list[str] = []
    confidence = 1.0

    if score_result.total_checks:
        uncertain_ratio = score_result.uncertain_checks / score_result.total_checks
        if uncertain_ratio > 0:
            confidence *= (1.0 - 0.7 * uncertain_ratio)
            reasons.append(f"{score_result.uncertain_checks} of {score_result.total_checks} checks were inconclusive.")

    verdict = factuality.get("verdict")
    if verdict == "no_reference":
        confidence *= 0.55
        reasons.append("No reference material: factuality could not be assessed automatically.")
    elif verdict in ("needs_verification",):
        confidence *= 0.7
        reasons.append("Reference material insufficient to verify most claims.")
    elif verdict == "partially_supported":
        confidence *= 0.85
        reasons.append("Factuality verdict is mixed (partially supported).")

    margin_rule = (definition.get("borderline_rules") or {}).get("score_margin", 0.08)
    threshold = definition.get("passing_threshold", 0.7)
    margin = abs(score_result.aggregate - threshold)
    if margin < margin_rule:
        confidence *= 0.6
        reasons.append(
            f"Aggregate score {score_result.aggregate:.2f} is within the borderline margin "
            f"({margin_rule:.2f}) of the passing threshold {threshold:.2f}."
        )

    return round(max(min(confidence, 1.0), 0.0), 3), reasons
