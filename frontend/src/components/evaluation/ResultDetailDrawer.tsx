// Side drawer showing the full automated evaluation for one result.
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { queries } from "@/api/hooks";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CriterionScoresTable, FactualityPanel, ResultFindingsTable } from "./ResultDetailShared";
import { TableSkeleton } from "@/components/ui/states";

export function ResultDetailDrawer({ runId, resultId, onClose }: {
  runId: number;
  resultId: number;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery(queries.result(runId, resultId));

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose} role="presentation">
      <div
        className="h-full w-full max-w-3xl overflow-y-auto border-l border-border bg-base-bg p-5 shadow-2xl scroll-thin"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Evaluation result detail"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-fg">
            Result <span className="font-mono text-sm text-fg-muted">{data?.record_id ?? resultId}</span>
          </h2>
          <button type="button" onClick={onClose} className="rounded p-1.5 text-fg-muted hover:bg-base-panel hover:text-fg" aria-label="Close detail view">
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading && <TableSkeleton rows={8} cols={4} />}
        {isError && <div className="text-danger">{(error as Error).message}</div>}

        {data && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={data.status} />
              <Badge variant="neutral">score {data.score.toFixed(2)}</Badge>
              <Badge variant="neutral">confidence {data.confidence.toFixed(2)}</Badge>
              <Badge variant={data.automated_label === "pass" ? "success" : "danger"}>
                automated: {data.automated_label}
              </Badge>
              {data.gold_label && (
                <Badge variant="info">gold: {data.gold_label}</Badge>
              )}
            </div>

            {data.summary?.confidence_reasons && data.summary.confidence_reasons.length > 0 && (
              <Card>
                <CardHeader><CardTitle>Why this decision?</CardTitle></CardHeader>
                <CardContent>
                  <ul className="list-disc space-y-1 pl-5 text-xs text-fg-muted">
                    {data.summary.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle>Criterion scores</CardTitle>
                <CardDescription>Weighted aggregate: {data.score.toFixed(3)}</CardDescription>
              </CardHeader>
              <CardContent>
                <CriterionScoresTable criteria={data.criterion_scores?.criteria ?? []} />
              </CardContent>
            </Card>

            <FactualityPanel
              factuality={data.factuality}
              borderlineCategory={data.borderline_category}
              borderlineExplanation={data.summary?.borderline_explanation}
              confidenceReasons={data.summary?.confidence_reasons}
              confidence={data.confidence}
            />

            <Card>
              <CardHeader>
                <CardTitle>Automated findings ({data.findings.length})</CardTitle>
                <CardDescription>
                  Every check is stored immutably with rule id, evidence, evaluator and rubric version.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ResultFindingsTable findings={data.findings} />
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
