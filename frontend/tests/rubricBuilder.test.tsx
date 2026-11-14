import { describe, expect, it } from "vitest";
import { emptyRubric, parseRubricJson, weightSum } from "@/lib/rubricBuilder";
import { fmtPct } from "@/lib/utils";

describe("rubricBuilder", () => {
  it("creates an empty rubric with one criterion and normalized defaults", () => {
    const r = emptyRubric();
    expect(r.criteria).toHaveLength(1);
    expect(r.passing_threshold).toBe(0.7);
    expect(r.borderline_rules?.confidence_below).toBe(0.6);
    expect(r.human_review_policy?.when_borderline).toBe(true);
  });

  it("parses valid rubric JSON and fills defaults", () => {
    const r = parseRubricJson(JSON.stringify({
      name: "Test",
      criteria: [{ id: "a", name: "A", weight: 1, checks: [{ type: "completeness" }] }],
    }));
    expect(r.criteria[0].pass_threshold).toBe(1);
    expect(r.criteria[0].scoring_scale.type).toBe("binary");
    expect(r.criteria[0].checks[0].type).toBe("completeness");
  });

  it("rejects JSON without a criteria array", () => {
    expect(() => parseRubricJson('{"name": "no criteria"}')).toThrow(/criteria/i);
    expect(() => parseRubricJson("not json at all")).toThrow();
  });

  it("computes weight sums for the UI hint", () => {
    const r = emptyRubric();
    r.criteria.push({ ...r.criteria[0], id: "b", weight: 2 });
    expect(weightSum(r)).toBe(3);
  });
});

describe("fmtPct", () => {
  it("formats rates and handles nulls", () => {
    expect(fmtPct(0.9231)).toBe("92.3%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtPct(undefined)).toBe("—");
  });
});
