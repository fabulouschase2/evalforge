import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlayCircle, UserPlus, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/roles";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ResultDetailDrawer } from "@/components/evaluation/ResultDetailDrawer";
import { fmtDateTime, fmtPct } from "@/lib/utils";
import type { EvaluationResult, EvaluationRun } from "@/lib/types";

export default function EvaluationDetailPage() {
  const { id } = useParams();
  const runId = Number(id);
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const canRun = isStaff(user?.role ?? "");
  const canAssign = isStaff(user?.role ?? "");

  const run = useQuery({ ...queries.evaluation(runId), refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false) });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [openResult, setOpenResult] = useState<EvaluationResult | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [runConfirm, setRunConfirm] = useState(false);
  const [selectedReviewers, setSelectedReviewers] = useState<number[]>([]);

  const filters = useMemo(() => {
    const f: Record<string, string | boolean> = {};
    if (statusFilter) f.status = statusFilter;
    if (reviewFilter) f.needs_review = reviewFilter === "true";
    return f;
  }, [statusFilter, reviewFilter]);

  const results = useQuery(queries.results(runId, page, filters));
  const users = useQuery(queries.users());

  const execute = useMutation({
    mutationFn: () => api.post<EvaluationRun>(`/evaluations/${runId}/run`),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("success", "Evaluation completed", "Automated findings and borderline routing are ready.");
    },
    onError: (e) => toast("error", "Run failed", (e as Error).message),
  });

  const assign = useMutation({
    mutationFn: (reviewerIds: number[]) =>
      api.post<{ created: number }>("/reviews/assign", { reviewer_ids: reviewerIds, result_ids: flaggedIds }),
    onSuccess: (r: { created: number }) => {
      qc.invalidateQueries();
      setAssignOpen(false);
      toast("success", "Reviewers assigned", `${r.created} review assignment(s) created (blind by default).`);
    },
    onError: (e) => toast("error", "Could not assign reviewers", (e as Error).message),
  });

  const flaggedIds = useMemo(
    () => (results.data?.items ?? []).filter((r) => r.needs_review).map((r) => r.id),
    [results.data],
  );

  if (run.isLoading) return <TableSkeleton rows={4} cols={5} />;
  if (run.isError) return <ErrorState message={(run.error as Error)?.message} retry={run.refetch} />;

  const r = run.data;
  if (!r) return null;
  const total = r.passed_count + r.failed_count + r.borderline_count;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-fg">
            {r.name}
            {r.is_demo && <Badge variant="warning">DEMO</Badge>}
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            Dataset{" "}
            <Link to={`/datasets/${r.dataset_id}`} className="text-teal hover:underline">#{r.dataset_id}</Link>
            {" "}· Rubric{" "}
            <Link to={`/rubrics/${r.rubric_id}`} className="text-teal hover:underline">#{r.rubric_id}</Link>
            {" "}· Rubric version {r.rubric_version_id} (pinned) · Dataset version {r.dataset_version_id} (pinned)
          </p>
        </div>
        <div className="flex gap-2">
          {canAssign && r.needs_review_count > 0 && (
            <Button variant="secondary" onClick={() => setAssignOpen(true)}>
              <UserPlus className="h-4 w-4" /> Assign reviewers ({r.needs_review_count} flagged)
            </Button>
          )}
          {canRun && r.status !== "completed" && r.status !== "running" && (
            <Button onClick={() => setRunConfirm(true)} disabled={execute.isPending}>
              <PlayCircle className="h-4 w-4" /> {execute.isPending ? "Running…" : "Run evaluation"}
            </Button>
          )}
          {canRun && r.status === "completed" && (
            <Button variant="ghost" onClick={() => qc.invalidateQueries()} title="Refresh">
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {r.error && (
        <div className="rounded-md border border-danger/40 bg-[rgba(239,68,68,0.08)] px-4 py-3 text-sm text-danger">
          {r.error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Status</div><div className="mt-1.5"><StatusBadge status={r.status} /></div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Records</div><div className="mt-1 text-2xl font-bold text-fg">{r.total_records || "—"}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Pass rate</div><div className="mt-1 text-2xl font-bold text-ok">{total ? fmtPct(r.passed_count / total) : "—"}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Failed</div><div className="mt-1 text-2xl font-bold text-danger">{r.failed_count}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Borderline</div><div className="mt-1 text-2xl font-bold text-warn">{r.borderline_count}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Avg score</div><div className="mt-1 text-2xl font-bold text-fg">{r.avg_score !== null ? r.avg_score.toFixed(2) : "—"}</div></CardContent></Card>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Results</CardTitle>
            <CardDescription>
              Click a row for automated findings, criterion scores, factuality analysis and borderline reasoning.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <select
              aria-label="Filter by status"
              className="h-8 rounded-md border border-border bg-base-panel/60 px-2 text-xs text-fg"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            >
              <option value="">All statuses</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
              <option value="borderline">Borderline</option>
            </select>
            <select
              aria-label="Filter by review flag"
              className="h-8 rounded-md border border-border bg-base-panel/60 px-2 text-xs text-fg"
              value={reviewFilter}
              onChange={(e) => { setReviewFilter(e.target.value); setPage(1); }}
            >
              <option value="">All flags</option>
              <option value="true">Needs review</option>
            </select>
          </div>
        </CardHeader>
        <CardContent>
          {results.isLoading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : results.isError ? (
            <ErrorState message={(results.error as Error)?.message} retry={results.refetch} />
          ) : results.data!.items.length === 0 ? (
            <EmptyState
              icon={PlayCircle}
              title={r.status === "pending" ? "Run not executed yet" : "No results match the filters"}
              description={r.status === "pending" ? "Press “Run evaluation” to execute the deterministic checks." : undefined}
            />
          ) : (
            <>
              <Table>
                <THead>
                  <TR>
                    <TH>Record</TH>
                    <TH>Status</TH>
                    <TH>Score</TH>
                    <TH>Confidence</TH>
                    <TH>Category</TH>
                    <TH>Gold</TH>
                    <TH>Review</TH>
                  </TR>
                </THead>
                <TBody>
                  {results.data!.items.map((res) => (
                    <TR key={res.id} className="cursor-pointer" onClick={() => setOpenResult(res)}>
                      <TD className="font-mono text-xs">{res.record_id}</TD>
                      <TD><StatusBadge status={res.status} /></TD>
                      <TD>{res.score.toFixed(2)}</TD>
                      <TD>{res.confidence.toFixed(2)}</TD>
                      <TD className="text-xs text-fg-muted">{res.borderline_category?.replace(/_/g, " ") ?? "—"}</TD>
                      <TD>{res.gold_label ? <Badge variant={res.gold_label === "pass" ? "success" : res.gold_label === "fail" ? "danger" : "warning"}>{res.gold_label}</Badge> : "—"}</TD>
                      <TD>{res.needs_review ? <Badge variant="warning">needs review</Badge> : ""}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {results.data!.total > 25 && (
                <div className="mt-3 flex items-center justify-between text-sm text-fg-muted">
                  <span>Page {results.data!.page} of {Math.ceil(results.data!.total / 25)}</span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                    <Button variant="outline" size="sm" disabled={page >= Math.ceil(results.data!.total / 25)} onClick={() => setPage((p) => p + 1)}>Next</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Result detail drawer */}
      {openResult && (
        <ResultDetailDrawer
          runId={runId}
          resultId={openResult.id}
          onClose={() => setOpenResult(null)}
        />
      )}

      {/* Assign reviewers dialog */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign independent reviewers</DialogTitle>
            <DialogDescription>
              Each selected reviewer gets a blind assignment for all {flaggedIds.length} flagged results in
              view. Reviewers cannot see each other's assessments until their own is submitted.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {(users.data ?? []).filter((u) => u.id !== user?.id).map((u) => (
              <label key={u.id} className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-2.5 hover:bg-base-panel/50">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[#16B8A6]"
                  onChange={(e) => {
                    setSelectedReviewers((prev) => (e.target.checked ? [...prev, u.id] : prev.filter((x) => x !== u.id)));
                  }}
                />
                <span className="text-sm font-medium text-fg">{u.name}</span>
                <span className="text-xs text-fg-muted">{u.email}</span>
                <Badge variant="neutral" className="ml-auto">{u.role.replace(/_/g, " ")}</Badge>
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>Cancel</Button>
            <Button onClick={() => assign.mutate(selectedReviewers)} disabled={selectedReviewers.length === 0 || assign.isPending}>
              {assign.isPending ? "Assigning…" : `Assign ${selectedReviewers.length} reviewer(s)`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={runConfirm}
        onOpenChange={setRunConfirm}
        title={`Run evaluation "${r.name}"?`}
        description="The deterministic evaluation engine executes every check and stores immutable findings. Completed runs cannot be re-run; create a new run to re-evaluate."
        confirmLabel="Run evaluation"
        busy={execute.isPending}
        onConfirm={() => { setRunConfirm(false); execute.mutate(); }}
      />
    </div>
  );
}
