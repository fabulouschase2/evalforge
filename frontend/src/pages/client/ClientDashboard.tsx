// Client dashboard — real org-scoped stats from /api/client/dashboard.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, CheckCircle2, Clock, FileDown, FolderKanban, Inbox, ListChecks, XCircle } from "lucide-react";
import { clientQueries } from "@/api/clientHooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";
import { PROJECT_TYPE_LABELS } from "@/lib/roles";

function Stat({ icon: Icon, label, value, hint, tone = "default" }: {
  icon: React.ElementType; label: string; value: React.ReactNode; hint?: string;
  tone?: "default" | "ok" | "warn" | "danger";
}) {
  const toneClass = tone === "ok" ? "text-ok" : tone === "warn" ? "text-amber-400" : tone === "danger" ? "text-danger" : "text-fg";
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className="rounded-lg bg-surface-raised p-2"><Icon className="h-5 w-5 text-teal" /></div>
        <div>
          <div className={`text-xl font-bold ${toneClass}`}>{value}</div>
          <div className="text-xs text-fg-muted">{label}{hint ? ` · ${hint}` : ""}</div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ClientDashboard() {
  const q = useQuery(clientQueries.dashboard());

  if (q.isLoading) {
    return <div className="space-y-4"><TableSkeleton rows={6} cols={4} /></div>;
  }
  if (q.isError) {
    return <ErrorState message={(q.error as Error)?.message} retry={q.refetch} />;
  }
  const d = q.data!;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Welcome, {d.organization.name}</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Progress across your projects. Worker identities and internal notes are never shown here.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={FolderKanban} label="Active projects" value={d.projects.active} hint={`${d.projects.total} total`} />
        <Stat icon={CheckCircle2} label="Completed projects" value={d.projects.completed} tone="ok" />
        <Stat icon={Clock} label="Pending requests" value={d.requests.pending} tone={d.requests.pending ? "warn" : "default"} />
        <Stat icon={FileDown} label="Deliverables" value={d.deliverables} />
        <Stat icon={ListChecks} label="Total tasks" value={d.tasks.total} />
        <Stat icon={CheckCircle2} label="Approved results" value={d.tasks.approved} tone="ok" />
        <Stat icon={XCircle} label="Rejected / revisions" value={d.tasks.rejected} tone={d.tasks.rejected ? "danger" : "default"} />
        <Stat icon={Inbox} label="Unread messages" value={d.unread_messages} tone={d.unread_messages ? "warn" : "default"} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Delivery progress</CardTitle>
          <CardDescription>Approved results / total tasks across all your projects.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-raised">
              <div
                className="h-full rounded-full bg-teal transition-all"
                style={{ width: `${Math.round((d.tasks.completion_rate ?? 0) * 100)}%` }}
              />
            </div>
            <span className="text-sm font-semibold text-fg">{pct(d.tasks.completion_rate)}</span>
          </div>
          <p className="mt-2 text-xs text-fg-muted">
            {d.tasks.completion_rate === null
              ? "No tasks have been generated yet — progress becomes available once work starts."
              : `${d.tasks.approved} of ${d.tasks.total} tasks approved · ${d.tasks.under_review} under review · ${d.tasks.in_progress} in progress.`}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>Project, request and deliverable events across your organization.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Link to="/client/requests"><Button variant="secondary" size="sm">New request</Button></Link>
            <Link to="/client/projects"><Button variant="secondary" size="sm">My projects</Button></Link>
          </div>
        </CardHeader>
        <CardContent>
          {d.recent_activity.length === 0 ? (
            <EmptyState
              title="No activity yet"
              description="Submit a project request to get started — our team reviews requests quickly."
            />
          ) : (
            <ul className="divide-y divide-line">
              {d.recent_activity.map((e, i) => (
                <li key={i} className="flex items-start gap-3 py-2.5">
                  <Badge variant={e.kind === "deliverable" ? "success" : e.kind === "request" ? "info" : "neutral"}>
                    {e.kind}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-fg">{e.title}</div>
                    <div className="text-xs text-fg-muted">{e.detail}</div>
                  </div>
                  <div className="whitespace-nowrap text-xs text-fg-muted">{fmtDateTime(e.at)}</div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Project types we deliver</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-1.5">
          {Object.entries(PROJECT_TYPE_LABELS).map(([k, label]) => (
            <Badge key={k} variant="neutral">{label}</Badge>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
