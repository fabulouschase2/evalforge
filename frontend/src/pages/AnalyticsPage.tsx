import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Info } from "lucide-react";
import { queries } from "@/api/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import { NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { BORDERLINE_CATEGORIES, type EvaluationRun } from "@/lib/types";
import { fmtNum, fmtPct } from "@/lib/utils";

function MetricCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-fg-muted">{label}</div>
        <div className={`mt-1 text-2xl font-bold ${tone ?? "text-fg"}`}>{value}</div>
        {hint && <div className="mt-1 text-[11px] leading-snug text-fg-muted">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const evaluations = useQuery(queries.evaluations());
  const [runIdStr, setRunIdStr] = useState("");
  const runId = runIdStr ? Number(runIdStr) : undefined;

  const metrics = useQuery(queries.metrics(runId));
  const agreement = useQuery(queries.agreement(runId));
  const confusion = useQuery(queries.confusionMatrix(runId));

  const loading = metrics.isLoading || agreement.isLoading;
  const isError = metrics.isError || agreement.isError;

  const failureData = Object.entries(metrics.data?.failure_categories ?? {}).map(([k, v]) => ({
    short: (BORDERLINE_CATEGORIES[k] ?? k.replace(/_/g, " ")).split(" ").map((w) => w.slice(0, 9)).join(" "),
    name: BORDERLINE_CATEGORIES[k] ?? k.replace(/_/g, " "),
    count: v,
  }));

  const insufficient = metrics.data?.insufficient_reason;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Analytics</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Statistical evaluation computed server-side with scikit-learn / SciPy. Metrics that require
            gold-standard labels are reported as unavailable when data is insufficient.
          </p>
        </div>
        <NativeSelect
          aria-label="Scope analytics to a run"
          className="w-72"
          value={runIdStr}
          onChange={(e) => setRunIdStr(e.target.value)}
        >
          <option value="">All runs</option>
          {(evaluations.data as EvaluationRun[] | undefined)?.map((r) => (
            <option key={r.id} value={r.id}>#{r.id} — {r.name}</option>
          ))}
        </NativeSelect>
      </div>

      {loading ? (
        <TableSkeleton rows={6} cols={4} />
      ) : isError ? (
        <ErrorState message={(metrics.error as Error)?.message} retry={metrics.refetch} />
      ) : (
        <>
          {/* Gold-label metrics */}
          <Card>
            <CardHeader>
              <CardTitle>Automated vs. gold standard</CardTitle>
              <CardDescription>
                Binary classification of automated decisions against gold labels (pass/fail). Borderline
                results are excluded from binary metrics by design.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {insufficient ? (
                <div className="flex items-start gap-2.5 rounded-md border border-info/40 bg-[rgba(96,165,250,0.07)] px-4 py-3 text-sm text-info">
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <strong>Metric unavailable:</strong> {insufficient}
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
                  <MetricCard label="Accuracy" value={fmtPct(metrics.data!.accuracy)} hint="Overall agreement with gold labels" />
                  <MetricCard label="Precision" value={fmtPct(metrics.data!.precision)} hint="Of automated passes, how many were truly correct" />
                  <MetricCard label="Recall" value={fmtPct(metrics.data!.recall)} hint="Of truly correct records, how many passed" />
                  <MetricCard label="F1 score" value={fmtNum(metrics.data!.f1)} hint="Harmonic mean of precision and recall" />
                  <MetricCard label="Cohen's κ" value={fmtNum(metrics.data!.cohen_kappa)} hint="Chance-adjusted agreement vs. gold labels"
                    tone={metrics.data!.cohen_kappa === null ? "text-fg-muted" : undefined} />
                  <MetricCard label="Gold-labeled records" value={String(metrics.data!.gold_labeled_count)} hint="Sample size for the metrics above" />
                </div>
              )}

              {metrics.data!.kappa_note && (
                <p className="text-xs italic text-fg-muted">{metrics.data!.kappa_note}</p>
              )}

              {/* Confusion matrix */}
              {confusion.data && !confusion.data.reason && confusion.data.labels.length > 0 && (
                <div>
                  <div className="mb-2 text-sm font-semibold text-fg">Confusion matrix (rows = gold, cols = automated)</div>
                  <Table className="max-w-sm">
                    <THead>
                      <TR>
                        <TH />
                        {confusion.data.labels.map((l) => <TH key={l}>pred {l}</TH>)}
                      </TR>
                    </THead>
                    <TBody>
                      {confusion.data.matrix.map((row, i) => (
                        <TR key={i}>
                          <TD className="font-medium text-fg-muted">gold {confusion.data!.labels[i]}</TD>
                          {row.map((v, j) => (
                            <TD key={j}>
                              <span className={`rounded px-2 py-1 font-mono text-sm ${
                                i === j ? "bg-[rgba(34,197,94,0.12)] text-ok" : "bg-[rgba(239,68,68,0.12)] text-danger"
                              }`}>
                                {v}
                              </span>
                            </TD>
                          ))}
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </div>
              )}
              {confusion.data?.reason && (
                <p className="text-xs italic text-fg-muted">{confusion.data.reason}</p>
              )}
            </CardContent>
          </Card>

          {/* Inter-annotator agreement */}
          <Card>
            <CardHeader>
              <CardTitle>Reviewer agreement</CardTitle>
              <CardDescription>
                Raw percentage agreement vs. chance-adjusted agreement (Fleiss' kappa). These are different
                measures — never confuse the two.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
                <MetricCard label="Raw agreement" value={fmtPct(agreement.data!.raw_agreement_rate)}
                  hint="Items where all reviewers chose the same label" />
                <MetricCard label="Fleiss' κ" value={fmtNum(agreement.data!.fleiss_kappa)}
                  hint="Chance-adjusted agreement across raters" />
                <MetricCard label="Multi-review items" value={String(agreement.data!.items_with_multiple_reviews)}
                  hint="Results with ≥ 2 submitted reviews" />
                <MetricCard label="Disagreement items" value={String(agreement.data!.disagreement_items)}
                  hint="Require adjudication" tone={agreement.data!.disagreement_items > 0 ? "text-warn" : undefined} />
                <MetricCard label="Reviewers" value={String(agreement.data!.reviewer_count)} />
              </div>
              {agreement.data!.note && (
                <div className="flex items-start gap-2.5 rounded-md border border-info/40 bg-[rgba(96,165,250,0.07)] px-4 py-3 text-sm text-info">
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>{agreement.data!.note}</div>
                </div>
              )}
              {agreement.data!.fleiss_kappa !== null && agreement.data!.fleiss_kappa < 0 && (
                <p className="text-xs italic text-fg-muted">
                  Negative kappa means observed agreement is below what chance would predict — common with
                  very few items or planted disagreement. Interpret with the raw rate.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Distribution + run quality */}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Failure &amp; uncertainty distribution</CardTitle>
                <CardDescription>Borderline categories across evaluated records in scope.</CardDescription>
              </CardHeader>
              <CardContent className="h-[260px]">
                {failureData.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-fg-muted">No borderline categories in scope.</div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={failureData} margin={{ top: 4, right: 8, left: -18, bottom: 26 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#34414C" vertical={false} />
                      <XAxis dataKey="short" tick={{ fill: "#94A3B8", fontSize: 10 }} angle={-22} textAnchor="end" interval={0} height={56} />
                      <YAxis allowDecimals={false} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                      <Tooltip
                        cursor={{ fill: "rgba(22,184,166,0.08)" }}
                        contentStyle={{ background: "#18232D", border: "1px solid #34414C", borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: "#E5E7EB" }}
                      />
                      <Bar dataKey="count" radius={[4, 4, 0, 0]} fill="#16B8A6">
                        {failureData.map((_, i) => <Cell key={i} fill={["#16B8A6", "#60A5FA", "#F59E0B", "#EF4444", "#A78BFA", "#22C55E", "#F472B6"][i % 7]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Run-level quality</CardTitle>
                <CardDescription>Aggregates in scope: pass rate, average score, borderline routing.</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4">
                <MetricCard label="Pass rate" value={fmtPct(metrics.data!.pass_rate)} />
                <MetricCard label="Average score" value={fmtNum(metrics.data!.avg_score)} />
                <MetricCard label="Borderline rate" value={fmtPct(metrics.data!.borderline_rate)}
                  hint="Routed to human review rather than auto-classified" tone="text-warn" />
                <MetricCard label="Failure categories" value={String(Object.keys(metrics.data!.failure_categories).length)} />
                {runId && <Badge variant="neutral" className="col-span-2">Scoped to run #{runId}</Badge>}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
