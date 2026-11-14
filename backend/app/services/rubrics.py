"""Rubric definition validation and version management.

A rubric definition is plain JSON:
{
  "name": str,
  "description": str,
  "criteria": [
    {
      "id": "format",                      # unique within rubric
      "name": "Format compliance",
      "description": str,
      "weight": 0.25,                      # > 0; weights of all criteria should sum to ~1
      "scoring_scale": {
        "type": "binary" | "likert",
        "min": 0, "max": 1,                # for likert e.g. 0..4
        "labels": {"0": "...", "1": "..."} # optional descriptive labels
      },
      "pass_threshold": 1,                 # score >= threshold counts as passing for the criterion
      "checks": [ {"type": "...", "params": {...}, "name": "...", "severity": "..."} ],
      "human_review_required": false,
      "expected_evidence": str | None
    }
  ],
  "passing_threshold": 0.7,               # weighted aggregate score >= 0.7 -> pass
  "borderline_rules": {"confidence_below": 0.6, "score_margin": 0.08,
                        "categories_enabled": [...]},
  "human_review_policy": {"when_borderline": true, "when_failed": false,
                           "sample_failed_pct": 0},
  "examples": [ {"prompt": ..., "response": ..., "expected_outcome": ...} ],
  "expected_evidence": str,
  "borderline_conditions": str
}
"""
from typing import Any

VALID_CHECK_TYPES = {
    "format_regex", "json_valid", "min_words", "max_words", "min_chars", "max_chars",
    "sentence_count", "required_keywords", "forbidden_patterns", "required_fields",
    "completeness", "evidence_citation", "numeric_match", "reference_overlap",
}
VALID_SCALE_TYPES = {"binary", "likert"}

# --- evaluation form (what testers fill in) ---------------------------------
FORM_FIELD_TYPES = {"yes_no", "single_select", "multi_select", "numeric", "likert", "text", "evidence"}


def _validate_form_section(definition: dict, errors: list, warnings: list) -> None:
    form = definition.get("form")
    if form is None:
        return
    if not isinstance(form, dict) or not isinstance(form.get("fields"), list) or not form["fields"]:
        errors.append(_issue("error", "form.fields", "form must be an object with a non-empty 'fields' list."))
        return
    seen_ids: set[str] = set()
    fields = form["fields"]
    for i, f in enumerate(fields):
        path = f"form.fields[{i}]"
        if not isinstance(f, dict):
            errors.append(_issue("error", path, "Field must be an object."))
            continue
        fid = f.get("id")
        if not fid or not isinstance(fid, str):
            errors.append(_issue("error", f"{path}.id", "Field id is required and must be a string."))
        elif fid in seen_ids:
            errors.append(_issue("error", f"{path}.id", f"Duplicate form field id '{fid}'."))
        else:
            seen_ids.add(fid)
        if not f.get("label"):
            errors.append(_issue("error", f"{path}.label", "Field label is required."))
        ftype = f.get("type")
        if ftype not in FORM_FIELD_TYPES:
            errors.append(_issue("error", f"{path}.type", f"Field type must be one of {sorted(FORM_FIELD_TYPES)}."))
        elif ftype in ("single_select", "multi_select") and not isinstance(f.get("options"), list):
            errors.append(_issue("error", f"{path}.options", "Select fields need an options list."))
        if ftype in ("numeric", "likert"):
            scale = f.get("scale") or {}
            if not isinstance(scale.get("min"), int) or not isinstance(scale.get("max"), int) or scale["min"] >= scale["max"]:
                errors.append(_issue("error", f"{path}.scale", "Numeric/likert fields need integer scale min < max."))
        cond = f.get("conditional_on")
        if cond is not None:
            if not isinstance(cond, dict) or not cond.get("field_id") or not isinstance(cond.get("values"), list):
                errors.append(_issue("error", f"{path}.conditional_on", "conditional_on needs {field_id, values}."))
            elif cond["field_id"] not in seen_ids:
                errors.append(_issue("error", f"{path}.conditional_on", "conditional_on must reference an EARLIER field id."))
    # default required-field list = all required fields
    if definition.get("required_fields") is None:
        definition["required_fields"] = [f["id"] for f in fields if isinstance(f, dict) and f.get("required")]
BORDERLINE_CATEGORIES = {
    "partially_correct", "evidence_insufficient", "context_misleading",
    "ambiguous_instruction", "conflicting_evidence", "reviewer_disagreement",
    "uncertain_automated_decision",
}


def _issue(level: str, path: str, message: str) -> dict[str, str]:
    return {"level": level, "path": path, "message": message}


def validate_rubric_definition(definition: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(definition, dict):
        return {"valid": False, "errors": [_issue("error", "$", "Rubric definition must be a JSON object.")], "warnings": warnings}

    if not definition.get("name"):
        errors.append(_issue("error", "name", "Rubric name is required."))
    if not isinstance(definition.get("criteria"), list) or len(definition["criteria"]) == 0:
        errors.append(_issue("error", "criteria", "At least one criterion is required."))
        criteria = []
    else:
        criteria = definition["criteria"]

    seen_ids: set[str] = set()
    weight_sum = 0.0
    for i, crit in enumerate(criteria):
        path = f"criteria[{i}]"
        if not isinstance(crit, dict):
            errors.append(_issue("error", path, "Criterion must be an object."))
            continue
        cid = crit.get("id")
        if not cid or not isinstance(cid, str):
            errors.append(_issue("error", f"{path}.id", "Criterion id is required and must be a string."))
        elif cid in seen_ids:
            errors.append(_issue("error", f"{path}.id", f"Duplicate criterion id '{cid}'."))
        else:
            seen_ids.add(cid)
        if not crit.get("name"):
            errors.append(_issue("error", f"{path}.name", "Criterion name is required."))

        weight = crit.get("weight")
        if weight is None:
            errors.append(_issue("error", f"{path}.weight", "Criterion weight is required."))
        elif not isinstance(weight, (int, float)) or weight <= 0:
            errors.append(_issue("error", f"{path}.weight", "Weight must be a positive number."))
        else:
            weight_sum += weight

        scale = crit.get("scoring_scale") or {}
        stype = scale.get("type")
        if stype not in VALID_SCALE_TYPES:
            errors.append(_issue("error", f"{path}.scoring_scale.type", f"Scale type must be one of {sorted(VALID_SCALE_TYPES)}."))
        else:
            if stype == "binary":
                smin, smax = scale.get("min", 0), scale.get("max", 1)
                if smin != 0 or smax != 1:
                    errors.append(_issue("error", f"{path}.scoring_scale", "Binary scale must have min=0 and max=1."))
            if stype == "likert":
                smin, smax = scale.get("min"), scale.get("max")
                if not isinstance(smin, int) or not isinstance(smax, int) or smin >= smax:
                    errors.append(_issue("error", f"{path}.scoring_scale", "Likert scale requires integer min < max."))

        threshold = crit.get("pass_threshold")
        if threshold is None:
            errors.append(_issue("error", f"{path}.pass_threshold", "pass_threshold is required."))
        elif not isinstance(threshold, (int, float)):
            errors.append(_issue("error", f"{path}.pass_threshold", "pass_threshold must be numeric."))
        else:
            smin = scale.get("min", 0)
            smax = scale.get("max", 1 if stype == "binary" else None)
            if stype == "binary" and threshold not in (0, 1):
                errors.append(_issue("error", f"{path}.pass_threshold", "Binary pass_threshold must be 0 or 1."))
            if stype == "likert" and isinstance(smin, int) and isinstance(smax, int) and not (smin <= threshold <= smax):
                errors.append(_issue("error", f"{path}.pass_threshold", f"pass_threshold must be between {smin} and {smax}."))

        checks = crit.get("checks")
        if not isinstance(checks, list) or len(checks) == 0:
            errors.append(_issue("error", f"{path}.checks", "At least one automatic check is required."))
        else:
            for j, check in enumerate(checks):
                cpath = f"{path}.checks[{j}]"
                if not isinstance(check, dict) or check.get("type") not in VALID_CHECK_TYPES:
                    errors.append(_issue("error", f"{cpath}.type", f"Unknown check type; must be one of {sorted(VALID_CHECK_TYPES)}."))
                params = check.get("params", {}) if isinstance(check, dict) else {}
                if not isinstance(params, dict):
                    errors.append(_issue("error", f"{cpath}.params", "params must be an object."))

    if criteria and weight_sum > 0 and abs(weight_sum - 1.0) > 0.001:
        warnings.append(_issue("warning", "criteria.weights", f"Weights sum to {weight_sum:.3f}; they will be normalized to 1.0."))

    pt = definition.get("passing_threshold")
    if pt is None:
        errors.append(_issue("error", "passing_threshold", "passing_threshold (0..1) is required."))
    elif not isinstance(pt, (int, float)) or not (0 <= pt <= 1):
        errors.append(_issue("error", "passing_threshold", "passing_threshold must be between 0 and 1."))

    brules = definition.get("borderline_rules", {})
    if brules:
        cb = brules.get("confidence_below")
        if cb is not None and (not isinstance(cb, (int, float)) or not (0 <= cb <= 1)):
            errors.append(_issue("error", "borderline_rules.confidence_below", "Must be between 0 and 1."))
        margin = brules.get("score_margin")
        if margin is not None and (not isinstance(margin, (int, float)) or not (0 <= margin <= 0.5)):
            errors.append(_issue("error", "borderline_rules.score_margin", "Must be between 0 and 0.5."))
        cats = brules.get("categories_enabled")
        if cats is not None:
            if not isinstance(cats, list):
                errors.append(_issue("error", "borderline_rules.categories_enabled", "Must be a list."))
            else:
                unknown = [c for c in cats if c not in BORDERLINE_CATEGORIES]
                if unknown:
                    errors.append(_issue("error", "borderline_rules.categories_enabled", f"Unknown categories: {unknown}."))

    policy = definition.get("human_review_policy", {})
    if policy:
        for key in ("when_borderline", "when_failed"):
            if key in policy and not isinstance(policy[key], bool):
                errors.append(_issue("error", f"human_review_policy.{key}", "Must be a boolean."))
        pct = policy.get("sample_failed_pct")
        if pct is not None and (not isinstance(pct, (int, float)) or not (0 <= pct <= 100)):
            errors.append(_issue("error", "human_review_policy.sample_failed_pct", "Must be between 0 and 100."))

    examples = definition.get("examples", [])
    if examples and not isinstance(examples, list):
        errors.append(_issue("error", "examples", "examples must be a list."))

    _validate_form_section(definition, errors, warnings)

    # Reference-based checks require reference data; warn when they may never fire.
    for i, crit in enumerate(criteria):
        for j, check in enumerate(crit.get("checks", []) or []):
            if isinstance(check, dict) and check.get("type") in {"numeric_match", "reference_overlap", "evidence_citation"}:
                warnings.append(_issue(
                    "warning", f"criteria[{i}].checks[{j}].type",
                    f"Check '{check.get('type')}' needs reference data (reference_answer / reference_sources); "
                    "records without it are marked inconclusive and can trigger borderline routing.",
                ))

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def normalize_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults so the engine always has consistent fields."""
    d = dict(definition)
    d.setdefault("description", "")
    d.setdefault("borderline_rules", {})
    d["borderline_rules"].setdefault("confidence_below", 0.6)
    d["borderline_rules"].setdefault("score_margin", 0.08)
    d["borderline_rules"].setdefault(
        "categories_enabled",
        sorted(BORDERLINE_CATEGORIES - {"reviewer_disagreement"}),
    )
    d.setdefault("human_review_policy", {})
    d["human_review_policy"].setdefault("when_borderline", True)
    d["human_review_policy"].setdefault("when_failed", False)
    d["human_review_policy"].setdefault("sample_failed_pct", 0)
    d.setdefault("examples", [])
    d.setdefault("expected_evidence", None)
    d.setdefault("borderline_conditions", None)
    return d
