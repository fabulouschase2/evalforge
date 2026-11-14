// Client projects: sanitized monitoring of the org's projects.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { clientQueries, type ClientProject } from "@/api/clientHooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import { PROJECT_TYPE_LABELS } from "@/lib/roles";

const STATUS_VARIANTS: Record<string, "info" | "success" | "warning" | "neutral" | "danger"> = {
  draft: "neutral", active: "info", paused: "warning", completed: "success", archived: "neutral",
};

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function ProjectDetail({ project }: { project: ClientProject }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card><CardContent className="p-4">
          <div className="text-2xl font-bold text-fg">{project.tasks.total}</div>
          <div className="text-xs text-fg-muted">Total tasks</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-2xl font-bold text-ok">{project.tasks.approved}</div>
          <div className="text-xs text-fg-muted">Approved results</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-2xl font-bold text-fg">{pct(project.tasks.completion_rate)}</div>
          <div className="text-xs text-fg-muted">Completion</div>
        </CardContent></Card>
      </div>

      <Table>
        <THead>
          <TR><TH>Pending</TH><TH>In progress</TH><TH>Under review</TH><TH>Approved</TH><TH>Rejected / revisions</TH></TR>
        </THead>
        <TBody>
          <TR>
            <TD>{project.tasks.pending}</TD><TD>{project.tasks.in_progress}</TD>
            <TD>{project.tasks.under_review}</TD><TD>{project.tasks.approved}</TD><TD>{project.tasks.rejected}</TD>
          </TR>
        </TBody>
      </Table>

      <div>
        <h3 className="text-sm font-semibold text-fg">Datasets ({project.datasets.length})</h3>
        {project.datasets.length === 0 ? (
          <p className="mt-1 text-xs text-fg-muted">No datasets uploaded yet — use the Datasets page to upload.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {project.datasets.map((d) => (
              <li key={d.id} className="flex items-center gap-2 text-sm text-fg">
                <Badge variant="neutral">v{d.current_version}</Badge>
                <span className="font-medium">{d.name}</span>
                <span className="text-xs text-fg-muted">{d.format} · {fmtDateTime(d.created_at)}</span>
                <Badge variant={d.status === "active" ? "success" : "neutral"}>{d.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>

      {project.recent_activity && project.recent_activity.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-fg">Project activity</h3>
          <ul className="mt-2 space-y-1.5">
            {project.recent_activity.map((e, i) => (
              <li key={i} className="flex items-center gap-2 text-xs text-fg-muted">
                <Badge variant="neutral">{e.kind}</Badge>
                <span className="text-fg">{e.detail}</span>
                <span className="ml-auto">{fmtDateTime(e.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-2">
        <Link to={`/client/messages?project=${project.id}`}>
          <Button variant="secondary" size="sm">Open messages</Button>
        </Link>
        <Link to={`/client/deliverables?project=${project.id}`}>
          <Button variant="secondary" size="sm">Deliverables ({project.deliverables})</Button>
        </Link>
      </div>
    </div>
  );
}

export default function ClientProjects() {
  const [status, setStatus] = useState("");
  const [detail, setDetail] = useState<ClientProject | null>(null);
  const projects = useQuery(clientQueries.projects(status || undefined));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">My projects</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Progress monitoring for your organization's projects. Team identities stay internal.
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Projects</CardTitle>
          <div className="flex gap-2">
            <NativeSelect aria-label="Filter by status" className="w-40" value={status}
              onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {["draft", "active", "paused", "completed", "archived"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </NativeSelect>
          </div>
        </CardHeader>
        <CardContent>
          {projects.isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : projects.isError ? (
            <ErrorState message={(projects.error as Error)?.message} retry={projects.refetch} />
          ) : (projects.data ?? []).length === 0 ? (
            <EmptyState title="No projects yet"
              description="Approved project requests become projects that appear here." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Project</TH><TH>Type</TH><TH>Status</TH><TH>Progress</TH><TH>Deadline</TH><TH /></TR>
              </THead>
              <TBody>
                {(projects.data ?? []).map((p) => (
                  <TR key={p.id}>
                    <TD className="max-w-[220px] truncate text-sm font-medium text-fg">{p.name}</TD>
                    <TD className="text-xs text-fg-muted">{PROJECT_TYPE_LABELS[p.project_type] ?? p.project_type}</TD>
                    <TD><Badge variant={STATUS_VARIANTS[p.status] ?? "neutral"}>{p.status}</Badge></TD>
                    <TD>
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-24 overflow-hidden rounded-full bg-surface-raised">
                          <div className="h-full rounded-full bg-teal"
                            style={{ width: `${Math.round((p.tasks.completion_rate ?? 0) * 100)}%` }} />
                        </div>
                        <span className="text-xs text-fg-muted">
                          {p.tasks.approved}/{p.tasks.total} · {pct(p.tasks.completion_rate)}
                        </span>
                      </div>
                    </TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(p.deadline)}</TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setDetail(p)}>Monitor</Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={detail !== null} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{detail?.name}</DialogTitle>
            <DialogDescription>
              <Badge variant={STATUS_VARIANTS[detail?.status ?? "draft"] ?? "neutral"}>{detail?.status}</Badge>
              {detail?.quality_requirements ? ` · Quality: ${detail.quality_requirements}` : ""}
            </DialogDescription>
          </DialogHeader>
          {detail && <ProjectDetail project={detail} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
