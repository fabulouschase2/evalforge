// Qualification assessments: builder + list + eligibility requirements editor.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { queries as v1queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import type { ProjectDetail } from "@/lib/types";

const ASSESSMENT_TYPES = ["mcq", "text_grading", "coding", "annotation_exercise", "factuality", "instruction_following", "custom_rubric"];
const SKILL_CATALOG = [
  "AI response evaluation", "Factuality verification", "Software engineering", "Python",
  "JavaScript", "Coding evaluation", "Data annotation", "Text classification",
  "Image annotation", "Video annotation", "Audio annotation", "Safety evaluation",
];

interface Question {
  question_type: string; prompt: string; options: string[];
  correct: string; points: number;
}
interface Assessment {
  id: number; title: string; description: string | null; assessment_type: string;
  skill_tags: string[]; time_limit_minutes: number | null; max_attempts: number;
  passing_score: number; project_id: number | null; status: string;
  question_count: number; version: number; created_at: string | null;
}

const EMPTY_Q: Question = { question_type: "mcq", prompt: "", options: ["", ""], correct: "", points: 1 };

export default function QualificationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [createOpen, setCreateOpen] = useState(false);
  const [eligOpen, setEligOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [atype, setAtype] = useState("mcq");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [skillTags, setSkillTags] = useState<string[]>([]);
  const [passingScore, setPassingScore] = useState("0.7");
  const [timeLimit, setTimeLimit] = useState("");
  const [questions, setQuestions] = useState<Question[]>([{ ...EMPTY_Q }]);
  const [eligProject, setEligProject] = useState("");
  const [eligAssessment, setEligAssessment] = useState("");
  const [eligMinScore, setEligMinScore] = useState("0.85");

  const projects = useQuery(v1queries.projects());
  const projectList = (projects.data ?? []) as unknown as ProjectDetail[];
  const adminProjects = projectList.filter((p) => p.is_admin);

  const assessments = useQuery({
    queryKey: ["qualifications"],
    queryFn: () => api.get<Assessment[]>("/qualifications"),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["qualifications"] });

  const create = useMutation({
    mutationFn: () => api.post("/qualifications", {
      title, description: description || null, assessment_type: atype,
      project_id: projectId ? Number(projectId) : null,
      skill_tags: skillTags,
      passing_score: Number(passingScore),
      time_limit_minutes: timeLimit ? Number(timeLimit) : null,
      questions: questions.map((q, i) => ({
        order: i, question_type: q.question_type, prompt: q.prompt,
        options: q.options.filter(Boolean),
        correct_answer: { value: q.question_type === "numeric" ? Number(q.correct) : q.correct },
        points: q.points,
      })),
    }),
    onSuccess: () => {
      invalidate(); setCreateOpen(false); setTitle(""); setDescription("");
      setQuestions([{ ...EMPTY_Q }]); setSkillTags([]);
      toast("success", "Assessment created");
    },
    onError: (e) => toast("error", "Could not create assessment", (e as Error).message),
  });

  const currentReqs = useQuery({
    queryKey: ["eligibility", eligProject],
    queryFn: () => api.get<{ requirements: { assessment_id?: number; min_score?: number; skill?: string }[] }>(`/qualifications/eligibility/${eligProject}`),
    enabled: !!eligProject,
  });

  const saveEligibility = useMutation({
    mutationFn: () => {
      const existing = (currentReqs.data?.requirements ?? []).filter((r) => "skill" in r);
      const newReq = eligAssessment
        ? [...existing, { assessment_id: Number(eligAssessment), min_score: Number(eligMinScore) }]
        : existing;
      return api.put(`/qualifications/eligibility/${eligProject}`, { requirements: newReq });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eligibility"] });
      setEligAssessment("");
      toast("success", "Eligibility requirements saved");
    },
    onError: (e) => toast("error", "Could not save", (e as Error).message),
  });

  const toggleStatus = useMutation({
    mutationFn: (a: Assessment) => api.put(`/qualifications/${a.id}`, { status: a.status === "active" ? "retired" : "active" }),
    onSuccess: () => { invalidate(); toast("success", "Assessment updated"); },
    onError: (e) => toast("error", "Update failed", (e as Error).message),
  });

  const list = assessments.data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Qualification assessments</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Workers must pass required assessments before claiming restricted projects' tasks.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEligOpen(true)}>Project eligibility</Button>
          <Button onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> New assessment</Button>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Assessments ({list.length})</CardTitle></CardHeader>
        <CardContent>
          {assessments.isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : assessments.isError ? (
            <ErrorState message={(assessments.error as Error)?.message} retry={assessments.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="No assessments yet"
              description="Create an assessment and attach it to project eligibility requirements." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Title</TH><TH>Type</TH><TH>Questions</TH><TH>Pass score</TH><TH>Skills verified</TH><TH>Status</TH><TH /></TR>
              </THead>
              <TBody>
                {list.map((a) => (
                  <TR key={a.id}>
                    <TD className="max-w-[240px] truncate text-sm font-medium text-fg">{a.title}</TD>
                    <TD><Badge variant="info">{a.assessment_type.replace(/_/g, " ")}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{a.question_count}</TD>
                    <TD className="text-xs text-fg-muted">{Math.round(a.passing_score * 100)}%</TD>
                    <TD className="max-w-[180px] truncate text-xs text-fg-muted">{(a.skill_tags ?? []).join(", ") || "—"}</TD>
                    <TD><Badge variant={a.status === "active" ? "success" : "neutral"}>{a.status}</Badge></TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => toggleStatus.mutate(a)}>
                        {a.status === "active" ? "Retire" : "Reactivate"}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create assessment */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New assessment</DialogTitle>
            <DialogDescription>
              MCQ / multi-select / numeric questions auto-grade; text and code route to manual grading.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="q-title">Title *</Label>
              <Input id="q-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><Label htmlFor="q-desc">Description</Label>
              <Input id="q-desc" value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div><Label htmlFor="q-type">Type</Label>
                <NativeSelect id="q-type" value={atype} onChange={(e) => setAtype(e.target.value)}>
                  {ASSESSMENT_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
                </NativeSelect></div>
              <div><Label htmlFor="q-pass">Passing score (0–1)</Label>
                <Input id="q-pass" type="number" min={0} max={1} step="0.05" value={passingScore} onChange={(e) => setPassingScore(e.target.value)} /></div>
              <div><Label htmlFor="q-time">Time limit (min, optional)</Label>
                <Input id="q-time" type="number" min={1} value={timeLimit} onChange={(e) => setTimeLimit(e.target.value)} /></div>
            </div>
            <div><Label htmlFor="q-project">Project (optional — platform-wide if empty)</Label>
              <NativeSelect id="q-project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">Platform-wide</option>
                {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect></div>
            <div>
              <Label>Skills verified on pass</Label>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {SKILL_CATALOG.map((s) => (
                  <button key={s} type="button"
                    onClick={() => setSkillTags((t) => t.includes(s) ? t.filter((x) => x !== s) : [...t, s])}
                    className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                      skillTags.includes(s) ? "border-teal-500 bg-teal-500/15 text-teal" : "border-line text-fg-muted hover:text-fg"
                    }`}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between">
                <Label>Questions</Label>
                <Button variant="ghost" size="sm" onClick={() => setQuestions((qs) => [...qs, { ...EMPTY_Q }])}>
                  <Plus className="h-3.5 w-3.5" /> Add question
                </Button>
              </div>
              <div className="space-y-3">
                {questions.map((q, i) => (
                  <div key={i} className="rounded-md border border-line p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      <NativeSelect value={q.question_type} aria-label={`Question ${i + 1} type`}
                        onChange={(e) => setQuestions((qs) => qs.map((x, j) => j === i ? { ...x, question_type: e.target.value } : x))}>
                        <option value="mcq">multiple choice</option>
                        <option value="multi_select">multi-select</option>
                        <option value="numeric">numeric</option>
                        <option value="text">free text (manual grade)</option>
                        <option value="code">code (manual grade)</option>
                      </NativeSelect>
                      <Button variant="ghost" size="sm" className="text-danger" aria-label={`Remove question ${i + 1}`}
                        onClick={() => setQuestions((qs) => qs.filter((_, j) => j !== i))}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    <Input placeholder="Prompt" value={q.prompt}
                      onChange={(e) => setQuestions((qs) => qs.map((x, j) => j === i ? { ...x, prompt: e.target.value } : x))} />
                    {["mcq", "multi_select"].includes(q.question_type) && (
                      <div className="space-y-1.5">
                        {q.options.map((opt, oi) => (
                          <div key={oi} className="flex gap-2">
                            <Input placeholder={`Option ${oi + 1}`} value={opt}
                              onChange={(e) => setQuestions((qs) => qs.map((x, j) => j === i ? {
                                ...x, options: x.options.map((o, k) => k === oi ? e.target.value : o),
                              } : x))} />
                            {q.options.length > 2 && (
                              <Button variant="ghost" size="sm" aria-label={`Remove option ${oi + 1}`}
                                onClick={() => setQuestions((qs) => qs.map((x, j) => j === i ? {
                                  ...x, options: x.options.filter((_, k) => k !== oi),
                                } : x))}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        ))}
                        <Button variant="ghost" size="sm"
                          onClick={() => setQuestions((qs) => qs.map((x, j) => j === i ? { ...x, options: [...x.options, ""] } : x))}>
                          + option
                        </Button>
                      </div>
                    )}
                    <Input
                      placeholder={q.question_type === "numeric" ? "Correct number" : q.question_type === "text" || q.question_type === "code" ? "Grading reference (shown to the grader)" : "Exact correct option"}
                      value={q.correct}
                      onChange={(e) => setQuestions((qs) => qs.map((x, j) => j === i ? { ...x, correct: e.target.value } : x))} />
                  </div>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!title || create.isPending}>
              {create.isPending ? "Creating…" : "Create assessment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Eligibility editor */}
      <Dialog open={eligOpen} onOpenChange={setEligOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Project eligibility requirements</DialogTitle>
            <DialogDescription>
              Only workers meeting every requirement (or with a recorded override) can claim tasks.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="e-project">Project *</Label>
              <NativeSelect id="e-project" value={eligProject} onChange={(e) => setEligProject(e.target.value)}>
                <option value="">— Select —</option>
                {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect></div>
            {eligProject && (
              <>
                <div className="rounded-md border border-line p-3">
                  <div className="text-xs font-semibold uppercase text-fg-muted">Current requirements</div>
                  {(currentReqs.data?.requirements ?? []).length === 0 ? (
                    <p className="mt-1 text-xs text-fg-muted">No requirements — any project member can claim.</p>
                  ) : (
                    <ul className="mt-1 space-y-1 text-xs text-fg">
                      {(currentReqs.data?.requirements ?? []).map((r, i) => (
                        <li key={i}>
                          {r.assessment_id
                            ? `Qualification #${r.assessment_id} ≥ ${Math.round((r.min_score ?? 0) * 100)}%`
                            : `Skill: ${r.skill}`}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div><Label htmlFor="e-assess">Add assessment requirement</Label>
                    <NativeSelect id="e-assess" value={eligAssessment} onChange={(e) => setEligAssessment(e.target.value)}>
                      <option value="">— Select —</option>
                      {list.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                    </NativeSelect></div>
                  <div><Label htmlFor="e-min">Min score</Label>
                    <Input id="e-min" type="number" min={0} max={1} step="0.05" value={eligMinScore} onChange={(e) => setEligMinScore(e.target.value)} /></div>
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEligOpen(false)}>Close</Button>
            <Button onClick={() => saveEligibility.mutate()}
              disabled={!eligProject || !eligAssessment || saveEligibility.isPending}>
              {saveEligibility.isPending ? "Saving…" : "Add requirement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
