"""Deterministic evaluation checks.

Each check receives a normalized record + check params and returns an outcome.
`passed=None` means the check was inconclusive (e.g. needs reference data that
is missing) — inconclusive checks lower confidence and can trigger borderline
routing, but they never silently turn into pass/fail.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any

WORD_RE = re.compile(r"\b\w+\b")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
CITATION_RE = re.compile(r"\[(\d+)\]|\((\w+,\s*\d{4})\)")

TRUNCATION_MARKERS = ("...", "…", "[truncated]", "[cut off]", "TODO", "lorem ipsum")


@dataclass
class CheckOutcome:
    rule_id: str
    rule_name: str
    check_type: str
    passed: bool | None          # None => inconclusive
    uncertain: bool = False
    value: Any = None
    expected: Any = None
    evidence: str | None = None
    explanation: str | None = None
    severity: str = "medium"
    signals: dict[str, Any] = field(default_factory=dict)


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.findall(text) if s.strip()]


def _find_regex(pattern: str, text: str, flags: int = 0) -> list[str]:
    try:
        return re.findall(pattern, text, flags)
    except re.error as exc:
        return [f"<invalid regex: {exc}>"]


# ---------------------------------------------------------------- checks ----

def check_format_regex(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    pattern = params.get("pattern", "")
    flags = re.IGNORECASE if params.get("case_insensitive", True) else 0
    if not pattern:
        return CheckOutcome(rule_id, rule_name, "format_regex", None, uncertain=True,
                            explanation="No pattern configured.")
    matches = _find_regex(pattern, record["response"], flags)
    passed = bool(matches) and "<invalid regex" not in str(matches[0])
    return CheckOutcome(rule_id, rule_name, "format_regex", passed,
                        value=(matches[0][:100] if matches else None),
                        expected=pattern,
                        evidence=f"Found {len(matches)} match(es) for pattern {pattern!r}.",
                        explanation=None if passed else "Response does not match the required format.",
                        severity=params.get("severity", "medium"))


def check_json_valid(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    text = record["response"].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return CheckOutcome(rule_id, rule_name, "json_valid", False,
                            value=None, expected="valid JSON",
                            evidence=f"JSON parse error: {exc.msg} at line {exc.lineno}",
                            explanation="Response is not valid JSON.",
                            severity=params.get("severity", "high"))
    required_keys = params.get("required_keys", [])
    missing = [k for k in required_keys if k not in parsed] if isinstance(parsed, dict) else []
    passed = not missing
    return CheckOutcome(rule_id, rule_name, "json_valid", passed,
                        value="object" if isinstance(parsed, dict) else type(parsed).__name__,
                        expected=f"keys: {required_keys}" if required_keys else "valid JSON",
                        evidence=None if passed else f"Missing required keys: {missing}",
                        explanation=None if passed else "JSON is valid but missing required keys.",
                        severity=params.get("severity", "high"))


def _length_check(record, params, rule_id, rule_name, mode: str, limit_key: str, default: int) -> CheckOutcome:
    text = record["response"]
    value = len(_words(text)) if mode.startswith("min_words") or mode.startswith("max_words") else len(text)
    limit = params.get(limit_key, default)
    ctype = mode if mode in ("min_words", "max_words", "min_chars", "max_chars") else mode
    if mode.startswith("min"):
        passed = value >= limit
        explanation = None if passed else f"Too short: {value} {mode.split('_')[1]}, minimum {limit}."
    else:
        passed = value <= limit
        explanation = None if passed else f"Too long: {value} {mode.split('_')[1]}, maximum {limit}."
    return CheckOutcome(rule_id, rule_name, ctype, passed, value=value, expected=limit,
                        evidence=f"{mode}: {value} (limit {limit})",
                        explanation=explanation, severity=params.get("severity", "low"))


def check_sentence_count(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    sentences = _sentences(record["response"])
    n = len(sentences)
    smin, smax = params.get("min"), params.get("max")
    passed = True
    problems = []
    if smin is not None and n < smin:
        passed, _ = False, problems.append(f"fewer than {smin} sentences ({n})")
    if smax is not None and n > smax:
        passed, _ = False, problems.append(f"more than {smax} sentences ({n})")
    return CheckOutcome(rule_id, rule_name, "sentence_count", passed, value=n,
                        expected={"min": smin, "max": smax},
                        evidence=f"Response contains {n} sentences (allowed: min={smin}, max={smax}).",
                        explanation=None if passed else "Sentence-count constraint violated: " + "; ".join(problems),
                        severity=params.get("severity", "low"))


def check_required_keywords(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    keywords = params.get("keywords", [])
    mode = params.get("mode", "all")
    case_sensitive = params.get("case_sensitive", False)
    text = record["response"] if case_sensitive else record["response"].lower()
    found, missing = [], []
    for kw in keywords:
        needle = kw if case_sensitive else kw.lower()
        present = needle in text
        (found if present else missing).append(kw)
    if not keywords:
        return CheckOutcome(rule_id, rule_name, "required_keywords", None, uncertain=True,
                            explanation="No keywords configured.")
    passed = all(k in found for k in keywords) if mode == "all" else len(found) > 0
    evidence = f"Found {len(found)}/{len(keywords)} required keyword(s)." + (f" Missing: {missing}" if missing else "")
    return CheckOutcome(rule_id, rule_name, "required_keywords", passed,
                        value={"found": found, "missing": missing},
                        expected=f"mode={mode}: {keywords}",
                        evidence=evidence,
                        explanation=None if passed else f"Missing required keywords ({mode}-match): {missing}",
                        severity=params.get("severity", "medium"))


def check_forbidden_patterns(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    patterns = params.get("patterns", [])
    violations = []
    for pat in patterns:
        matches = _find_regex(pat, record["response"], re.IGNORECASE)
        if matches and "<invalid regex" not in str(matches[0]):
            violations.append({"pattern": pat, "matches": [str(m)[:60] for m in matches[:3]]})
    if not patterns:
        return CheckOutcome(rule_id, rule_name, "forbidden_patterns", None, uncertain=True,
                            explanation="No patterns configured.")
    passed = not violations
    return CheckOutcome(rule_id, rule_name, "forbidden_patterns", passed,
                        value=violations, expected="no forbidden patterns",
                        evidence=None if passed else f"Forbidden pattern matches: {violations}",
                        explanation=None if passed else "Response contains forbidden content patterns.",
                        severity=params.get("severity", "high"))


def check_required_fields(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    fields = params.get("fields", [])
    text = record["response"]
    missing = [f for f in fields if not re.search(rf"(?im)^\s*{re.escape(f)}\s*:", text)]
    if not fields:
        return CheckOutcome(rule_id, rule_name, "required_fields", None, uncertain=True,
                            explanation="No fields configured.")
    passed = not missing
    return CheckOutcome(rule_id, rule_name, "required_fields", passed,
                        value={"missing": missing}, expected=fields,
                        evidence=None if passed else f"Missing required 'Field:' sections: {missing}",
                        explanation=None if passed else f"Structured response missing required fields: {missing}",
                        severity=params.get("severity", "medium"))


def check_completeness(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    """Heuristic completeness: non-empty, not truncated, addresses the asked questions."""
    response = record["response"].strip()
    prompt = record["prompt"]
    problems = []
    if len(response) < 5:
        problems.append("Response is empty or nearly empty.")
    lowered = response.lower()
    for marker in TRUNCATION_MARKERS:
        if lowered.rstrip().endswith(marker.lower()) or (marker == "TODO" and "TODO" in response):
            problems.append(f"Response appears truncated or unfinished (ends with/contains {marker!r}).")
            break
    # Sub-questions coverage: count explicit question marks in the prompt
    asked = len(re.findall(r"\?", prompt))
    if asked >= 2:
        # Crude check: response should be at least ~20 chars per question asked
        if len(response) < asked * 20:
            problems.append(
                f"Prompt asks {asked} questions but the response is very short ({len(response)} chars); "
                "may not address all sub-questions."
            )
    passed = not problems
    return CheckOutcome(rule_id, rule_name, "completeness", passed,
                        value={"length": len(response), "questions_in_prompt": asked},
                        evidence="No truncation or emptiness signals." if passed else "; ".join(problems),
                        explanation=None if passed else "Response completeness concerns: " + "; ".join(problems),
                        severity=params.get("severity", "medium"))


def check_evidence_citation(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    """Response must cite the provided reference sources ([n] markers or source titles)."""
    sources = record.get("reference_sources") or []
    response = record["response"]
    if not sources:
        return CheckOutcome(rule_id, rule_name, "evidence_citation", None, uncertain=True,
                            signals={"needs_reference": True},
                            evidence="Record has no reference sources to cite.",
                            explanation="Inconclusive: no reference sources available for citation check.")
    citations = CITATION_RE.findall(response)
    bracket_nums = {int(m[0]) for m in citations if m[0].isdigit()}
    inline_names = [m[1] for m in citations if m[1]]
    cited: list[str] = []
    for idx, src in enumerate(sources, start=1):
        title = str(src if isinstance(src, str) else src.get("title", ""))
        if idx in bracket_nums or (title and title.lower() in response.lower()):
            cited.append(title or f"source {idx}")
    min_required = params.get("min_citations", 1)
    passed = len(cited) >= min_required
    return CheckOutcome(rule_id, rule_name, "evidence_citation", passed,
                        value={"cited": cited, "sources": len(sources)},
                        expected=f"at least {min_required} citation(s) from {len(sources)} sources",
                        evidence=f"Cited {len(cited)} of {len(sources)} available sources; bracket citations found: {sorted(bracket_nums)}.",
                        explanation=None if passed else f"Response cites {len(cited)} source(s) but at least {min_required} required.",
                        severity=params.get("severity", "medium"))


CITATION_STRIP_RE = re.compile(r"\[\d+\]|\((\w+,\s*\d{4})\)")


def _numbers_in(text: str) -> list[float]:
    # Citation markers like [1] must not be read as numeric answers.
    text = CITATION_STRIP_RE.sub(" ", text)
    out = []
    for m in NUMBER_RE.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def check_numeric_match(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    """Compare numeric values in the response against reference-answer numbers.

    Passes when no response number conflicts with the reference; a number
    present in the response but absent from the reference is treated as a
    conflict (deterministic signal, severity high).
    """
    reference = record.get("reference_answer")
    if reference is None:
        return CheckOutcome(rule_id, rule_name, "numeric_match", None, uncertain=True,
                            signals={"needs_reference": True},
                            evidence="No reference_answer on record.",
                            explanation="Inconclusive: no reference answer to compare against.")
    ref_nums = _numbers_in(str(reference))
    resp_nums = _numbers_in(record["response"])
    if not ref_nums:
        return CheckOutcome(rule_id, rule_name, "numeric_match", None, uncertain=True,
                            signals={"needs_reference": True},
                            evidence="Reference answer contains no numbers to compare.",
                            explanation="Inconclusive: reference answer has no numeric value.")
    if not resp_nums:
        return CheckOutcome(rule_id, rule_name, "numeric_match", False,
                            value=None, expected=ref_nums,
                            evidence="Response contains no numbers but reference expects one.",
                            explanation="No numeric answer found in response.",
                            severity=params.get("severity", "high"))
    tolerance = params.get("tolerance", 0.0)
    conflicts = [n for n in resp_nums if not any(abs(n - r) <= tolerance for r in ref_nums)]
    passed = not conflicts
    return CheckOutcome(rule_id, rule_name, "numeric_match", passed,
                        value={"response_numbers": resp_nums[:10], "conflicting": conflicts[:10]},
                        expected=f"no conflicts with reference numbers {ref_nums[:10]}",
                        evidence=(
                            f"Response numbers: {resp_nums[:10]}; reference numbers: {ref_nums[:10]}; "
                            + (f"conflicting values: {conflicts[:10]} (tolerance {tolerance})."
                               if conflicts else "no conflicting values.")
                        ),
                        explanation=None if passed else f"Numbers {conflicts[:10]} in the response do not appear in the reference answer (tolerance {tolerance}).",
                        severity=params.get("severity", "high"))


STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "this", "by", "at", "from", "or", "an",
    "has", "have", "had", "not", "no", "but", "we", "you", "they", "he", "she", "i",
    "there", "which", "what", "who", "when", "where", "why", "how", "can", "could",
    "will", "would", "should", "may", "might", "must", "do", "does", "did", "so", "if",
    "its", "their", "our", "your", "my", "me", "him", "her", "them", "us",
}


def check_reference_overlap(record: dict, params: dict, rule_id: str, rule_name: str) -> CheckOutcome:
    """Token-overlap heuristic between response and reference answer.

    This is a lexical similarity signal — NOT proof of factual correctness.
    """
    reference = record.get("reference_answer")
    if not reference:
        return CheckOutcome(rule_id, rule_name, "reference_overlap", None, uncertain=True,
                            signals={"needs_reference": True},
                            evidence="No reference_answer on record.",
                            explanation="Inconclusive: no reference answer available.")
    ref_terms = {w for w in _words(str(reference)) if w not in STOPWORDS}
    resp_terms = {w for w in _words(record["response"]) if w not in STOPWORDS}
    if not ref_terms:
        return CheckOutcome(rule_id, rule_name, "reference_overlap", None, uncertain=True,
                            signals={"needs_reference": True},
                            evidence="Reference answer has no comparable terms.",
                            explanation="Inconclusive: reference answer has no comparable terms.")
    overlap = resp_terms & ref_terms
    ratio = len(overlap) / len(ref_terms)
    support_threshold = params.get("support_threshold", 0.5)
    passed = ratio >= support_threshold
    return CheckOutcome(rule_id, rule_name, "reference_overlap", passed,
                        value=round(ratio, 3), expected=f">= {support_threshold}",
                        evidence=(
                            f"Lexical overlap with reference: {len(overlap)}/{len(ref_terms)} reference terms "
                            f"({ratio:.0%}) present in response. This is a lexical similarity heuristic, "
                            "not proof of factual accuracy."
                        ),
                        explanation=None if passed else
                        f"Only {ratio:.0%} of reference-answer key terms appear in the response "
                        f"(threshold {support_threshold:.0%}).",
                        severity=params.get("severity", "medium"),
                        signals={"overlap_ratio": ratio})


CHECK_REGISTRY = {
    "format_regex": check_format_regex,
    "json_valid": check_json_valid,
    "min_words": lambda r, p, rid, rn: _length_check(r, p, rid, rn, "min_words", "min", 1),
    "max_words": lambda r, p, rid, rn: _length_check(r, p, rid, rn, "max_words", "max", 10000),
    "min_chars": lambda r, p, rid, rn: _length_check(r, p, rid, rn, "min_chars", "min", 1),
    "max_chars": lambda r, p, rid, rn: _length_check(r, p, rid, rn, "max_chars", "max", 100000),
    "sentence_count": check_sentence_count,
    "required_keywords": check_required_keywords,
    "forbidden_patterns": check_forbidden_patterns,
    "required_fields": check_required_fields,
    "completeness": check_completeness,
    "evidence_citation": check_evidence_citation,
    "numeric_match": check_numeric_match,
    "reference_overlap": check_reference_overlap,
}


def run_check(record: dict, check: dict, criterion_id: str | None) -> CheckOutcome:
    ctype = check.get("type")
    fn = CHECK_REGISTRY.get(ctype)
    if fn is None:
        return CheckOutcome(
            rule_id=check.get("rule_id", ctype or "unknown"),
            rule_name=check.get("name", ctype or "Unknown check"),
            check_type=ctype or "unknown", passed=None, uncertain=True,
            explanation=f"Unknown check type '{ctype}'.",
        )
    rule_id = check.get("rule_id", f"{criterion_id or 'c'}.{ctype}")
    rule_name = check.get("name", ctype.replace("_", " ").title())
    return fn(record, check.get("params", {}) or {}, rule_id, rule_name)
