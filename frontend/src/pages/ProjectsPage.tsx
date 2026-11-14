import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, FolderKanban } from "lucide-react";
import { api } from "@/lib/api";
import { queries as v1queries } from "@/api/hooks";
import { v2queries } from "@/api/v2hooks";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";
import { PROJECT_TYPE_LABELS } from "@/lib/roles";
import type { ProjectDetail } from "@/lib/types";

export default function ProjectsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();

  const { data, isLoading, isError, error, refetch } = useQuery(v1queries.projects());
  const orgs = useQuery(v2queries.organizations());
  const types = useQuery(v2queries.projectTypes());
  const projectsList = (data ?? []) as unknown as ProjectDetail[];

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "", description: "", client: "", project_type: "ai_response_evaluation",
    instructions: "", quality_requirements: "", target_task_volume: "", deadline: "",
    blind_review: "true", status: "active",
  });

  const create = useMutation({
    mutationFn: () => api.post<ProjectDetail>("/projects", {
      name: form.name,
      description: form.description || null,
      client: form.client || null,
      project_type: form.project_type,
      instructions: form.instructions || null,
      quality_requirements: form.quality_requirements || null,
      target_task_volume: form.target_task_volume ? Number(form.target_task_volume) : null,
      deadline: form.deadline || null,
      blind_review: form.blind_review === "true",
      status: form.status,
    }),
    onSuccess: (p) => {
      qc.invalidateQueries();
      setOpen(false);
      toast("success", "Project created", `${p.name} — add members and generate tasks from its detail page.`);
    },
    onError: (e) => toast("error", "Could not create project", (e as Error).message),
  });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">Projects</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Each project has its own datasets, task queues, workers, reviewers and analytics.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New project</Button>
      </div>

      {isLoading ? (
        <TableSkeleton rows={4} cols={3} />
      ) : isError ? (
        <ErrorState message={(error as Error)?.message} retry={refetch} />
      ) : projectsList.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Projects organize your evaluation work — create one to start collecting data and distributing tasks."
          action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New project</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projectsList.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="group">
              <Card className="h-full transition-colors group-hover:border-teal/50">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <FolderKanban className="h-4 w-4 shrink-0 text-teal" />
                      <span className="truncate">{p.name}</span>
                    </span>
                    <Badge variant={p.status === "active" ? "success" : "neutral"}>{p.status}</Badge>
                  </CardTitle>
                  <CardDescription className="line-clamp-2">{p.description ?? "No description"}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5 text-[11px]">
                    <Badge variant="info">{PROJECT_TYPE_LABELS[p.project_type] ?? p.project_type}</Badge>
                    {p.is_demo && <Badge variant="warning">DEMO</Badge>}
                  </div>
                  <div className="mt-2 text-xs text-fg-muted">
                    {p.member_count} members · {p.task_count} tasks · {p.dataset_count} datasets
                  </div>
                  <div className="mt-1 text-xs text-fg-muted">Created {fmtDateTime(p.created_at)}</div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Create project</DialogTitle>
            <DialogDescription>Configure the evaluation engagement. You become its admin.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="p-name">Project name</Label>
              <Input id="p-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-desc">Description</Label>
              <Textarea id="p-desc" className="font-sans text-sm" value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="p-type">Project type</Label>
              <NativeSelect id="p-type" value={form.project_type}
                onChange={(e) => setForm((f) => ({ ...f, project_type: e.target.value }))}>
                {(types.data?.types ?? ["ai_response_evaluation"]).map((t) => (
                  <option key={t} value={t}>{PROJECT_TYPE_LABELS[t] ?? t}</option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="p-client">Client / organization</Label>
              <Input id="p-client" value={form.client} onChange={(e) => setForm((f) => ({ ...f, client: e.target.value }))}
                placeholder="e.g. Acme AI" />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-instructions">Instructions for workers</Label>
              <Textarea id="p-instructions" className="font-sans text-sm" value={form.instructions}
                onChange={(e) => setForm((f) => ({ ...f, instructions: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="p-deadline">Deadline</Label>
              <Input id="p-deadline" type="date" value={form.deadline}
                onChange={(e) => setForm((f) => ({ ...f, deadline: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="p-volume">Target task volume</Label>
              <Input id="p-volume" type="number" min={0} value={form.target_task_volume}
                onChange={(e) => setForm((f) => ({ ...f, target_task_volume: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="p-blind">Blind review</Label>
              <NativeSelect id="p-blind" value={form.blind_review} onChange={(e) => setForm((f) => ({ ...f, blind_review: e.target.value }))}>
                <option value="true">On — reviewers never see tester identity</option>
                <option value="false">Off</option>
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="p-qreq">Quality requirements</Label>
              <Input id="p-qreq" value={form.quality_requirements}
                onChange={(e) => setForm((f) => ({ ...f, quality_requirements: e.target.value }))}
                placeholder="e.g. 95% approval threshold" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!form.name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
