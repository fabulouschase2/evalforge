import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff, isPlatformAdmin } from "@/lib/roles";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import { CriterionScoresTable, FactualityPanel, ResultFindingsTable } from "@/components/evaluation/ResultDetailShared";

const REVIEW_LABELS = ["pass", "fail", "partially_correct", "evidence_insufficient", "uncertain"];

export default function ReviewDetailPage() {
  const { id } = useParams();
  const assignmentId = Number(id);
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();

  const ws = useQuery(queries.reviewWorkspace(assignmentId));
  const [label, setLabel] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [evidence, setEvidence] = useState("");
  const [uncertain, setUncertain] = useState(false);

  const [adjOpen, setAdjOpen] = useState(false);
  const [adjLabel, setAdjLabel] = useState("");
  const [adjRationale, setAdjRationale] = useState("");

  const submit = useMutation({
    mutationFn: () => api.post(`/reviews/${assignmentId}/submit`, {
      label, reasoning: reasoning || null, evidence: evidence || null, uncertain, criterion_scores: [],
    }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("success", "Review submitted", "Your assessment is stored immutably. Other reviews are now visible to you.");
    },
    onError: (e) => toast("error", "Could not submit review", (e as Error).message),
  });

  const adjudicate = useMutation({
    mutationFn: () => api.post(`/reviews/results/${ws.data!.result.id}/adjudicate`, {
      final_label: adjLabel, rationale: adjRationale, final_criterion_scores: [],
    }),
    onSuccess: () => {
      qc.invalidateQueries();
      setAdjOpen(false);
      toast("success", "Adjudication recorded", "All original assessments are preserved alongside your final decision.");
    },
    onError: (e) => toast("error", "Adjudication failed", (e as Error).message),
  });

  if (ws.isLoading) return <TableSkeleton rows={8} cols={4} />;
  if (ws.isError) return <ErrorState message={(ws.error as Error)?.message} retry={ws.refetch} />;

  const d = ws.data;
  if (!d) return null;
  const isOwner = d.assignment.reviewer_id === user?.id;
  const canAdjudicate = isStaff(user?.role ?? "") && !d.adjudication;
  const reviewsDisagree = d.visible_reviews.length >= 2 && new Set(d.visible_reviews.map((r) => r.label)).size > 1;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Review workspace</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Result <span className="font-mono">{d.result.record_id}</span> · Run{" "}
            <span className="text-teal">{d.run?.name ?? d.result.run_id}</span> · Assignment #{d.assignment.id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {d.assignment.blind && <Badge variant="info">blind review</Badge>}
          <StatusBadge status={d.assignment.status} />
          {d.result.gold_label && isOwner && d.own_review_submitted && (
            <Badge variant="neutral">gold: {d.result.gold_label}</Badge>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Prompt</CardTitle>
          </CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm text-fg">{d.record.prompt}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>AI response</CardTitle>
            <CardDescription>The response under evaluation.</CardDescription>
          </CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm text-fg">{d.record.response}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Reference material</CardTitle>
            <CardDescription>Reference answer and sources attached to this record.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {d.record.reference_answer
              ? <div className="whitespace-pre-wrap rounded-md border border-border bg-base-panel/40 p-3 text-fg-muted">{d.record.reference_answer}</div>
              : <div className="text-xs italic text-fg-muted">No reference answer on this record — factual correctness cannot be verified automatically.</div>}
            {(d.record.reference_sources?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {d.record.reference_sources.map((s, i) => (
                  <Badge key={i} variant="neutral">{String(s)}</Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Automated evaluation</CardTitle>
            <CardDescription>
              Automated label <Badge variant={d.result.automated_label === "pass" ? "success" : "danger"}>{d.result.automated_label}</Badge>{" "}
              · score {d.result.score.toFixed(2)} · confidence {d.result.confidence.toFixed(2)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CriterionScoresTable criteria={d.result.criterion_scores?.criteria ?? []} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Automated findings</CardTitle>
          <CardDescription>Every deterministic check with its evidence and explanation.</CardDescription>
        </CardHeader>
        <CardContent>
          <ResultFindingsTable findings={d.findings} />
        </CardContent>
      </Card>

      <FactualityPanel
        factuality={d.result.factuality}
        borderlineCategory={d.result.borderline_category}
        borderlineExplanation={d.result.summary?.borderline_explanation}
        confidenceReasons={d.result.summary?.confidence_reasons}
        confidence={d.result.confidence}
      />

      {/* Other reviews — hidden until own submission (blind review enforcement) */}
      <Card>
        <CardHeader>
          <CardTitle>
            Other reviewer assessments
            {!d.own_review_submitted && isOwner && <Badge variant="warning" className="ml-2">hidden until you submit</Badge>}
          </CardTitle>
          <CardDescription>
            Independent reviews follow blind-review rules: peers' decisions become visible only after your own
            assessment is submitted.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!d.own_review_submitted && isOwner ? (
            <div className="rounded-md border border-warn/40 bg-[rgba(245,158,11,0.06)] px-4 py-3 text-sm text-warn">
              Blind review in progress — {d.visible_reviews.length} peer review(s) are withheld until you submit yours.
            </div>
          ) : d.visible_reviews.length === 0 ? (
            <div className="text-sm text-fg-muted">No reviews visible yet.</div>
          ) : (
            d.visible_reviews.map((rv) => (
              <div key={rv.id} className="rounded-md border border-border p-3.5">
                <div className="flex items-center gap-2">
                  <Badge variant={rv.label === "pass" ? "success" : rv.label === "fail" ? "danger" : "warning"}>{rv.label.replace(/_/g, " ")}</Badge>
                  {rv.uncertain && <Badge variant="info">reviewer uncertain</Badge>}
                  <span className="text-xs text-fg-muted">reviewer #{rv.reviewer_id} · submitted {new Date(rv.submitted_at).toLocaleString()}</span>
                </div>
                {rv.reasoning && <p className="mt-2 text-sm text-fg-muted">{rv.reasoning}</p>}
              </div>
            ))
          )}
          {reviewsDisagree && !d.adjudication && (
            <div className="rounded-md border border-danger/40 bg-[rgba(239,68,68,0.07)] px-4 py-3 text-sm text-danger">
              Reviewer disagreement detected — an adjudication decision is required.
            </div>
          )}
        </CardContent>
      </Card>

      {/* Submit own review */}
      {isOwner && !d.own_review_submitted ? (
        <Card>
          <CardHeader>
            <CardTitle>Submit your assessment</CardTitle>
            <CardDescription>
              Your submission is permanent and cannot be edited. Mark “uncertain” when you are not confident
              in your own decision.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="rv-label">Failure label / decision</Label>
                <NativeSelect id="rv-label" value={label} onChange={(e) => setLabel(e.target.value)}>
                  <option value="">— Select —</option>
                  {REVIEW_LABELS.map((l) => <option key={l} value={l}>{l.replace(/_/g, " ")}</option>)}
                </NativeSelect>
              </div>
              <label className="mt-6 flex items-center gap-2 text-sm text-fg">
                <input type="checkbox" className="h-4 w-4 accent-[#16B8A6]" checked={uncertain} onChange={(e) => setUncertain(e.target.checked)} />
                I am uncertain about this decision
              </label>
            </div>
            <div>
              <Label htmlFor="rv-reasoning">Written reasoning (required)</Label>
              <Textarea
                id="rv-reasoning"
                className="min-h-[110px] font-sans text-sm"
                value={reasoning}
                onChange={(e) => setReasoning(e.target.value)}
                placeholder="Explain your assessment: which criteria and evidence informed the decision?"
              />
            </div>
            <div>
              <Label htmlFor="rv-evidence">Supporting evidence (optional)</Label>
              <Input
                id="rv-evidence"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                placeholder="Quote the response or reference material supporting your decision"
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={() => submit.mutate()} disabled={!label || !reasoning.trim() || submit.isPending}>
                {submit.isPending ? "Submitting…" : "Submit assessment"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : isOwner && d.own_review ? (
        <Card>
          <CardHeader>
            <CardTitle>Your assessment (immutable)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant={d.own_review.label === "pass" ? "success" : "danger"}>{d.own_review.label.replace(/_/g, " ")}</Badge>
              {d.own_review.uncertain && <Badge variant="info">uncertain</Badge>}
            </div>
            {d.own_review.reasoning && <p className="text-fg-muted">{d.own_review.reasoning}</p>}
          </CardContent>
        </Card>
      ) : null}

      {/* Adjudication */}
      {d.adjudication && (
        <Card className="border-teal/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-teal" /> Adjudication decision</CardTitle>
            <CardDescription>Final decision by an adjudicator. Original reviews remain preserved above.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div>
              <Badge variant="default">final: {d.adjudication.final_label.replace(/_/g, " ")}</Badge>
            </div>
            <p className="text-fg-muted">{d.adjudication.rationale}</p>
            <div className="text-xs text-fg-muted">
              Covered reviews: {d.adjudication.review_ids.join(", ")} · {new Date(d.adjudication.created_at).toLocaleString()}
            </div>
          </CardContent>
        </Card>
      )}

      {canAdjudicate && reviewsDisagree && (
        <Card className="border-warn/40">
          <CardHeader>
            <CardTitle>Adjudication required</CardTitle>
            <CardDescription>
              Reviewers disagree on this result. Record the final decision — every original assessment stays
              preserved for audit.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="secondary" onClick={() => setAdjOpen(true)}>Open adjudication</Button>
          </CardContent>
        </Card>
      )}

      <Dialog open={adjOpen} onOpenChange={setAdjOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Adjudicate result {d.result.record_id}</DialogTitle>
            <DialogDescription>
              This creates an adjudication record. The reviewers' original assessments are never modified.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="adj-label">Final label</Label>
              <NativeSelect id="adj-label" value={adjLabel} onChange={(e) => setAdjLabel(e.target.value)}>
                <option value="">— Select —</option>
                {REVIEW_LABELS.map((l) => <option key={l} value={l}>{l.replace(/_/g, " ")}</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="adj-rationale">Rationale (required)</Label>
              <Textarea
                id="adj-rationale"
                className="min-h-[100px] font-sans text-sm"
                value={adjRationale}
                onChange={(e) => setAdjRationale(e.target.value)}
                placeholder="Why is this the final decision? Which reviewer arguments did you adopt?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAdjOpen(false)}>Cancel</Button>
            <Button onClick={() => adjudicate.mutate()} disabled={!adjLabel || !adjRationale.trim() || adjudicate.isPending}>
              {adjudicate.isPending ? "Recording…" : "Record adjudication"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
