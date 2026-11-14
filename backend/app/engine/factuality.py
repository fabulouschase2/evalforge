"""Reference-based factuality analysis (deterministic heuristics).

This module distinguishes four claim states using lexical and numeric signals
against reference material when available:

- supported:        key content of the claim appears in the reference
- contradicted:     the claim conflicts with the reference (e.g. different numbers,
                    explicit negation of a reference statement)
- unsupported:      the claim introduces content absent from the reference
- needs_verification: the claim cannot be compared (no reference or too little overlap)

IMPORTANT: these are transparent heuristics, not semantic understanding.
Keyword/number matching cannot prove factual accuracy — results are labeled as
heuristic signals and routed to human review when ambiguity remains.
"""
import re
from typing import Any

from app.engine.checks import CITATION_STRIP_RE, NUMBER_RE, STOPWORDS, _words

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NEGATION_RE = re.compile(
    r"\b(not|no|never|cannot|can't|won't|doesn't|don't|didn't|isn't|aren't|"
    r"wasn't|weren't|fails? to|does not|did not|without|excluded|excluding|"
    r"except|prohibited|forbidden)\b",
    re.IGNORECASE,
)
HEDGE_RE = re.compile(
    r"\b(maybe|possibly|probably|likely|unlikely|unclear|uncertain|"
    r"believe|think|seems|appears|might|may)\b",
    re.IGNORECASE,
)


def _salient_terms(text: str) -> set[str]:
    return {w for w in _words(text) if w not in STOPWORDS and len(w) > 2}


def _numbers(text: str) -> list[float]:
    text = CITATION_STRIP_RE.sub(" ", text)
    out = []
    for m in NUMBER_RE.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def classify_claim(sentence: str, ref_terms: set[str], ref_numbers: list[float],
                   ref_has_negation: bool) -> tuple[str, dict]:
    """Classify one claim sentence. Returns (state, signals)."""
    terms = _salient_terms(sentence)
    nums = _numbers(sentence)
    has_negation = bool(NEGATION_RE.search(sentence))
    hedged = bool(HEDGE_RE.search(sentence))
    signals: dict = {"hedged": hedged}

    if not terms and not nums:
        return "needs_verification", signals

    overlap = terms & ref_terms
    ratio = len(overlap) / len(terms) if terms else 1.0
    signals["overlap_ratio"] = round(ratio, 3)

    # Numeric conflicts are the clearest contradiction signal
    if nums and ref_numbers:
        conflicting = [n for n in nums if n not in ref_numbers]
        matching = [n for n in nums if n in ref_numbers]
        signals["conflicting_numbers"] = conflicting
        signals["matching_numbers"] = matching
        if conflicting and not matching and ratio > 0.35:
            if hedged:
                return "needs_verification", signals
            return "contradicted", signals
        if conflicting and matching:
            # Mixed numeric evidence: cannot decide which number governs -> defer.
            return "needs_verification", signals
        if matching and not conflicting:
            return "supported", signals

    if ratio >= 0.75 and not (has_negation != ref_has_negation):
        return "supported", signals
    if ratio <= 0.25:
        return "unsupported", signals
    # Negation contrast against reference (e.g. response says "included",
    # reference says "excluded") while talking about the same topic.
    if (has_negation != ref_has_negation) and ratio >= 0.4:
        return "contradicted", signals
    if hedged or ratio < 0.5:
        return "needs_verification", signals
    return "supported", signals


def analyze_factuality(response: str, reference: str | None, reference_sources: list | None) -> dict[str, Any]:
    """Return claim-level classification with an aggregate verdict.

    The aggregate verdict is one of:
    - "well_supported"    — most claims supported, few unsupported
    - "partially_supported" — meaningful mix
    - "contradicted"      — at least one claim directly conflicts with reference
    - "unsupported"       — most claims absent from reference
    - "needs_verification" — not enough reference material to decide
    - "no_reference"      — no reference material at all
    """
    if not reference and not reference_sources:
        return {
            "verdict": "no_reference",
            "claims": [],
            "note": (
                "No reference material on this record. Factual support cannot be assessed "
                "automatically; any factuality conclusion would require human judgment."
            ),
        }

    ref_text = str(reference or "")
    for src in reference_sources or []:
        ref_text += "\n" + str(src if isinstance(src, str) else src.get("title", "") + " " + str(src.get("content", "")))
    ref_terms = _salient_terms(ref_text)
    ref_numbers = _numbers(ref_text)
    ref_has_negation = bool(NEGATION_RE.search(ref_text))

    sentences = [s.strip() for s in SENT_SPLIT_RE.split(response) if s.strip()]
    claims: list[dict[str, Any]] = []
    for s in sentences[:40]:
        state, signals = classify_claim(s, ref_terms, ref_numbers, ref_has_negation)
        claims.append({
            "text": s[:300],
            "state": state,
            "numbers": _numbers(s)[:8],
            **signals,
        })

    counts = {"supported": 0, "contradicted": 0, "unsupported": 0, "needs_verification": 0}
    for c in claims:
        counts[c["state"]] += 1
    total = sum(counts.values()) or 1
    conflicting_number_claims = sum(
        1 for c in claims if c.get("conflicting_numbers") and c.get("matching_numbers")
    )

    if counts["contradicted"] > 0:
        verdict = "contradicted"
    elif total and counts["unsupported"] / total > 0.6:
        verdict = "unsupported"
    elif total and counts["supported"] / total >= 0.7:
        verdict = "well_supported"
    elif total and counts["supported"] / total >= 0.35:
        verdict = "partially_supported"
    else:
        verdict = "needs_verification"

    notes = {
        "contradicted": "At least one response claim conflicts with the reference material (numeric or negation conflict).",
        "unsupported": "Most response claims do not appear in the reference material.",
        "well_supported": "Most response claims align with the reference material.",
        "partially_supported": "A meaningful share of claims are supported while others are not.",
        "needs_verification": "Reference material is insufficient to verify most claims.",
    }

    return {
        "verdict": verdict,
        "counts": counts,
        "claims": claims,
        "conflicting_number_claims": conflicting_number_claims,
        "note": notes[verdict] + " Heuristic lexical analysis — not semantic verification.",
    }
