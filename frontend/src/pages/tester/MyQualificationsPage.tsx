// Tester workspace: available assessments, take flow, history, skills, performance.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, Plus, Send } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

interface Assessment {
  id: number; title: string; description: string | null; assessment_type: string;
  skill_tags: string[]; time_limit_minutes: number | null; max_attempts: number;
  passing_score: number; question_count: number; status: string;
}
interface Question {
  id: number; order: number; question_type: string; prompt: string;
  options: string[]; points: number;
}
interface AttemptInfo {
  id: number; attempt_number: number; status: string; score: number | null;
  submitted_at: string | null;
}
interface Skill { id: number; skill: string; source: string; verified_at: string | null }
interface Performance {
  submissions: { total: number; approved: number; rejected: number; revision_requested: number };
  golden_tasks: { attempts: number; passed: number; accuracy: number | null };
  tier: { tier: string; passed_qualifications: number; verified_skills: string[] };
  recent_feedback: { decision: string; comments: string | null; created_at: string }[];
}

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);

export default function MyQualificationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [takeAssessment, setTakeAssessment] = useState<Assessment | null>(null);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [newSkill, setNewSkill] = useState("");

  const assessments = useQuery({
    queryKey: ["qualifications-worker"],
    queryFn: () => api.get<Assessment[]>("/qualifications"),
  });
  const mine = useQuery({
    queryKey: ["my-skills"],
    queryFn: () => api.get<{ skills: Skill[]; catalog: string[] }>("/workers/me/skills"),
  });
  const perf = useQuery({
    queryKey: ["my-performance"],
    queryFn: () => api.get<Performance>("/workers/me/performance"),
  });
  const history = useQuery({
    queryKey: ["my-attempt-history", takeAssessment?.id],
    queryFn: () => api.get<{ history: AttemptInfo[]; assessment: { questions: Question[] } }>(`/qualifications/${takeAssessment!.id}/attempt`),
    enabled: !!takeAssessment,
  });

  const start = useMutation({
    mutationFn: (a: Assessment) => api.post<{ attempt_id: number }>(`/qualifications/${a.id}/attempts`),
    onSuccess: (data, a) => {
      setAttemptId(data.attempt_id);
      setTakeAssessment(a);
      qc.invalidateQueries({ queryKey: ["my-attempt-history"] });
    },
    onError: (e) => toast("error", "Cannot start attempt", (e as Error).message),
  });

  const openExisting = useMutation({
    mutationFn: (a: Assessment) => api.get<{ open_attempt: { id: number } | null }>(`/qualifications/${a.id}/attempt`),
    onSuccess: (data, a) => {
      if (data.open_attempt) {
        setAttemptId(data.open_attempt.id);
        setTakeAssessment(a);
      } else {
        start.mutate(a);
      }
    },
  });

  const submit = useMutation({
    mutationFn: () => {
      // multi_select answers are stored pipe-joined in local state; send lists
      const payload: Record<number, string | string[]> = {};
      for (const [qid, value] of Object.entries(answers)) {
        const q = questions.find((x) => x.id === Number(qid));
        payload[Number(qid)] = q?.question_type === "multi_select"
          ? String(value).split("|").filter(Boolean)
          : value;
      }
      return api.post<{ score: number; passed: boolean; status: string }>(
        `/qualifications/attempts/${attemptId}/submit`, { answers: payload });
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["my-performance"] });
      qc.invalidateQueries({ queryKey: ["my-skills"] });
      qc.invalidateQueries({ queryKey: ["my-attempt-history"] });
      setTakeAssessment(null); setAttemptId(null); setAnswers({});
      toast(result.passed ? "success" : "error",
        result.passed ? "Assessment passed!" : "Assessment graded",
        `Score: ${Math.round(result.score * 100)}% — ${result.status.replace(/_/g, " ")}`);
    },
    onError: (e) => toast("error", "Submission failed", (e as Error).message),
  });

  const claimSkill = useMutation({
    mutationFn: () => api.post("/workers/me/skills", { skill: newSkill }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["my-skills"] }); setNewSkill(""); toast("success", "Skill listed as self-reported"); },
    onError: (e) => toast("error", "Could not add skill", (e as Error).message),
  });

  const questions: Question[] = history.data?.assessment?.questions as Question[] ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">My qualifications</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Pass assessments to unlock restricted projects and verify your skills.
        </p>
      </div>

      {perf.data && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Card><CardContent className="p-4">
            <div className="text-lg font-bold capitalize text-fg">{perf.data.tier.tier}</div>
            <div className="text-xs text-fg-muted">Current tier</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <div className="text-lg font-bold text-ok">{perf.data.submissions.approved}/{perf.data.submissions.total}</div>
            <div className="text-xs text-fg-muted">Approved submissions</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <div className="text-lg font-bold text-fg">{pct(perf.data.golden_tasks.accuracy)}</div>
            <div className="text-xs text-fg-muted">Golden-task accuracy</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <div className="text-lg font-bold text-fg">{perf.data.tier.passed_qualifications}</div>
            <div className="text-xs text-fg-muted">Qualifications passed</div>
          </CardContent></Card>
        </div>
      )}

      <Card>
        <CardHeader><CardTitle>Available assessments</CardTitle></CardHeader>
        <CardContent>
          {assessments.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : assessments.isError ? (
            <ErrorState message={(assessments.error as Error)?.message} retry={assessments.refetch} />
          ) : (assessments.data ?? []).length === 0 ? (
            <EmptyState title="No assessments available" />
          ) : (
            <Table>
              <THead><TR><TH>Assessment</TH><TH>Type</TH><TH>Questions</TH><TH>Time limit</TH><TH>Pass score</TH><TH /></TR></THead>
              <TBody>
                {(assessments.data ?? []).filter((a) => a.status === "active").map((a) => (
                  <TR key={a.id}>
                    <TD className="max-w-[240px] truncate text-sm font-medium text-fg">{a.title}</TD>
                    <TD><Badge variant="info">{a.assessment_type.replace(/_/g, " ")}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{a.question_count}</TD>
                    <TD className="text-xs text-fg-muted">{a.time_limit_minutes ? `${a.time_limit_minutes} min` : "—"}</TD>
                    <TD className="text-xs text-fg-muted">{Math.round(a.passing_score * 100)}%</TD>
                    <TD className="text-right">
                      <Button size="sm" onClick={() => openExisting.mutate(a)} disabled={openExisting.isPending}>
                        <Award className="h-3.5 w-3.5" /> Take
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>My skills</CardTitle>
            <CardDescription>Verified skills come from passed assessments; listed skills are self-reported.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1.5">
              {(mine.data?.skills ?? []).length === 0 ? (
                <p className="text-sm text-fg-muted">No skills listed yet.</p>
              ) : (mine.data?.skills ?? []).map((s) => (
                <Badge key={s.id} variant={s.source === "verified" ? "success" : "neutral"}>
                  {s.source === "verified" ? "✓ " : ""}{s.skill}
                </Badge>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <Input placeholder="Add a skill (self-reported)…" value={newSkill}
                onChange={(e) => setNewSkill(e.target.value)} />
              <Button variant="secondary" onClick={() => claimSkill.mutate()}
                disabled={!newSkill.trim() || claimSkill.isPending}>
                <Plus className="h-4 w-4" /> Add
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Recent reviewer feedback</CardTitle></CardHeader>
          <CardContent>
            {(perf.data?.recent_feedback ?? []).length === 0 ? (
              <EmptyState title="No feedback yet" description="Feedback appears after your submissions are reviewed." />
            ) : (
              <ul className="space-y-2">
                {(perf.data?.recent_feedback ?? []).map((f, i) => (
                  <li key={i} className="rounded-md border border-line p-2.5 text-sm">
                    <div className="flex items-center gap-2">
                      <Badge variant={f.decision === "approved" ? "success" : f.decision === "rejected" ? "danger" : "warning"}>
                        {f.decision.replace(/_/g, " ")}
                      </Badge>
                      <span className="text-xs text-fg-muted">{fmtDateTime(f.created_at)}</span>
                    </div>
                    {f.comments && <p className="mt-1 text-fg-muted">{f.comments}</p>}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Take-assessment dialog */}
      <Dialog open={takeAssessment !== null} onOpenChange={(o) => { if (!o) { setTakeAssessment(null); setAttemptId(null); } }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{takeAssessment?.title}</DialogTitle>
            <DialogDescription>
              {takeAssessment?.time_limit_minutes
                ? `You have ${takeAssessment.time_limit_minutes} minutes from when you started. `
                : ""}
              Answer every question, then submit. {" "}
              {takeAssessment && `Pass score: ${Math.round(takeAssessment.passing_score * 100)}%.`}
            </DialogDescription>
          </DialogHeader>
          {attemptId && (
            <div className="space-y-4">
              {questions.map((q, i) => (
                <div key={q.id} className="space-y-2">
                  <div className="text-sm font-medium text-fg">{i + 1}. {q.prompt}</div>
                  {["mcq", "multi_select"].includes(q.question_type) ? (
                    <div className="space-y-1.5">
                      {q.options.map((opt) => (
                        <label key={opt} className="flex items-center gap-2 text-sm text-fg">
                          <input
                            type={q.question_type === "mcq" ? "radio" : "checkbox"}
                            name={`q-${q.id}`}
                            value={opt}
                            checked={q.question_type === "mcq"
                              ? answers[q.id] === opt
                              : String(answers[q.id] ?? "").split("|").includes(opt)}
                            onChange={(e) => {
                              if (q.question_type === "mcq") {
                                setAnswers((a) => ({ ...a, [q.id]: opt }));
                              } else {
                                const current = String(answers[q.id] ?? "").split("|").filter(Boolean);
                                const next = e.target.checked ? [...current, opt] : current.filter((x) => x !== opt);
                                setAnswers((a) => ({ ...a, [q.id]: next.join("|") }));
                              }
                            }}
                          />
                          {opt}
                        </label>
                      ))}
                    </div>
                  ) : (
                    <Input
                      placeholder={q.question_type === "numeric" ? "Numeric answer" : "Your answer"}
                      value={answers[q.id] ?? ""}
                      onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                    />
                  )}
                </div>
              ))}
              <div className="flex justify-end border-t border-line pt-3">
                <Button onClick={() => submit.mutate()} disabled={submit.isPending}>
                  <Send className="h-4 w-4" /> {submit.isPending ? "Submitting…" : "Submit attempt"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
