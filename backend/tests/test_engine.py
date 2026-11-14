"""Deterministic evaluation checks, scoring and borderline classification (unit level)."""
from app.engine import borderline as bl
from app.engine.checks import run_check
from app.engine.factuality import analyze_factuality
from app.engine.scoring import compute_confidence, score_record
from app.services.rubrics import normalize_definition


def rec(record_id="r1", prompt="What is 2+2?", response="2+2 equals 4.",
        reference="2+2 equals 4.", sources=None, expected=None):
    """Engine checks operate on plain dicts (the normalized record shape)."""
    return {
        "record_id": record_id, "prompt": prompt, "response": response,
        "reference_answer": reference, "reference_sources": sources or [],
        "expected_label": expected, "metadata": {},
    }


# ------------------------------------------------------------- individual checks

def test_format_regex():
    r = rec(response="Answer: 4")
    out = run_check(r, {"type": "format_regex", "params": {"pattern": r"^Answer:"}}, "c1")
    assert out.passed is True
    out2 = run_check(rec(response="4"), {"type": "format_regex", "params": {"pattern": r"^Answer:"}}, "c1")
    assert out2.passed is False


def test_json_valid_check():
    ok = run_check(rec(response='{"a": 1, "b": 2}'), {"type": "json_valid", "params": {"required_keys": ["a", "b"]}}, "c1")
    assert ok.passed is True
    bad = run_check(rec(response="{'a': 1}"), {"type": "json_valid", "params": {}}, "c1")
    assert bad.passed is False


def test_sentence_count():
    r = rec(response="One sentence here. Two sentences now.")
    out = run_check(r, {"type": "sentence_count", "params": {"min": 1, "max": 3}}, "c1")
    assert out.passed is True and out.value == 2
    out2 = run_check(r, {"type": "sentence_count", "params": {"max": 1}}, "c1")
    assert out2.passed is False


def test_required_keywords_modes():
    r = rec(response="The refund window is 30 days and shipping is free.")
    all_mode = run_check(r, {"type": "required_keywords", "params": {"keywords": ["refund", "shipping"], "mode": "all"}}, "c1")
    assert all_mode.passed is True
    all_fail = run_check(r, {"type": "required_keywords", "params": {"keywords": ["refund", "warranty"], "mode": "all"}}, "c1")
    assert all_fail.passed is False
    any_mode = run_check(r, {"type": "required_keywords", "params": {"keywords": ["warranty", "shipping"], "mode": "any"}}, "c1")
    assert any_mode.passed is True


def test_forbidden_patterns():
    out = run_check(rec(response="Click here: http://spam.example"), {"type": "forbidden_patterns", "params": {"patterns": [r"https?://"]}}, "c1")
    assert out.passed is False and out.severity == "high"


def test_required_fields():
    out = run_check(rec(response="Summary: good\nDetails: fine"), {"type": "required_fields", "params": {"fields": ["Summary", "Details"]}}, "c1")
    assert out.passed is True
    out2 = run_check(rec(response="Summary: good"), {"type": "required_fields", "params": {"fields": ["Summary", "Details"]}}, "c1")
    assert out2.passed is False and out2.value["missing"] == ["Details"]


def test_completeness_detects_truncation():
    out = run_check(rec(response="The answer starts well and then it just..."), {"type": "completeness", "params": {}}, "c1")
    assert out.passed is False
    ok = run_check(rec(response="A complete answer with a conclusion."), {"type": "completeness", "params": {}}, "c1")
    assert ok.passed is True


def test_evidence_citation_needs_sources():
    out = run_check(rec(sources=[]), {"type": "evidence_citation", "params": {}}, "c1")
    assert out.passed is None and out.uncertain  # inconclusive without sources
    cited = run_check(rec(sources=["Policy v1"], response="Per the policy [1], refunds take 30 days."),
                      {"type": "evidence_citation", "params": {"min_citations": 1}}, "c1")
    assert cited.passed is True
    uncited = run_check(rec(sources=["Policy v1"], response="Refunds take 30 days."),
                        {"type": "evidence_citation", "params": {"min_citations": 1}}, "c1")
    assert uncited.passed is False


def test_numeric_match_conflicts():
    out = run_check(rec(reference="The fee is 10 dollars.", response="The fee is 20 dollars."),
                    {"type": "numeric_match", "params": {}}, "c1")
    assert out.passed is False
    ok = run_check(rec(reference="The fee is 10 dollars.", response="The fee is 10 dollars [1]."),
                   {"type": "numeric_match", "params": {}}, "c1")
    assert ok.passed is True  # citation marker [1] must not count as a number
    no_ref = run_check(rec(reference=None), {"type": "numeric_match", "params": {}}, "c1")
    assert no_ref.passed is None and no_ref.uncertain


def test_reference_overlap():
    out = run_check(rec(reference="Paris is the capital of France.", response="The capital of France is Paris."),
                    {"type": "reference_overlap", "params": {"support_threshold": 0.5}}, "c1")
    assert out.passed is True
    miss = run_check(rec(reference="Paris is the capital of France.", response="Berlin is in Germany by the sea."),
                     {"type": "reference_overlap", "params": {"support_threshold": 0.5}}, "c1")
    assert miss.passed is False


def test_inconclusive_never_passes_silently():
    out = run_check(rec(reference=None), {"type": "reference_overlap", "params": {}}, "c1")
    assert out.passed is None


# ------------------------------------------------------------------- scoring

SMALL_RUBRIC = normalize_definition({
    "name": "s", "criteria": [
        {"id": "a", "name": "A", "weight": 0.6, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
        {"id": "b", "name": "B", "weight": 0.4, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
         "checks": [{"type": "completeness"}]},
    ],
    "passing_threshold": 0.6,
})


def _outcome(passed, severity="medium", check_type="completeness"):
    from app.engine.checks import CheckOutcome
    return CheckOutcome(f"x.{check_type}", "X", check_type, passed, severity=severity)


def test_weighted_aggregate_scoring():
    result = score_record(SMALL_RUBRIC, {"a": [_outcome(True)], "b": [_outcome(True)]})
    assert result.aggregate == 1.0 and result.passed

    result = score_record(SMALL_RUBRIC, {"a": [_outcome(True)], "b": [_outcome(False)]})
    assert result.aggregate == 0.6 and result.passed  # 0.6 >= 0.6 threshold

    result = score_record(SMALL_RUBRIC, {"a": [_outcome(False)], "b": [_outcome(True)]})
    assert result.aggregate == 0.4 and not result.passed


def test_critical_failure_dominates_criterion():
    rubric = normalize_definition({
        "name": "s", "criteria": [
            {"id": "a", "name": "A", "weight": 1.0, "scoring_scale": {"type": "likert", "min": 0, "max": 2},
             "pass_threshold": 1,
             "checks": [{"type": "completeness"}, {"type": "numeric_match"}]},
        ],
        "passing_threshold": 0.5,
    })
    # numeric (high severity) failed -> criterion zeroed despite completeness passing
    result = score_record(rubric, {"a": [_outcome(True), _outcome(False, severity="high", check_type="numeric_match")]})
    assert result.criterion_results[0].raw_score == 0.0 and not result.passed


def test_confidence_reduced_by_uncertainty_and_margin():
    rubric = normalize_definition({
        "name": "s", "criteria": [
            {"id": "a", "name": "A", "weight": 1.0, "scoring_scale": {"type": "binary"}, "pass_threshold": 1,
             "checks": [{"type": "completeness"}, {"type": "reference_overlap"}]},
        ],
        "passing_threshold": 0.5,
        "borderline_rules": {"confidence_below": 0.6, "score_margin": 0.05},
    })
    result = score_record(rubric, {"a": [_outcome(True), _outcome(None)]})  # one inconclusive
    confidence, reasons = compute_confidence(rubric, result, {"verdict": "no_reference"})
    assert confidence < 1.0 and len(reasons) >= 2


# ---------------------------------------------------------------- borderline

BASE_KW = dict(aggregate=0.95, confidence=1.0, uncertain_checks=0, failed_checks=0, total_checks=4)


def _factuality(verdict="well_supported", conflicting=0):
    return {"verdict": verdict, "conflicting_number_claims": conflicting}


def test_clear_pass_not_borderline():
    d = bl.classify({}, 0.95, 1.0, _factuality(), {"prompt": "Q?", "reference_sources": []}, 0, 0, 4)
    assert not d.is_borderline


def test_low_confidence_routes_to_uncertain_automated_decision():
    d = bl.classify({}, 0.95, 0.3, _factuality(), {"prompt": "Q?", "reference_sources": []}, 2, 0, 4)
    assert d.is_borderline and d.category == "uncertain_automated_decision"


def test_score_margin_routes_to_partially_correct():
    d = bl.classify({}, 0.64, 1.0, _factuality(), {"prompt": "Q?", "reference_sources": []}, 0, 0, 4)
    # passing_threshold defaults to 0.7; |0.64-0.7|=0.06 < 0.08 margin
    assert d.is_borderline and d.category == "partially_correct"


def test_conflicting_numbers_route_to_conflicting_evidence():
    d = bl.classify({}, 0.95, 1.0, _factuality("needs_verification", conflicting=2),
                    {"prompt": "Q?", "reference_sources": ["s"]}, 0, 0, 4)
    assert d.is_borderline and d.category == "conflicting_evidence"


def test_no_reference_routes_to_evidence_insufficient_when_passing():
    d = bl.classify({}, 0.95, 1.0, _factuality("no_reference"), {"prompt": "Q?", "reference_sources": []}, 0, 0, 4)
    assert d.is_borderline and d.category == "evidence_insufficient"
    assert "not a confirmed correct answer" in d.explanation.lower() or "unverifiable" in d.explanation.lower()


def test_decisive_contradiction_is_not_borderline():
    d = bl.classify({}, 0.4, 1.0, _factuality("contradicted"), {"prompt": "Q?", "reference_sources": ["s"]}, 0, 2, 4)
    assert not d.is_borderline


def test_ambiguous_instruction_detected_only_on_pass():
    d = bl.classify({}, 0.95, 1.0, _factuality(), {"prompt": "Tell me about shipping or whatever makes sense, thanks.", "reference_sources": []}, 0, 0, 4)
    assert d.is_borderline and d.category == "ambiguous_instruction"
    # A clearly failing response is a fail, not a borderline case
    d2 = bl.classify({}, 0.3, 1.0, _factuality(), {"prompt": "Tell me about shipping or whatever makes sense.", "reference_sources": []}, 0, 2, 4)
    assert not d2.is_borderline


def test_review_policy_flags_borderline_only():
    definition = {"human_review_policy": {"when_borderline": True, "when_failed": False}}
    assert bl.review_policy(definition, "fail", True) is True
    assert bl.review_policy(definition, "fail", False) is False
    assert bl.review_policy(definition, "pass", False) is False


# ---------------------------------------------------------------- factuality

def test_factuality_states():
    a = analyze_factuality("Paris is the capital of France.", "Paris is the capital of France.", [])
    assert a["verdict"] == "well_supported"

    b = analyze_factuality("The fee is 20 dollars.", "The fee is 10 dollars.", [])
    assert b["verdict"] == "contradicted"

    c = analyze_factuality("Zebras migrate over the moon.", "Paris is the capital of France.", [])
    assert c["verdict"] in ("unsupported", "needs_verification")

    d = analyze_factuality("Anything at all.", None, [])
    assert d["verdict"] == "no_reference"
    assert "human judgment" in d["note"]

    e = analyze_factuality("The fee is 10 dollars and taxes are 20 percent.", "The fee is 10 dollars.", [])
    assert e["verdict"] in ("needs_verification", "partially_supported")
    assert e["conflicting_number_claims"] >= 1  # 10 matches, 20 conflicts -> deferred, not auto-failed
