// Project detail: overview stats, membership management, task/dataset summaries.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, UserPlus, Database, ListChecks, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries } from "@/api/v2hooks";
import { queries as v1queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { TASK_STATUS_LABELS, PROJECT_TYPE_LABELS } from "@/lib/roles";
import { fmtDateTime } from "@/lib/utils";
import type { PlatformTask, ProjectDetail, ProjectMember } from "@/lib/types";

export default function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const toast = useToast();

  const project = useQuery(v2queries.project(projectId));
  const members = useQuery(v2queries.members(projectId));
  const tasks = useQuery({
    queryKey: ["v2-project-tasks", projectId],
    queryFn: () => api.get<{ items: PlatformTask[] }>(`/tasks?project_id=${projectId}&page_size=100`),
  });
  const users = useQuery(v2queries.users());

  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ email: "", role: "tester" });
  const [removeFor, setRemoveFor] = useState<ProjectMember | null>(null);

  const addMember = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/members`, form),
    onSuccess: () => { qc.invalidateQueries(); setAddOpen(false); toast("success", "Member added"); },
    onError: (e) => toast("error", "Could not add member", (e as Error).message),
  });

  const removeMember = useMutation({
    mutationFn: () => api.del(`/projects/${projectId}/members/${removeFor!.id}`),
    onSuccess: () => { qc.invalidateQueries(); setRemoveFor(null); toast("success", "Member removed"); },
    onError: (e) => { setRemoveFor(null); toast("error", "Could not remove member", (e as Error).message); },
  });

  if (project.isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (project.isError) return <ErrorState message={(project.error as Error)?.message} retry={project.refetch} />;

  const p = project.data;
  if (!p) return null;
  const taskCounts = (tasks.data?.items ?? []).reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/projects" className="text-fg-muted hover:text-fg"><ArrowLeft className="h-4 w-4" /></Link>
            <h1 className="text-xl font-bold text-fg">{p.name}</h1>
            <Badge variant={p.status === "active" ? "success" : "neutral"}>{p.status}</Badge>
          </div>
          <p className="mt-1 text-sm text-fg-muted">{p.description ?? "No description"}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="info">{PROJECT_TYPE_LABELS[p.project_type] ?? p.project_type}</Badge>
          {p.deadline && <Badge variant="warning">due {new Date(p.deadline).toLocaleDateString()}</Badge>}
          {p.target_task_volume && <Badge variant="neutral">target {p.target_task_volume} tasks</Badge>}
          <Badge variant={p.blind_review ? "default" : "neutral"}>{p.blind_review ? "blind review on" : "blind review off"}</Badge>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Link to={`/projects/${p.id}/client`}>
          <Button variant="secondary" size="sm">Client engagement</Button>
        </Link>
      </div>

      {p.instructions && (
        <Card>
          <CardHeader><CardTitle>Project instructions</CardTitle></CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm text-fg">{p.instructions}</CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Members</div><div className="mt-1 text-2xl font-bold text-fg">{p.member_count}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Datasets</div><div className="mt-1 text-2xl font-bold text-fg">{p.dataset_count}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Tasks</div><div className="mt-1 text-2xl font-bold text-fg">{p.task_count}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-fg-muted">Approved</div><div className="mt-1 text-2xl font-bold text-ok">{taskCounts.approved ?? 0}</div></CardContent></Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Members</CardTitle>
              <CardDescription>Membership controls project access for every user.</CardDescription>
            </div>
            {p.is_admin && (
              <Button size="sm" onClick={() => setAddOpen(true)}><UserPlus className="h-3.5 w-3.5" /> Add member</Button>
            )}
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <THead><TR><TH>User</TH><TH>Membership</TH><TH>Added</TH>{p.is_admin && <TH />}</TR></THead>
              <TBody>
                {(members.data ?? []).map((m) => (
                  <TR key={m.id}>
                    <TD>
                      <div className="text-sm font-medium text-fg">{m.name}</div>
                      <div className="text-xs text-fg-muted">{m.email}</div>
                    </TD>
                    <TD><Badge variant={m.role === "admin" ? "default" : m.role === "tester" ? "info" : "neutral"}>{m.role}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(m.added_at)}</TD>
                    {p.is_admin && (
                      <TD className="text-right">
                        <Button variant="ghost" size="sm" className="text-danger hover:text-danger"
                          onClick={() => setRemoveFor(m)} title="Remove from project">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Task pipeline</CardTitle>
            <CardDescription>
              <Link to="/tasks" className="text-teal hover:underline">Open task management →</Link>
            </CardDescription>
          </CardHeader>
          <CardContent>
            {Object.entries(taskCounts).length === 0 ? (
              <div className="text-sm text-fg-muted">No tasks in this project yet.</div>
            ) : (
              <div className="space-y-2">
                {Object.entries(taskCounts).map(([status, count]) => (
                  <div key={status} className="flex items-center justify-between">
                    <span className="text-sm text-fg-muted">{TASK_STATUS_LABELS[status] ?? status}</span>
                    <span className="text-sm font-semibold text-fg">{count}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 flex gap-2">
              <Link to="/data-collection" className="flex-1">
                <Button variant="secondary" size="sm" className="w-full"><Database className="h-3.5 w-3.5" /> Collect data</Button>
              </Link>
              <Link to={`/tasks`} className="flex-1">
                <Button variant="secondary" size="sm" className="w-full"><ListChecks className="h-3.5 w-3.5" /> Manage tasks</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add member to {p.name}</DialogTitle>
            <DialogDescription>Membership role must match the user's platform role (tester joins as tester, reviewer as reviewer).</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="pm-email">User email</Label>
              <Input id="pm-email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="pm-role">Membership role</Label>
              <NativeSelect id="pm-role" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                <option value="tester">tester</option>
                <option value="reviewer">reviewer</option>
                <option value="admin">admin</option>
              </NativeSelect>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={() => addMember.mutate()} disabled={!form.email || addMember.isPending}>
              {addMember.isPending ? "Adding…" : "Add member"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removeFor !== null}
        onOpenChange={(o) => !o && setRemoveFor(null)}
        title={`Remove ${removeFor?.name} from the project?`}
        description="They immediately lose access to this project's tasks and data."
        confirmLabel="Remove member"
        destructive
        busy={removeMember.isPending}
        onConfirm={() => removeMember.mutate()}
      />
    </div>
  );
}
