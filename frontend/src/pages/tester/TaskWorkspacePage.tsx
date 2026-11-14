// Task execution workspace: dynamic form driven by the rubric's evaluation form.
// Supports autosave, conditional questions, validation and submission.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Save, Send, AlertTriangle, ChevronLeft } from "lucide-react";
import { v2queries, useSubmissionMutations, useTaskMutations } from "@/api/v2hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";
import type { FormField } from "@/lib/types";
import AnnotationTaskWorkspace from "@/components/annotation/AnnotationTaskWorkspace";

function FieldInput({ field, value, onChange }: {
  field: FormField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const id = `field-${field.id}`;
  switch (field.type) {
    case "yes_no":
      return (
        <NativeSelect id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— Select —</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </NativeSelect>
      );
    case "single_select":
      return (
        <NativeSelect id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— Select —</option>
          {(field.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </NativeSelect>
      );
    case "multi_select": {
      const selected = Array.isArray(value) ? (value as string[]) : [];
      return (
        <div className="space-y-1.5">
          {(field.options ?? []).map((o) => (
            <label key={o} className="flex cursor-pointer items-center gap-2 text-sm text-fg">
              <input type="checkbox" className="h-4 w-4 accent-[#16B8A6]"
                checked={selected.includes(o)}
                onChange={(e) => onChange(e.target.checked ? [...selected, o] : selected.filter((x) => x !== o))} />
              {o}
            </label>
          ))}
        </div>
      );
    }
    case "numeric":
    case "likert": {
      const scale = field.scale ?? { min: 0, max: 10 };
      const num = typeof value === "number" ? value : value !== null && value !== undefined && value !== "" ? Number(value) : null;
      return (
        <div className="flex items-center gap-3">
          <input
            id={id} type="range"
            min={scale.min} max={scale.max} step={1}
            value={num ?? Math.ceil((scale.min + scale.max) / 2)}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-56 accent-[#16B8A6]"
            aria-label={field.label}
          />
          <Input
            type="number" min={scale.min} max={scale.max} className="w-24" aria-label={`${field.label} numeric value`}
            value={num ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          />
          <span className="text-xs text-fg-muted">{scale.min}–{scale.max}</span>
        </div>
      );
    }
    case "evidence": {
      const items = Array.isArray(value) ? (value as { kind: string; value: string; note?: string }[]) : [];
      return (
        <div className="space-y-2">
          {items.map((e, i) => (
            <div key={i} className="flex gap-2">
              <NativeSelect aria-label="Evidence kind" className="w-28" value={e.kind}
                onChange={(e2) => onChange(items.map((x, j) => (j === i ? { ...x, kind: e2.target.value } : x)))}>
                <option value="url">url</option>
                <option value="text">text</option>
              </NativeSelect>
              <Input aria-label="Evidence value" value={e.value}
                onChange={(e2) => onChange(items.map((x, j) => (j === i ? { ...x, value: e2.target.value } : x)))} />
              <Button variant="ghost" size="sm" className="text-danger" aria-label="Remove evidence"
                onClick={() => onChange(items.filter((_, j) => j !== i))}>×</Button>
            </div>
          ))}
          <Button variant="outline" size="sm" type="button"
            onClick={() => onChange([...items, { kind: "url", value: "" }])}>
            + Add evidence
          </Button>
        </div>
      );
    }
    default:
      return (
        <Textarea id={id} className="font-sans text-sm" value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)} />
      );
  }
}

export default function TaskWorkspacePage() {
  const { id } = useParams();
  const taskId = Number(id);
  const toast = useToast();
  const mutations = useSubmissionMutations();
  const taskMutations = useTaskMutations();
  const ws = useQuery(v2queries.workspace(taskId));
  const [payload, setPayload] = useState<Record<string, unknown>>({});
  const [explanation, setExplanation] = useState("");
  const [dirty, setDirty] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const lastSaved = useRef<string | null>(null);

  useEffect(() => {
    if (ws.data) {
      const initial = { ...(ws.data.draft_payload ?? {}) };
      // seed likert defaults
      for (const f of ws.data.form_fields) {
        if ((f.type === "likert" || f.type === "numeric") && initial[f.id] === undefined) {
          const scale = f.scale ?? { min: 1, max: 5 };
          initial[f.id] = Math.ceil((scale.min + scale.max) / 2);
        }
      }
      setPayload(initial);
      const firstText = ws.data.form_fields.find((f) => f.type === "text");
      if (firstText && initial[firstText.id] !== undefined && !explanation) {
        setExplanation(String(initial[firstText.id]));
      }
      lastSaved.current = ws.data.draft_updated_at;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.data?.task.id]);

  const autosave = useCallback(
    (p: Record<string, unknown>) => {
      if (!ws.data?.task.id) return;
      mutations.saveDraft(taskId, p).catch(() => { /* autosave failures are silent */ });
    },
    [mutations, taskId, ws.data?.task.id],
  );

  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => autosave(payload), 1500);
    return () => clearTimeout(t);
  }, [payload, dirty, autosave]);

  // Opening the workspace means work has started: assigned -> in_progress.
  const autoStart = useMutation({
    mutationFn: () => taskMutations.start(taskId),
    onSuccess: () => { void ws.refetch(); },
  });
  useEffect(() => {
    if (ws.data?.task.status === "assigned") autoStart.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.data?.task.status]);

  // NOTE: all hooks must run on every render — never place them after the
  // early returns below (hook-order violation crashed this page once data
  // arrived after a loading-first render).
  const submit = useMutation({
    mutationFn: () =>
      mutations.submit(taskId, {
        payload,
        explanation: explanation || undefined,
        evidence: (payload["sources"] as unknown[]) ?? [],
        time_spent_seconds: ws.data?.task.claimed_at
          ? Math.round((Date.now() - new Date(ws.data.task.claimed_at).getTime()) / 1000)
          : undefined,
      }),
    onSuccess: () => {
      toast("success", "Work submitted", "Your submission is now awaiting review. Feedback will appear here.");
      setDirty(false);
    },
    onError: (e) => toast("error", "Submission rejected", (e as Error).message),
  });

  if (ws.isLoading) return <TableSkeleton rows={8} cols={4} />;
  if (ws.isError) return <ErrorState message={(ws.error as Error)?.message} retry={ws.refetch} />;

  // v3 multimodal: annotation tasks render their dedicated workspace
  const ANNOTATION_TYPES = ["image_annotation", "video_annotation", "audio_annotation"];
  if (ANNOTATION_TYPES.includes(ws.data!.task.task_type ?? "")) {
    return <AnnotationTaskWorkspace taskId={taskId} />;
  }

  const data = ws.data!;
  const visibleFields = data.form_fields.filter((f) => {
    if (!f.conditional_on) return true;
    return (f.conditional_on.values as unknown[]).includes(payload[f.conditional_on.field_id]);
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/tasks/mine" className="text-fg-muted hover:text-fg"><ChevronLeft className="h-4 w-4" /></Link>
            <h1 className="text-xl font-bold text-fg">{data.task.title}</h1>
          </div>
          <p className="mt-1 text-sm text-fg-muted">
            {data.task.project_name} · {data.task.task_type} · {data.task.difficulty} ·
            attempt {data.task.attempt_count}/{data.task.max_attempts}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={data.task.status} />
          {data.draft_updated_at && (
            <span className="text-xs text-fg-muted">Draft saved {fmtDateTime(data.draft_updated_at)}</span>
          )}
        </div>
      </div>

      {data.task.status === "revision_required" && (
        <div className="rounded-md border border-warn/40 bg-[rgba(245,158,11,0.08)] px-4 py-3 text-sm text-warn">
          <AlertTriangle className="mr-1 inline h-4 w-4" />
          A reviewer requested revisions. Update your answers below and resubmit (attempt {data.task.attempt_count + 1} of {data.task.max_attempts}).
        </div>
      )}

      {data.task.instructions && (
        <Card>
          <CardHeader><CardTitle>Task instructions</CardTitle></CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm text-fg">{data.task.instructions}</CardContent>
        </Card>
      )}

      {data.record && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Input prompt</CardTitle></CardHeader>
            <CardContent className="whitespace-pre-wrap text-sm text-fg">{data.record.prompt}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>AI response under evaluation</CardTitle></CardHeader>
            <CardContent className="whitespace-pre-wrap text-sm text-fg">{data.record.response}</CardContent>
          </Card>
          {(data.record.reference_answer || (data.record.reference_sources ?? []).length > 0 || data.record.supporting_evidence) && (
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Reference material</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm text-fg-muted">
                {data.record.reference_answer && (
                  <div className="whitespace-pre-wrap rounded-md border border-border bg-base-panel/40 p-3">{data.record.reference_answer}</div>
                )}
                {(data.record.reference_sources ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {data.record.reference_sources.map((s, i) => <Badge key={i} variant="neutral">{String(s)}</Badge>)}
                  </div>
                )}
                {data.record.supporting_evidence && <div>Evidence: {data.record.supporting_evidence}</div>}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Dynamic evaluation form */}
      <Card>
        <CardHeader>
          <CardTitle>Evaluation form</CardTitle>
          <CardDescription>
            Fields render from the rubric version pinned to this task
            {data.task.blind_review ? " · your review is anonymous to other reviewers" : ""}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {data.form_fields.length === 0 ? (
            <div className="text-sm text-fg-muted">
              This task has no structured form — provide your analysis in the explanation field below.
            </div>
          ) : (
            visibleFields.map((f) => (
              <div key={f.id}>
                <Label htmlFor={`field-${f.id}`}>
                  {f.label}
                  {f.required && <span className="ml-1 text-danger">*</span>}
                  {f.type === "likert" && <span className="ml-1 text-xs font-normal text-fg-muted">(scale)</span>}
                </Label>
                <FieldInput field={f} value={payload[f.id]} onChange={(v) => { setPayload((p) => ({ ...p, [f.id]: v })); setDirty(true); }} />
              </div>
            ))
          )}
          <div>
            <Label htmlFor="ws-explanation">Written explanation {data.form_fields.length === 0 ? "" : "(optional)"}</Label>
            <Textarea id="ws-explanation" className="font-sans text-sm min-h-[100px]" value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              placeholder="Explain your reasoning, cite evidence and note any factual errors or instruction-following failures." />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-fg-muted">
              <Save className="mr-1 inline h-3 w-3" />
              Progress saves automatically{dirty ? " (pending change)" : ""}
            </span>
            <Button onClick={() => setConfirmOpen(true)} disabled={!data.can_submit || submit.isPending}>
              <Send className="h-4 w-4" /> Submit work
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Submission history + feedback */}
      {(data.submissions.length > 0 || data.feedback.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>Submission history &amp; reviewer feedback</CardTitle>
            <CardDescription>Submitted attempts are immutable; decisions are shown here as they arrive.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.submissions.map((s) => (
              <div key={s.id} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-fg">Attempt {s.attempt_number}</span>
                  <StatusBadge status={s.status} />
                </div>
                <div className="text-xs text-fg-muted">submitted {fmtDateTime(s.submitted_at)}</div>
              </div>
            ))}
            {data.feedback.map((f, i) => (
              <div key={i} className="rounded-md border border-border bg-base-panel/40 p-3">
                <div className="flex items-center gap-2">
                  <Badge variant={f.decision === "approved" ? "success" : f.decision === "rejected" ? "danger" : "warning"}>
                    {f.decision.replace(/_/g, " ")}
                  </Badge>
                  <span className="text-xs text-fg-muted">
                    attempt {f.attempt} · {f.reviewer_name ? `by ${f.reviewer_name}` : "reviewer"} · {fmtDateTime(f.created_at)}
                  </span>
                </div>
                {f.comments && <p className="mt-1.5 text-sm text-fg-muted">{f.comments}</p>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Submit your work?"
        description="Submissions are immutable — after submitting you cannot edit this attempt unless a reviewer requests revisions."
        confirmLabel="Submit now"
        busy={submit.isPending}
        onConfirm={() => { setConfirmOpen(false); submit.mutate(); }}
      />
    </div>
  );
}
