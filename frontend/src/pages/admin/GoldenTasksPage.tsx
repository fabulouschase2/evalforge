// Golden task management: create/import probes, tune queue insertion config.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries, useInvalidateAll } from "@/api/v2hooks";
import { queries as v1queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import type { ProjectDetail } from "@/lib/types";

const SCORING_METHODS = ["exact", "variations", "numeric_tolerance", "single_label", "multi_label", "contains_keywords"];
const DIFFICULTIES = ["easy", "medium", "hard", "expert"];

interface GoldenTask {
  id: number; project_id: number; title: string; scoring_method: string;
  difficulty: string; version: number; is_active: boolean;
  reference_answer: Record<string, unknown>; accepted_variations: unknown[];
  created_at: string | null; has_variations: boolean;
}

const EMPTY_FORM = {
  project_id: "", title: "", reference: "", variations: "", scoring_method: "exact",
  scoring_config: "", difficulty: "medium", explanation: "",
};

export default function GoldenTasksPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [projectFilter, setProjectFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [importOpen, setImportOpen] = useState(false);
  const [importJson, setImportJson] = useState("");
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState({ percentage: "10", fixed_count: "", min_spacing: "5", accuracy_alert_below: "0.6", consecutive_failures_alert: "3", min_seconds_per_task: "10" });

  const projects = useQuery(v1queries.projects());
  const projectList = (projects.data ?? []) as unknown as ProjectDetail[];
  const adminProjects = projectList.filter((p) => p.is_admin);

  const goldens = useQuery({
    queryKey: ["golden-tasks", projectFilter],
    queryFn: () => api.get<GoldenTask[]>(`/golden-tasks${projectFilter ? `?project_id=${projectFilter}` : ""}`),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["golden-tasks"] });

  const create = useMutation({
    mutationFn: () => api.post("/golden-tasks", {
      project_id: Number(form.project_id),
      title: form.title,
      reference_answer: { answer: form.reference },
      accepted_variations: form.variations.split(",").map((s) => s.trim()).filter(Boolean),
      scoring_method: form.scoring_method,
      scoring_config: form.scoring_config ? JSON.parse(form.scoring_config) : {},
      difficulty: form.difficulty,
      explanation: form.explanation || null,
    }),
    onSuccess: () => { invalidate(); setCreateOpen(false); setForm(EMPTY_FORM); toast("success", "Golden task created"); },
    onError: (e) => toast("error", "Could not create", (e as Error).message),
  });

  const importTasks = useMutation({
    mutationFn: () => api.post<{ imported: number; errors: unknown[] }>("/golden-tasks/import", {
      project_id: Number(form.project_id),
      tasks: JSON.parse(importJson),
    }),
    onSuccess: (data: { imported: number; errors: unknown[] }) => {
      invalidate(); setImportOpen(false); setImportJson("");
      toast("success", `Imported ${data.imported} tasks`, data.errors.length ? `${data.errors.length} rows had errors.` : undefined);
    },
    onError: (e) => toast("error", "Import failed", (e as Error).message),
  });

  const saveConfig = useMutation({
    mutationFn: () => api.put(`/golden-tasks/config/${configOpen ? projectFilter || adminProjects[0]?.id : 0}`, {
      percentage: Number(config.percentage),
      fixed_count: config.fixed_count ? Number(config.fixed_count) : null,
      min_spacing: Number(config.min_spacing),
      accuracy_alert_below: Number(config.accuracy_alert_below),
      consecutive_failures_alert: Number(config.consecutive_failures_alert),
      min_seconds_per_task: Number(config.min_seconds_per_task),
    }),
    onSuccess: () => { setConfigOpen(false); toast("success", "Golden task config saved"); },
    onError: (e) => toast("error", "Could not save config", (e as Error).message),
  });

  const toggleActive = useMutation({
    mutationFn: (g: GoldenTask) => api.put(`/golden-tasks/${g.id}`, { is_active: !g.is_active }),
    onSuccess: () => { invalidate(); toast("success", "Golden task updated"); },
    onError: (e) => toast("error", "Update failed", (e as Error).message),
  });

  const list = goldens.data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Golden tasks</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Known-answer probes woven into task queues to measure worker quality. Workers never see which tasks are golden.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setConfigOpen(true)}>Queue config</Button>
          <Button variant="secondary" onClick={() => setImportOpen(true)}><Upload className="h-4 w-4" /> Import</Button>
          <Button onClick={() => setCreateOpen(true)}><KeyRound className="h-4 w-4" /> New golden task</Button>
        </div>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Probes ({list.length})</CardTitle>
          <NativeSelect aria-label="Filter by project" className="w-56" value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="">All projects</option>
            {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </NativeSelect>
        </CardHeader>
        <CardContent>
          {goldens.isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : goldens.isError ? (
            <ErrorState message={(goldens.error as Error)?.message} retry={goldens.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="No golden tasks yet"
              description="Create probes or import them — then generate tasks to weave them into the queue." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Title</TH><TH>Method</TH><TH>Difficulty</TH><TH>Version</TH><TH>State</TH><TH>Created</TH><TH /></TR>
              </THead>
              <TBody>
                {list.map((g) => (
                  <TR key={g.id}>
                    <TD className="max-w-[260px] truncate text-sm font-medium text-fg">{g.title}</TD>
                    <TD><Badge variant="info">{g.scoring_method.replace(/_/g, " ")}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{g.difficulty}</TD>
                    <TD className="text-xs text-fg-muted">v{g.version}</TD>
                    <TD><Badge variant={g.is_active ? "success" : "neutral"}>{g.is_active ? "active" : "paused"}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(g.created_at)}</TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => toggleActive.mutate(g)}>
                        {g.is_active ? "Pause" : "Activate"}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New golden task</DialogTitle>
            <DialogDescription>The reference answer is immutable — edits create a new version.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="g-project">Project *</Label>
              <NativeSelect id="g-project" value={form.project_id} onChange={(e) => setForm((f) => ({ ...f, project_id: e.target.value }))}>
                <option value="">— Select —</option>
                {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect></div>
            <div><Label htmlFor="g-title">Title *</Label>
              <Input id="g-title" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} /></div>
            <div><Label htmlFor="g-ref">Reference answer *</Label>
              <Input id="g-ref" value={form.reference} onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} placeholder="The known correct answer" /></div>
            <div><Label htmlFor="g-variations">Accepted variations (comma-separated, for the variations method)</Label>
              <Input id="g-variations" value={form.variations} onChange={(e) => setForm((f) => ({ ...f, variations: e.target.value }))} /></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label htmlFor="g-method">Scoring method</Label>
                <NativeSelect id="g-method" value={form.scoring_method} onChange={(e) => setForm((f) => ({ ...f, scoring_method: e.target.value }))}>
                  {SCORING_METHODS.map((m) => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}
                </NativeSelect></div>
              <div><Label htmlFor="g-diff">Difficulty</Label>
                <NativeSelect id="g-diff" value={form.difficulty} onChange={(e) => setForm((f) => ({ ...f, difficulty: e.target.value }))}>
                  {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
                </NativeSelect></div>
            </div>
            <div><Label htmlFor="g-cfg">Scoring config (JSON, optional — e.g. {`{"tolerance": 0.01}`})</Label>
              <Input id="g-cfg" value={form.scoring_config} onChange={(e) => setForm((f) => ({ ...f, scoring_config: e.target.value }))} /></div>
            <div><Label htmlFor="g-expl">Explanation (shown in quality reports)</Label>
              <Textarea id="g-expl" rows={2} value={form.explanation} onChange={(e) => setForm((f) => ({ ...f, explanation: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()}
              disabled={!form.project_id || !form.title || !form.reference || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Import dialog */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Import golden tasks (JSON)</DialogTitle>
            <DialogDescription>
              {`[{"title": "...", "reference_answer": {"answer": "..."}, "scoring_method": "exact", "difficulty": "easy"}]`}
            </DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="gi-project">Project *</Label>
            <NativeSelect id="gi-project" value={form.project_id} onChange={(e) => setForm((f) => ({ ...f, project_id: e.target.value }))}>
              <option value="">— Select —</option>
              {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </div>
          <Textarea rows={8} className="font-mono text-xs" value={importJson}
            placeholder='[{"title": "Capital of France", "reference_answer": {"answer": "Paris"}}]'
            onChange={(e) => setImportJson(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setImportOpen(false)}>Cancel</Button>
            <Button onClick={() => importTasks.mutate()}
              disabled={!form.project_id || !importJson.trim() || importTasks.isPending}>
              {importTasks.isPending ? "Importing…" : "Import"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Config dialog */}
      <Dialog open={configOpen} onOpenChange={setConfigOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Golden queue configuration</DialogTitle>
            <DialogDescription>Applies when tasks are generated. Alerts are indicators only — never automatic suspensions.</DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="gc-project">Project *</Label>
            <NativeSelect id="gc-project" value={projectFilter || (adminProjects[0]?.id ? String(adminProjects[0].id) : "")}
              onChange={(e) => setProjectFilter(e.target.value)}>
              {adminProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><Label htmlFor="gc-pct">Insertion percentage</Label>
              <Input id="gc-pct" type="number" min={0} max={100} value={config.percentage} onChange={(e) => setConfig((c) => ({ ...c, percentage: e.target.value }))} /></div>
            <div><Label htmlFor="gc-fixed">Fixed count per batch (optional)</Label>
              <Input id="gc-fixed" type="number" min={0} value={config.fixed_count} onChange={(e) => setConfig((c) => ({ ...c, fixed_count: e.target.value }))} /></div>
            <div><Label htmlFor="gc-space">Min ordinary tasks between probes</Label>
              <Input id="gc-space" type="number" min={0} value={config.min_spacing} onChange={(e) => setConfig((c) => ({ ...c, min_spacing: e.target.value }))} /></div>
            <div><Label htmlFor="gc-acc">Accuracy alert below (0–1)</Label>
              <Input id="gc-acc" type="number" step="0.05" min={0} max={1} value={config.accuracy_alert_below} onChange={(e) => setConfig((c) => ({ ...c, accuracy_alert_below: e.target.value }))} /></div>
            <div><Label htmlFor="gc-consec">Consecutive failures alert</Label>
              <Input id="gc-consec" type="number" min={1} value={config.consecutive_failures_alert} onChange={(e) => setConfig((c) => ({ ...c, consecutive_failures_alert: e.target.value }))} /></div>
            <div><Label htmlFor="gc-speed">Min plausible seconds per task</Label>
              <Input id="gc-speed" type="number" min={0} value={config.min_seconds_per_task} onChange={(e) => setConfig((c) => ({ ...c, min_seconds_per_task: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfigOpen(false)}>Cancel</Button>
            <Button onClick={() => saveConfig.mutate()} disabled={saveConfig.isPending || !adminProjects.length}>
              {saveConfig.isPending ? "Saving…" : "Save config"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
