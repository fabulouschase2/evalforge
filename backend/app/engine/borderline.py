"""Borderline / uncertainty classification.

Philosophy: low confidence does NOT mean incorrect. We separate three axes:
1. Model response quality (pass/fail from scoring).
2. Evaluation system uncertainty (can the automation trust its own decision?).
3. Reviewer disagreement (handled later when multiple humans disagree).

A borderline result keeps its automated label (`automated_label`) but is routed
to human review with a category and explanation. Nothing is destroyed.
"""
from dataclasses import dataclass, field
from typing import Any


CATEGORIES = [
    "partially_correct",
    "evidence_insufficient",
    "context_misleading",
    "ambiguous_instruction",
    "conflicting_evidence",
    "reviewer_disagreement",
    "uncertain_automated_decision",
]

AMBIGUITY_MARKERS = [
    "or not", "it depends", "in some cases", "varies", "as appropriate",
    "if necessary", "where applicable", "e.g.", "or equivalent", "up to you",
    "feel free", "as needed", "whatever makes sense", "or whatever",
    "or something", "as you see fit", "whatever works",
]


@dataclass
class BorderlineDecision:
    is_borderline: bool
    category: str | None = None
    explanation: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)


def _prompt_is_ambiguous(prompt: str) -> tuple[bool, str | None]:
    lowered = prompt.lower()
    hits = [m for m in AMBIGUITY_MARKERS if m in lowered]
    question_count = lowered.count("?")
    if question_count >= 3:
        return True, f"Prompt asks {question_count} separate questions; scope may be ambiguous."
    if hits:
        return True, f"Prompt contains ambiguity markers: {hits[:3]}."
    if "?" not in lowered and len(lowered.split()) < 8:
        return True, "Prompt is a short statement without a clear question; instruction intent is unclear."
    return False, None


def classify(
    definition: dict[str, Any],
    aggregate: float,
    confidence: float,
    factuality: dict[str, Any],
    record: dict[str, Any],
    uncertain_checks: int,
    failed_checks: int,
    total_checks: int,
) -> BorderlineDecision:
    rules = definition.get("borderline_rules") or {}
    confidence_below = float(rules.get("confidence_below", 0.6))
    score_margin = float(rules.get("score_margin", 0.08))
    enabled = set(rules.get("categories_enabled") or CATEGORIES)
    threshold = float(definition.get("passing_threshold", 0.7))

    signals: dict[str, Any] = {
        "confidence": confidence,
        "aggregate": aggregate,
        "threshold": threshold,
        "factuality_verdict": factuality.get("verdict"),
        "uncertain_checks": uncertain_checks,
    }

    # 1) Automated decision uncertainty
    if confidence < confidence_below:
        if "uncertain_automated_decision" in enabled:
            return BorderlineDecision(
                True, "uncertain_automated_decision",
                f"Automated decision confidence {confidence:.2f} is below the configured threshold "
                f"{confidence_below:.2f}. The automated label is provisional, not a verdict.",
                signals,
            )

    # 2) Score close to threshold (either side) -> borderline
    if abs(aggregate - threshold) < score_margin:
        if "partially_correct" in enabled:
            return BorderlineDecision(
                True, "partially_correct",
                f"Aggregate score {aggregate:.2f} sits within the borderline margin ({score_margin:.2f}) "
                f"of the passing threshold {threshold:.2f}: neither clearly passing nor clearly failing.",
                signals,
            )

    # 3) Factuality-driven categories (only when reference data exists)
    verdict = factuality.get("verdict")

    # Mixed numeric evidence: some numbers match the reference, others conflict.
    # The automation cannot decide which governs — a human must.
    if factuality.get("conflicting_number_claims", 0) > 0 and verdict in (
        "needs_verification", "partially_supported",
    ) and "conflicting_evidence" in enabled:
        return BorderlineDecision(
            True, "conflicting_evidence",
            "Response contains numbers that both match and conflict with the reference material. "
            "The automated check cannot determine which values govern, so the decision is routed "
            "to human review rather than being auto-classified.",
            signals,
        )

    if verdict == "needs_verification" and "evidence_insufficient" in enabled:
        return BorderlineDecision(
            True, "evidence_insufficient",
            "Reference material exists but is insufficient to verify most response claims; "
            "factual correctness cannot be established automatically.",
            signals,
        )
    if verdict in ("partially_supported",) and "partially_correct" in enabled and aggregate >= threshold:
        return BorderlineDecision(
            True, "partially_correct",
            "Response passes deterministic checks but factuality analysis found a meaningful share "
            "of claims without reference support. Human judgment needed before trusting the pass.",
            signals,
        )
    if verdict == "no_reference" and "evidence_insufficient" in enabled and not failed_checks:
        return BorderlineDecision(
            True, "evidence_insufficient",
            "No reference material on this record; automated checks pass but factual accuracy "
            "is unverifiable. Do not treat this as a confirmed correct answer.",
            signals,
        )

    # 4) Near-split check outcomes -> conflicting evidence. Only when the response
    #    would otherwise pass (aggregate >= threshold) and the reference verdict is
    #    not decisive (contradicted/unsupported mean a clear failure).
    if (total_checks > 1 and failed_checks > 0 and (total_checks - failed_checks) > 0
            and aggregate >= threshold):
        passed_share = (total_checks - failed_checks) / total_checks
        if (0.4 <= passed_share <= 0.6 and "conflicting_evidence" in enabled
                and verdict not in ("contradicted", "unsupported")):
            return BorderlineDecision(
                True, "conflicting_evidence",
                f"Deterministic checks nearly split: {total_checks - failed_checks} passed and "
                f"{failed_checks} failed. The response shows genuinely mixed signals across criteria.",
                signals,
            )

    # 5) Ambiguous instruction — only flag when the response otherwise passes
    ambiguous, why = _prompt_is_ambiguous(record.get("prompt", ""))
    if ambiguous and aggregate >= threshold and "ambiguous_instruction" in enabled:
        return BorderlineDecision(
            True, "ambiguous_instruction",
            f"Response passes automated checks, but the instruction itself may be ambiguous: {why} "
            "A human should confirm the response addresses the intended reading.",
            signals,
        )

    # 6) Context misleading: reference sources contradict the prompt's premise
    sources = record.get("reference_sources") or []
    if (sources and aggregate >= threshold and not failed_checks
            and factuality.get("verdict") == "unsupported" and "context_misleading" in enabled):
        return BorderlineDecision(
            True, "context_misleading",
            "Structural checks pass but response claims do not align with provided reference "
            "material; the context given to the model may be misleading.",
            signals,
        )

    return BorderlineDecision(False, None, None, signals)


def review_policy(definition: dict[str, Any], status: str, is_borderline: bool) -> bool:
    policy = definition.get("human_review_policy") or {}
    if is_borderline and policy.get("when_borderline", True):
        return True
    if status == "fail" and policy.get("when_failed", False):
        return True
    return False
