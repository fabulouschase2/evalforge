// Shared rubric builder logic: default definitions, JSON import/export, validation display.

import type { CheckDefinition, CriterionDefinition, RubricDefinition, ValidationIssue } from "@/lib/types";
import { CHECK_TYPES } from "@/lib/types";

export function emptyCriterion(index: number): CriterionDefinition {
  return {
    id: `criterion_${index + 1}`,
    name: "",
    description: "",
    weight: 1,
    scoring_scale: { type: "binary", min: 0, max: 1 },
    pass_threshold: 1,
    checks: [{ type: "completeness", params: {} }],
    human_review_required: false,
  };
}

export function emptyRubric(): RubricDefinition {
  return {
    name: "",
    description: "",
    criteria: [emptyCriterion(0)],
    passing_threshold: 0.7,
    borderline_rules: { confidence_below: 0.6, score_margin: 0.08 },
    human_review_policy: { when_borderline: true, when_failed: false, sample_failed_pct: 0 },
    examples: [],
    expected_evidence: "",
    borderline_conditions: "",
  };
}

export interface ValidationState {
  valid: boolean | null;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  busy: boolean;
}

export function IssueList({ issues, level }: { issues: ValidationIssue[]; level: "error" | "warning" }) {
  if (issues.length === 0) return null;
  const color = level === "error" ? "text-danger border-danger/40 bg-[rgba(239,68,68,0.07)]"
    : "text-warn border-warn/40 bg-[rgba(245,158,11,0.07)]";
  return (
    <div className={`rounded-md border px-4 py-3 text-sm ${color}`} role={level === "error" ? "alert" : undefined}>
      <ul className="space-y-1">
        {issues.map((i, idx) => (
          <li key={idx}>
            <span className="font-mono text-xs opacity-80">{i.path}</span> — {i.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function weightSum(rubric: RubricDefinition): number {
  return rubric.criteria.reduce((acc, c) => acc + (Number(c.weight) || 0), 0);
}

export function normalizeChecksJson(check: CheckDefinition): CheckDefinition {
  return {
    type: CHECK_TYPES.includes(check.type) ? check.type : "completeness",
    name: check.name,
    rule_id: check.rule_id,
    severity: check.severity,
    params: check.params && typeof check.params === "object" ? check.params : {},
  };
}

/** Parse user-typed JSON into a rubric definition, throwing on structural problems. */
export function parseRubricJson(text: string): RubricDefinition {
  const parsed = JSON.parse(text) as RubricDefinition;
  if (!parsed || typeof parsed !== "object") throw new Error("Rubric JSON must be an object.");
  if (!Array.isArray(parsed.criteria)) throw new Error("Rubric JSON must contain a 'criteria' array.");
  parsed.criteria = parsed.criteria.map((c, i) => ({
    ...c,
    id: c.id ?? `criterion_${i + 1}`,
    name: c.name ?? "",
    weight: Number(c.weight ?? 1),
    scoring_scale: c.scoring_scale ?? { type: "binary", min: 0, max: 1 },
    pass_threshold: Number(c.pass_threshold ?? 1),
    checks: Array.isArray(c.checks) ? c.checks.map(normalizeChecksJson) : [],
  }));
  if (typeof parsed.passing_threshold !== "number") parsed.passing_threshold = 0.7;
  return parsed;
}
