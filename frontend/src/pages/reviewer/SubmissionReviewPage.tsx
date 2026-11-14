// Review interface: full submission context + decision form (approve/reject/revision).
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Undo2, AlertTriangle, ChevronLeft } from "lucide-react";
import { v2queries, useSubmissionMutations } from "@/api/v2hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Label, Textarea, NativeSelect } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";

export default function SubmissionReviewPage() {
  const { id } = useParams();
  const submissionId = Number(id);
  const toast = useToast();
  const mutations = useSubmissionMutations();
  const sub = useQuery(v2queries.submission(submissionId));

  const [decision, setDecision] = useState("");
  const [comments, setComments] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [ambiguous, setAmbiguous] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const decide = useMutation({
    mutationFn: () => mutations.decide(submissionId, {
      decision, comments: comments || undefined,
      flagged_suspicious: flagged, ambiguous, escalated,
    }),
    onSuccess: () => {
      toast("success", "Decision recorded",
        "The tester has been notified. Original decisions are preserved in history.");
    },
    onError: (e) => toast("error", "Decision failed", (e as Error).message),
  });

  if (sub.isLoading) return <TableSkeleton rows={7} cols={4} />;
  if (sub.isError) return <ErrorState message={(sub.error as Error)?.message} retry={sub.refetch} />;

  const s = sub.data!;
  const decided = s.status === "approved" || s.status === "rejected";
  const canDecide = s.status === "submitted" || s.status === "under_review";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/review-queue" className="text-fg-muted hover:text-fg"><ChevronLeft className="h-4 w-4" /></Link>
            <h1 className="text-xl font-bold text-fg">{s.task_title}</h1>
          </div>
          <p className="mt-1 text-sm text-fg-muted">
            {s.project_name} · attempt {s.attempt_number} · submitted {fmtDateTime(s.submitted_at)}
            {s.blind_review && !s.tester_name && <span className="ml-2 badge">blind review</span>}
          </p>
        </div>
        <StatusBadge status={s.status} />
      </div>

      {s.task_record && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader><CardTitle>Task input</CardTitle></CardHeader>
            <CardContent className="whitespace-pre-wrap text-sm text-fg">{s.task_record.prompt}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>AI response</CardTitle></CardHeader>
            <CardContent className="whitespace-pre-wrap text-sm text-fg">{s.task_record.response}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Reference / evidence</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm text-fg-muted">
              {s.task_record.reference_answer && (
                <div className="whitespace-pre-wrap rounded-md border border-border bg-base-panel/40 p-3">
                  {s.task_record.reference_answer}
                </div>
              )}
              {!s.task_record.reference_answer && <div className="text-xs italic">No reference answer on this record.</div>}
              {s.task_record.supporting_evidence && <div>Evidence: {s.task_record.supporting_evidence}</div>}
              {s.task_record.source_url && (
                <div className="truncate">Source: <a href={s.task_record.source_url} className="text-teal hover:underline" target="_blank" rel="noreferrer">{s.task_record.source_url}</a></div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tester submission</CardTitle>
          <CardDescription>
            {s.tester_name ? `By ${s.tester_name}` : "Tester identity hidden (blind review)"}
            {s.rubric_definition ? ` · rubric version ${s.rubric_version_id}` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {Object.entries(s.payload).map(([k, v]) => (
            <div key={k} className="flex gap-3 rounded-md border border-border p-3">
              <span className="w-44 shrink-0 font-mono text-xs text-fg-muted">{k}</span>
              <span className="min-w-0 flex-1 break-words text-sm text-fg">
                {Array.isArray(v) && v.length === 0 ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}
              </span>
            </div>
          ))}
          {s.explanation && (
            <div className="rounded-md border border-border bg-base-panel/40 p-3 text-sm text-fg">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">Tester explanation</div>
              {s.explanation}
            </div>
          )}
          {(s.evidence ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {s.evidence.map((e, i) => (
                <Badge key={i} variant="info">{e.kind}: {e.value}</Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Decision form */}
      <Card>
        <CardHeader>
          <CardTitle>Your decision</CardTitle>
          <CardDescription>
            Decisions are append-only — they can never be edited or silently overwritten. Conflicting
            reviewer decisions escalate to the quality lead automatically.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {decided ? (
            <div className="rounded-md border border-border bg-base-panel/40 px-4 py-3 text-sm text-fg-muted">
              This submission is finalized ({s.status}). Existing reviews are preserved in history below.
            </div>
          ) : !canDecide ? (
            <div className="rounded-md border border-warn/40 bg-[rgba(245,158,11,0.08)] px-4 py-3 text-sm text-warn">
              This submission is revision_required — it is back with the tester. You can still record an
              additional opinion, which will be preserved for the next decision round.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <NativeSelect aria-label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
                  <option value="">— Select decision —</option>
                  <option value="approved">Approve</option>
                  <option value="rejected">Reject</option>
                  <option value="revision_requested">Request revisions</option>
                </NativeSelect>
                <label className="flex items-center gap-2 text-sm text-fg">
                  <input type="checkbox" className="h-4 w-4 accent-[#16B8A6]" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} />
                  Flag as suspicious
                </label>
                <label className="flex items-center gap-2 text-sm text-fg">
                  <input type="checkbox" className="h-4 w-4 accent-[#16B8A6]" checked={ambiguous} onChange={(e) => setAmbiguous(e.target.checked)} />
                  Mark ambiguous
                </label>
                <label className="flex items-center gap-2 text-sm text-fg">
                  <input type="checkbox" className="h-4 w-4 accent-[#16B8A6]" checked={escalated} onChange={(e) => setEscalated(e.target.checked)} />
                  Escalate to quality lead
                </label>
              </div>
              <div>
                <Label htmlFor="rev-comments">Reviewer comments (required for rejection/revision)</Label>
                <Textarea id="rev-comments" className="font-sans text-sm min-h-[90px]" value={comments}
                  onChange={(e) => setComments(e.target.value)}
                  placeholder="Explain the decision, list concrete issues, and give the tester actionable feedback." />
              </div>
              <div className="flex justify-end">
                <Button onClick={() => setConfirmOpen(true)} disabled={!decision || decide.isPending}>
                  Record decision
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Review history */}
      {(s.reviews ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Review history ({(s.reviews ?? []).length})</CardTitle>
            <CardDescription>Immutable record of every reviewer decision on this submission.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {s.reviews!.map((rv) => (
              <div key={rv.id} className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2">
                  <Badge variant={rv.decision === "approved" ? "success" : rv.decision === "rejected" ? "danger" : "warning"}>
                    {rv.decision.replace(/_/g, " ")}
                  </Badge>
                  {rv.ambiguous && <Badge variant="info">ambiguous</Badge>}
                  {rv.escalated && <Badge variant="danger">escalated</Badge>}
                  {rv.flagged_suspicious && <Badge variant="danger">flagged</Badge>}
                  <span className="text-xs text-fg-muted">
                    {rv.reviewer_name ?? `reviewer #${rv.reviewer_id}`} · {fmtDateTime(rv.created_at)}
                  </span>
                </div>
                {rv.comments && <p className="mt-1.5 text-sm text-fg-muted">{rv.comments}</p>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {s.adjudication && (
        <Card className="border-teal/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-teal" /> Adjudication</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <Badge variant="default">final: {s.adjudication.final_decision}</Badge>
            <p className="mt-2 text-fg-muted">{s.adjudication.rationale}</p>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Record decision: ${decision.replace("_", " ")}?`}
        description="This creates a permanent review record and notifies the tester. It cannot be undone."
        confirmLabel="Record decision"
        busy={decide.isPending}
        onConfirm={() => { setConfirmOpen(false); decide.mutate(); }}
      />
    </div>
  );
}
