// Shared result detail view: findings, criterion scores, factuality, borderline reasoning.
// Used by the evaluation results drawer and the review workspace.

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { BORDERLINE_CATEGORIES, type CriterionScore, type Finding } from "@/lib/types";
import { fmtDateTime } from "@/lib/utils";

export function ResultFindingsTable({ findings }: { findings: Finding[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Rule</TH>
          <TH>Type</TH>
          <TH>Result</TH>
          <TH>Evidence / explanation</TH>
        </TR>
      </THead>
      <TBody>
        {findings.map((f) => (
          <TR key={f.id}>
            <TD className="font-mono text-xs">{f.rule_id}</TD>
            <TD className="text-xs text-fg-muted">{f.check_type}</TD>
            <TD>
              {f.passed === null || f.uncertain
                ? <Badge variant="warning">inconclusive</Badge>
                : f.passed
                  ? <Badge variant="success">pass</Badge>
                  : <Badge variant="danger">fail</Badge>}
              {f.severity === "high" && f.passed === false && <span className="ml-1 text-danger">⚡</span>}
            </TD>
            <TD className="max-w-md text-xs text-fg-muted">
              {f.evidence && <div>{f.evidence}</div>}
              {f.explanation && <div className="mt-0.5 italic text-fg-muted/80">{f.explanation}</div>}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function CriterionScoresTable({ criteria }: { criteria: CriterionScore[] }) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Criterion</TH>
          <TH>Weight</TH>
          <TH>Score</TH>
          <TH>Scale</TH>
          <TH>Passed</TH>
        </TR>
      </THead>
      <TBody>
        {criteria.map((c) => (
          <TR key={c.criterion_id}>
            <TD className="text-sm">{c.name} <span className="font-mono text-xs text-fg-muted">({c.criterion_id})</span></TD>
            <TD>{(c.weight * 100).toFixed(0)}%</TD>
            <TD>{c.raw_score} / {c.scale.max}</TD>
            <TD className="text-xs text-fg-muted">{c.scale.min}–{c.scale.max}</TD>
            <TD>
              {c.passed ? <Badge variant="success">pass</Badge> : <Badge variant="danger">fail</Badge>}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function FactualityPanel({ factuality, borderlineCategory, borderlineExplanation, confidenceReasons, confidence }: {
  factuality: { verdict: string; counts?: Record<string, number>; note?: string } | null;
  borderlineCategory?: string | null;
  borderlineExplanation?: string | null;
  confidenceReasons?: string[];
  confidence?: number;
}) {
  if (!factuality && !borderlineCategory && !confidenceReasons?.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Uncertainty &amp; factuality analysis</CardTitle>
        <CardDescription>
          Heuristic signals the engine used to decide whether this result is trustworthy — not ground truth.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {factuality && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="info">factuality: {factuality.verdict.replace(/_/g, " ")}</Badge>
            {factuality.counts && (
              <span className="text-xs text-fg-muted">
                {Object.entries(factuality.counts).filter(([, v]) => v > 0)
                  .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(" · ")}
              </span>
            )}
          </div>
        )}
        {factuality?.note && <p className="text-xs text-fg-muted italic">{factuality.note}</p>}
        {borderlineCategory && (
          <div className="rounded-md border border-warn/40 bg-[rgba(245,158,11,0.07)] px-3 py-2.5">
            <div className="text-sm font-semibold text-warn">
              Borderline: {BORDERLINE_CATEGORIES[borderlineCategory] ?? borderlineCategory.replace(/_/g, " ")}
            </div>
            {borderlineExplanation && <p className="mt-1 text-xs text-fg-muted">{borderlineExplanation}</p>}
          </div>
        )}
        {confidenceReasons && confidenceReasons.length > 0 && (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
              Automated decision confidence{typeof confidence === "number" ? `: ${confidence.toFixed(2)}` : ""}
            </div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-fg-muted">
              {confidenceReasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function FindingTraceability({ finding }: { finding: Finding }) {
  return (
    <span className="font-mono text-[10px] text-fg-muted/70">
      {finding.evaluator_version} · rubric v{finding.rubric_version} · {fmtDateTime(finding.executed_at)}
    </span>
  );
}
