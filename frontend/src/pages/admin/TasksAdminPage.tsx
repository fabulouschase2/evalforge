// Task management: generation from datasets, manual/bulk creation, assignment controls.
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Wand2, Users, Ban, UserCog, FileDown, ListChecks } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries, useTaskMutations } from "@/api/v2hooks";
import { queries as v1queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TASK_STATUS_LABELS } from "@/lib/roles";
import { fmtDateTime } from "@/lib/utils";
import type { Dataset, PlatformTask, ProjectDetail, Rubric } from "@/lib/types";

export default function TasksAdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [projectId, setProjectId] = useState("");
  const [search, setSearch] = useState("");

  const filters = useMemo(() => ({
    status: status || undefined,
    project_id: projectId || undefined,
    search: search || undefined,
  }), [status, projectId, search]);

  const tasks = useQuery(v2queries.tasks(page, filters));
  const projects = useQuery(v1queries.projects());
  const datasets = useQuery(v1queries.datasets());
  const rubrics = useQuery(v1queries.rubrics());
  const users = useQuery(v2queries.users());

  const m = useTaskMutations(() => toast("success", "Done"));
  const [generateOpen, setGenerateOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [assignFor, setAssignFor] = useState<PlatformTask | null>(null);
  const [assignee, setAssignee] = useState("");
  const [cancelFor, setCancelFor] = useState<PlatformTask | null>(null);

  const [gen, setGen] = useState({ project_id: "", dataset_id: "", rubric_id: "", limit: "", priority: "normal", difficulty: "medium", estimated_minutes: "", max_attempts: "2" });
  const [manual, setManual] = useState({ project_id: "", title: "", instructions: "", priority: "normal" });

  const projectsList = (projects.data ?? []) as unknown as ProjectDetail[];
  const adminableProjects = projectsList.filter((p) => p.is_admin);
  const testers = (users.data ?? []).filter((u) => u.role === "tester");

  const createGen = useMutation({
    mutationFn: () => api.post<{ created: number }>("/tasks/generate", {
      project_id: Number(gen.project_id),
      dataset_id: Number(gen.dataset_id),
      rubric_id: Number(gen.rubric_id),
      limit: gen.limit ? Number(gen.limit) : undefined,
      priority: gen.priority,
      difficulty: gen.difficulty,
      estimated_minutes: gen.estimated_minutes ? Number(gen.estimated_minutes) : undefined,
      max_attempts: Number(gen.max_attempts),
    }),
    onSuccess: (r) => {
      qc.invalidateQueries();
      setGenerateOpen(false);
      toast("success", "Tasks generated", `${r.created} task(s) created and published.`);
    },
    onError: (e) => toast("error", "Generation failed", (e as Error).message),
  });

  const createManual = useMutation({
    mutationFn: () => m.createManual({
      project_id: Number(manual.project_id),
      title: manual.title,
      instructions: manual.instructions || undefined,
      priority: manual.priority,
    }),
    onSuccess: () => {
      qc.invalidateQueries();
      setManualOpen(false);
      toast("success", "Task created");
    },
    onError: (e) => toast("error", "Could not create task", (e as Error).message),
  });

  const assign = useMutation({
    mutationFn: () => m.assign(assignFor!.id, Number(assignee)),
    onSuccess: () => { qc.invalidateQueries(); setAssignFor(null); toast("success", "Task assigned"); },
    onError: (e) => { setAssignFor(null); toast("error", "Assignment failed", (e as Error).message); },
  });

  const doCancel = useMutation({
    mutationFn: () => m.cancel(cancelFor!.id),
    onSuccess: () => { qc.invalidateQueries(); setCancelFor(null); toast("success", "Task cancelled"); },
    onError: (e) => { setCancelFor(null); toast("error", "Cancel failed", (e as Error).message); },
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Task management</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Generate tasks from dataset records, assign them to testers and track the full lifecycle.
            Exclusive claiming prevents two workers on the same task.
          </p>
        </div>
        <div className="flex gap-2">
          <a href="/api/exports/tasks?format=csv" target="_blank" rel="noreferrer">
            <Button variant="ghost" size="sm"><FileDown className="h-4 w-4" /> Export CSV</Button>
          </a>
          <Button variant="secondary" onClick={() => { setManual({ ...manual, project_id: adminableProjects[0]?.id?.toString() ?? "" }); setManualOpen(true); }}>
            <Plus className="h-4 w-4" /> Manual task
          </Button>
          <Button onClick={() => { setGen((g) => ({ ...g, project_id: adminableProjects[0]?.id?.toString() ?? "" })); setGenerateOpen(true); }}>
            <Wand2 className="h-4 w-4" /> Generate from dataset
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Tasks</CardTitle>
            <CardDescription>{tasks.data?.total ?? 0} tasks in your visible projects.</CardDescription>
          </div>
          <div className="flex gap-2">
            <NativeSelect aria-label="Filter by status" className="h-8 w-40 text-xs" value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">All statuses</option>
              {Object.entries(TASK_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </NativeSelect>
            <NativeSelect aria-label="Filter by project" className="h-8 w-44 text-xs" value={projectId}
              onChange={(e) => { setProjectId(e.target.value); setPage(1); }}>
              <option value="">All projects</option>
              {projectsList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
            <Input aria-label="Search tasks" placeholder="Search…" className="h-8 w-40 text-xs"
              value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          </div>
        </CardHeader>
        <CardContent>
          {tasks.isLoading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : tasks.isError ? (
            <ErrorState message={(tasks.error as Error)?.message} retry={tasks.refetch} />
          ) : tasks.data!.items.length === 0 ? (
            <EmptyState icon={ListChecks} title="No tasks match"
              description="Generate tasks from a dataset or create them manually." />
          ) : (
            <>
              <Table>
                <THead>
                  <TR>
                    <TH>Task</TH><TH>Project</TH><TH>Status</TH><TH>Priority</TH>
                    <TH>Assignee</TH><TH>Created</TH><TH />
                  </TR>
                </THead>
                <TBody>
                  {tasks.data!.items.map((t) => (
                    <TR key={t.id}>
                      <TD>
                        <div className="max-w-[280px] truncate text-sm font-medium text-fg">{t.title}</div>
                        <div className="text-xs text-fg-muted">{t.task_type} · {t.difficulty}</div>
                      </TD>
                      <TD className="text-xs text-fg-muted">{t.project_name}</TD>
                      <TD><StatusBadge status={t.status} /></TD>
                      <TD><Badge variant={t.priority === "urgent" ? "danger" : t.priority === "high" ? "warning" : "neutral"}>{t.priority}</Badge></TD>
                      <TD className="text-xs">{t.assigned_tester_name ?? "—"}</TD>
                      <TD className="text-xs text-fg-muted">{fmtDateTime(t.created_at)}</TD>
                      <TD className="text-right">
                        <div className="flex justify-end gap-1">
                          {(t.status === "available" || t.status === "draft") && (
                            <Button variant="ghost" size="sm" onClick={() => { setAssignFor(t); setAssignee(""); }} title="Assign">
                              <Users className="h-3.5 w-3.5" />
                            </Button>
                          )}
                          {(t.status === "assigned" || t.status === "in_progress") && (
                            <Button variant="ghost" size="sm" onClick={() => { setAssignFor(t); setAssignee(""); }} title="Reassign">
                              <UserCog className="h-3.5 w-3.5" />
                            </Button>
                          )}
                          {t.status !== "approved" && t.status !== "cancelled" && (
                            <Button variant="ghost" size="sm" className="text-danger hover:text-danger"
                              onClick={() => setCancelFor(t)} title="Cancel task">
                              <Ban className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {tasks.data!.total > 25 && (
                <div className="mt-3 flex items-center justify-between text-sm text-fg-muted">
                  <span>Page {tasks.data!.page} of {Math.ceil(tasks.data!.total / 25)}</span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                    <Button variant="outline" size="sm" disabled={page >= Math.ceil(tasks.data!.total / 25)} onClick={() => setPage((p) => p + 1)}>Next</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Generate dialog */}
      <Dialog open={generateOpen} onOpenChange={setGenerateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate tasks from dataset</DialogTitle>
            <DialogDescription>
              One task per record. Records that already have a task in the project are skipped.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="g-project">Project</Label>
              <NativeSelect id="g-project" value={gen.project_id}
                onChange={(e) => setGen((g) => ({ ...g, project_id: e.target.value, dataset_id: "" }))}>
                <option value="">— Select —</option>
                {adminableProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="g-dataset">Dataset</Label>
              <NativeSelect id="g-dataset" value={gen.dataset_id} onChange={(e) => setGen((g) => ({ ...g, dataset_id: e.target.value }))}>
                <option value="">— Select —</option>
                {(datasets.data as Dataset[] | undefined)?.filter((d) => d.project_id === Number(gen.project_id) && d.status === "active")
                  .map((d) => <option key={d.id} value={d.id}>{d.name} (v{d.current_version})</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="g-rubric">Rubric</Label>
              <NativeSelect id="g-rubric" value={gen.rubric_id} onChange={(e) => setGen((g) => ({ ...g, rubric_id: e.target.value }))}>
                <option value="">— Select —</option>
                {(rubrics.data as Rubric[] | undefined)?.map((r) => <option key={r.id} value={r.id}>{r.name} (v{r.current_version})</option>)}
              </NativeSelect>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="g-limit">Limit (optional)</Label>
                <Input id="g-limit" type="number" min={1} value={gen.limit}
                  onChange={(e) => setGen((g) => ({ ...g, limit: e.target.value }))} placeholder="All records" />
              </div>
              <div>
                <Label htmlFor="g-priority">Priority</Label>
                <NativeSelect id="g-priority" value={gen.priority} onChange={(e) => setGen((g) => ({ ...g, priority: e.target.value }))}>
                  <option value="low">low</option><option value="normal">normal</option>
                  <option value="high">high</option><option value="urgent">urgent</option>
                </NativeSelect>
              </div>
              <div>
                <Label htmlFor="g-difficulty">Difficulty</Label>
                <NativeSelect id="g-difficulty" value={gen.difficulty} onChange={(e) => setGen((g) => ({ ...g, difficulty: e.target.value }))}>
                  <option value="easy">easy</option><option value="medium">medium</option>
                  <option value="hard">hard</option><option value="expert">expert</option>
                </NativeSelect>
              </div>
              <div>
                <Label htmlFor="g-attempts">Max attempts</Label>
                <Input id="g-attempts" type="number" min={1} value={gen.max_attempts}
                  onChange={(e) => setGen((g) => ({ ...g, max_attempts: e.target.value }))} />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGenerateOpen(false)}>Cancel</Button>
            <Button onClick={() => createGen.mutate()} disabled={!gen.project_id || !gen.dataset_id || !gen.rubric_id || createGen.isPending}>
              {createGen.isPending ? "Generating…" : "Generate tasks"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual task dialog */}
      <Dialog open={manualOpen} onOpenChange={setManualOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create manual task</DialogTitle>
            <DialogDescription>Published directly to the project's marketplace.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="m-project">Project</Label>
              <NativeSelect id="m-project" value={manual.project_id}
                onChange={(e) => setManual((m2) => ({ ...m2, project_id: e.target.value }))}>
                <option value="">— Select —</option>
                {adminableProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="m-title">Title</Label>
              <Input id="m-title" value={manual.title} onChange={(e) => setManual((m2) => ({ ...m2, title: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="m-instructions">Instructions</Label>
              <Input id="m-instructions" value={manual.instructions}
                onChange={(e) => setManual((m2) => ({ ...m2, instructions: e.target.value }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setManualOpen(false)}>Cancel</Button>
            <Button onClick={() => createManual.mutate()} disabled={!manual.project_id || !manual.title.trim() || createManual.isPending}>
              {createManual.isPending ? "Creating…" : "Create task"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign dialog */}
      <Dialog open={assignFor !== null} onOpenChange={(o) => !o && setAssignFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{assignFor?.status === "available" || assignFor?.status === "draft" ? "Assign task" : "Reassign task"}</DialogTitle>
            <DialogDescription>
              {assignFor?.title} — the assignee gets a notification and exclusive access to this task.
            </DialogDescription>
          </DialogHeader>
          <NativeSelect aria-label="Assign to tester" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">— Select tester —</option>
            {testers.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.email})</option>)}
          </NativeSelect>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignFor(null)}>Cancel</Button>
            <Button onClick={() => assign.mutate()} disabled={!assignee || assign.isPending}>
              {assign.isPending ? "Assigning…" : "Confirm assignment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={cancelFor !== null}
        onOpenChange={(o) => !o && setCancelFor(null)}
        title={`Cancel task "${cancelFor?.title}"?`}
        description="Cancelled tasks are removed from the marketplace. History is preserved in the audit trail."
        confirmLabel="Cancel task"
        destructive
        busy={doCancel.isPending}
        onConfirm={() => doCancel.mutate()}
      />
    </div>
  );
}
