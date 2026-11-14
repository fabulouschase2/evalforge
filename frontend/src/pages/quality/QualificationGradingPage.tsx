// Quality/staff: manually grade qualification attempts (text / code exercises).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { fmtDateTime } from "@/lib/utils";

interface GradingItem {
  id: number; assessment_id: number; assessment_title: string | null;
  worker_id: number; worker_name: string | null; status: string;
  provisional_score: number | null; attempt_number: number; submitted_at: string | null;
  answers: Record<string, unknown>;
  questions: { id: number; prompt: string; question_type: string; options: string[]; correct_answer: { value?: unknown } | null; points: number }[];
}

export default function QualificationGradingPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [gradeFor, setGradeFor] = useState<GradingItem | null>(null);
  const [score, setScore] = useState("0.8");

  const queue = useQuery({
    queryKey: ["qual-grading-queue"],
    queryFn: () => api.get<GradingItem[]>("/quality/qualifications"),
  });

  const grade = useMutation({
    mutationFn: () => api.post(`/quality/qualifications/${gradeFor!.id}/grade`, { score: Number(score) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["qual-grading-queue"] });
      setGradeFor(null);
      toast("success", "Attempt graded", "The worker has been notified.");
    },
    onError: (e) => toast("error", "Grading failed", (e as Error).message),
  });

  const list = queue.data ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Qualification grading</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Free-text and code answers need a human grade. Auto-graded attempts never appear here.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Awaiting review ({list.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {queue.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : queue.isError ? (
            <ErrorState message={(queue.error as Error)?.message} retry={queue.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="Nothing to grade" description="Manual-grading attempts will appear here." />
          ) : (
            <Table>
              <THead><TR><TH>Assessment</TH><TH>Worker</TH><TH>Attempt</TH><TH>Provisional</TH><TH>Submitted</TH><TH /></TR></THead>
              <TBody>
                {list.map((item) => (
                  <TR key={item.id}>
                    <TD className="max-w-[220px] truncate text-sm font-medium text-fg">{item.assessment_title}</TD>
                    <TD className="text-sm text-fg-muted">{item.worker_name ?? `#${item.worker_id}`}</TD>
                    <TD className="text-xs text-fg-muted">#{item.attempt_number}</TD>
                    <TD className="text-xs text-fg-muted">
                      {item.provisional_score !== null ? `${Math.round(item.provisional_score * 100)}% (auto part)` : "—"}
                    </TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(item.submitted_at)}</TD>
                    <TD className="text-right">
                      <Button size="sm" onClick={() => { setGradeFor(item); setScore(String(item.provisional_score ?? 0.8)); }}>
                        <ClipboardCheck className="h-3.5 w-3.5" /> Grade
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={gradeFor !== null} onOpenChange={(o) => !o && setGradeFor(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Grade — {gradeFor?.assessment_title}</DialogTitle>
            <DialogDescription>
              Worker {gradeFor?.worker_name ?? ""} · attempt #{gradeFor?.attempt_number}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {(gradeFor?.questions ?? []).map((q, i) => (
              <div key={q.id} className="rounded-md border border-line p-3 text-sm">
                <div className="font-medium text-fg">{i + 1}. {q.prompt}</div>
                <div className="mt-2 rounded bg-surface-raised p-2 text-fg">
                  <span className="text-xs uppercase tracking-wide text-fg-muted">Worker answer: </span>
                  {String((gradeFor?.answers ?? {})[q.id] ?? "—")}
                </div>
                {q.correct_answer?.value !== undefined && (
                  <div className="mt-1.5 text-xs text-fg-muted">Reference: {String(q.correct_answer.value)}</div>
                )}
              </div>
            ))}
            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-fg-muted" htmlFor="grade-score">
                Final score (0–1)
              </label>
              <input
                id="grade-score" type="number" min={0} max={1} step={0.05}
                className="mt-1 w-32 rounded-md border border-line bg-surface p-2 text-sm text-fg"
                value={score} onChange={(e) => setScore(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGradeFor(null)}>Cancel</Button>
            <Button onClick={() => grade.mutate()} disabled={grade.isPending}>
              {grade.isPending ? "Saving…" : "Submit grade"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
