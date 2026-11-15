// Quality pages: adjudication queue, reviewer consistency, tester quality, agreement.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Scale, Info } from "lucide-react";
import { v2queries, useSubmissionMutations } from "@/api/v2hooks";
import { useToast } from "@/components/ui/toast";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtPct } from "@/lib/utils";

const EMPTY_DECISION = { id: 0, title: null as string | null, counts: {} as Record<string, number> };

function AdjudicationQueuePage() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const queue = useQuery(v2queries.adjudicationQueue(page));
  const [forItem, setForItem] = useState<{ id: number; title: string | null; counts: Record<string, number> } | null>(EMPTY_DECISION);
  const [finalDecision, setFinalDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const mutations = useSubmissionMutations(() => {
    setForItem(null);
    toast("success", "Adjudication recorded", "Original review decisions are preserved.");
  });

  const adjudicate = useMutation({
    mutationFn: () => mutations.adjudicate(forItem!.id, { final_decision: finalDecision, rationale }),
    onError: (e) => toast("error", "Adjudication failed", (e as Error).message),
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Adjudication queue</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Submissions where reviewers disagree or that were escalated. Both original decisions are
          preserved; your final decision is recorded separately.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Conflicting cases ({queue.data?.total ?? 0})</CardTitle></CardHeader>
        <CardContent>
          {queue.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : queue.isError ? (
            <ErrorState message={(queue.error as Error)?.message} retry={queue.refetch} />
          ) : queue.data!.items.length === 0 ? (
            <EmptyState icon={Scale} title="No conflicts to adjudicate"
              description="Reviewer disagreements and escalations appear here automatically." />
          ) : (
            <div className="space-y-2">
              {queue.data!.items.map((s) => (
                <div key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-fg">{s.task_title}</div>
                    <div className="mt-0.5 text-xs text-fg-muted">
                      {s.project_name} · attempt {s.attempt_number} · status {s.status}
                      {Object.entries(s.decision_counts).map(([k, v]) => (
                        <Badge key={k} variant={k === "approved" ? "success" : k === "rejected" ? "danger" : "warning"} className="ml-2">
                          {v}× {k.replace(/_/g, " ")}
                        </Badge>
                      ))}
                      {s.escalated && <Badge variant="danger" className="ml-2">escalated</Badge>}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Link to={`/submissions/${s.id}`} className="text-xs text-teal hover:underline self-center">Inspect</Link>
                    <Button size="sm" onClick={() => { setForItem({ id: s.id, title: s.task_title, counts: s.decision_counts }); setFinalDecision(""); setRationale(""); }}>
                      Adjudicate
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={forItem !== null && forItem.id !== 0} onOpenChange={(o) => !o && setForItem(EMPTY_DECISION)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Adjudicate: {forItem?.title}</DialogTitle>
            <DialogDescription>
              Reviewer decisions: {Object.entries(forItem?.counts ?? {}).map(([k, v]) => `${v}× ${k}`).join(", ") || "none"}.
              Your decision becomes final; the original reviews stay on record.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="adj-decision">Final decision</Label>
              <NativeSelect id="adj-decision" value={finalDecision} onChange={(e) => setFinalDecision(e.target.value)}>
                <option value="">— Select —</option>
                <option value="approved">Approve</option>
                <option value="rejected">Reject</option>
                <option value="revision_requested">Request revisions</option>
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="adj-rationale">Rationale (required)</Label>
              <Textarea id="adj-rationale" className="font-sans text-sm" value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                placeholder="Which reviewer arguments did you adopt and why?" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setForItem(EMPTY_DECISION)}>Cancel</Button>
            <Button onClick={() => adjudicate.mutate()} disabled={!finalDecision || !rationale.trim() || adjudicate.isPending}>
              {adjudicate.isPending ? "Recording…" : "Record adjudication"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReviewerPerformancePage() {
  const { data, isLoading, isError, error, refetch } = useQuery(v2queries.reviewerConsistency());
  if (isLoading) return <TableSkeleton rows={5} cols={5} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-fg">Reviewer performance &amp; consistency</h1>
      <div className="flex items-start gap-2 rounded-md border border-info/40 bg-[rgba(96,165,250,0.07)] px-4 py-3 text-sm text-info">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />{data!.note}
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <THead>
              <TR><TH>Reviewer</TH><TH>Reviews</TH><TH>Decisions</TH><TH>Escalations</TH><TH>Ambiguous flags</TH><TH>Matches adjudication</TH></TR>
            </THead>
            <TBody>
              {data!.reviewers.map((r) => (
                <TR key={r.reviewer_id}>
                  <TD className="font-medium text-fg">{r.name}</TD>
                  <TD>{r.total_reviews}</TD>
                  <TD className="text-xs">{Object.entries(r.decisions).map(([k, v]) => `${v}× ${k.replace(/_/g, " ")}`).join(", ") || "—"}</TD>
                  <TD>{r.escalations}</TD>
                  <TD>{r.ambiguous_flags}</TD>
                  <TD>{r.matches_adjudication === null ? "—" : fmtPct(r.matches_adjudication)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function TesterPerformancePage() {
  const { data, isLoading, isError, error, refetch } = useQuery(v2queries.testerQuality());
  if (isLoading) return <TableSkeleton rows={5} cols={5} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-fg">Tester performance &amp; error analysis</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data!.testers.map((t) => (
          <Card key={t.tester_id}>
            <CardHeader>
              <CardTitle>{t.name}</CardTitle>
              <CardDescription>
                {t.submitted} submissions · {t.resubmissions} resubmissions · approval rate {fmtPct(t.approval_rate)}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex gap-4 text-xs text-fg-muted">
                <span className="text-ok">approved: {t.approved}</span>
                <span className="text-danger">rejected: {t.rejected}</span>
                <span className="text-warn">revisions: {t.revision_required}</span>
              </div>
              {t.recent_feedback.length > 0 && (
                <div className="space-y-1.5">
                  {t.recent_feedback.map((f, i) => (
                    <div key={i} className="rounded border border-border p-2 text-xs text-fg-muted">
                      <Badge variant={f.decision === "rejected" ? "danger" : "warning"}>{f.decision.replace(/_/g, " ")}</Badge>{" "}
                      {f.comments}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      {data!.testers.length === 0 && <EmptyState title="No tester activity yet" />}
    </div>
  );
}

function AgreementAnalysisPage() {
  const { data, isLoading, isError, error, refetch } = useQuery(v2queries.agreement());
  if (isLoading) return <TableSkeleton rows={4} cols={4} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-fg">Inter-annotator agreement</h1>
      <div className="flex items-start gap-2 rounded-md border border-info/40 bg-[rgba(96,165,250,0.07)] px-4 py-3 text-sm text-info">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />{data!.note} Sample size: {data!.items_with_multiple_reviews} items.
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Items with 2+ reviews</div><div className="mt-1 text-2xl font-bold text-fg">{data!.items_with_multiple_reviews}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Full agreement</div><div className="mt-1 text-2xl font-bold text-ok">{data!.full_agreement_items}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Raw agreement</div><div className="mt-1 text-2xl font-bold text-fg">{fmtPct(data!.raw_agreement_rate)}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Fleiss' κ (chance-adjusted)</div><div className="mt-1 text-2xl font-bold text-fg">{data!.fleiss_kappa ?? "—"}</div></CardContent></Card>
      </div>
    </div>
  );
}

export { AdjudicationQueuePage, ReviewerPerformancePage, TesterPerformancePage, AgreementAnalysisPage };
// Default export for React.lazy route splitting (see main.tsx).
export default { AdjudicationQueuePage, ReviewerPerformancePage, TesterPerformancePage, AgreementAnalysisPage };
