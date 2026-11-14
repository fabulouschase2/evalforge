// Tester overview: personal pipeline, stats and quick links.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ListChecks, Loader2, CheckCircle2, XCircle, Clock, RefreshCcw } from "lucide-react";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/utils";

export default function TesterOverview() {
  const { user } = useAuth();
  const mine = useQuery(v2queries.myTasks(undefined));
  const subs = useQuery(v2queries.mySubmissions(undefined));

  if (mine.isLoading || subs.isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (mine.isError) return <ErrorState message={(mine.error as Error)?.message} retry={mine.refetch} />;

  const tasks = mine.data?.items ?? [];
  const submissions = subs.data?.items ?? [];
  const inProgress = tasks.filter((t) => t.status === "assigned" || t.status === "in_progress" || t.status === "revision_required");
  const approved = submissions.filter((s) => s.status === "approved");
  const rejected = submissions.filter((s) => s.status === "rejected");
  const decided = approved.length + rejected.length;
  const approvalRate = decided ? approved.length / decided : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Welcome back, {user?.name.split(" ")[0]}</h1>
          <p className="mt-1 text-sm text-fg-muted">Your tasks, submissions and quality feedback in one place.</p>
        </div>
        <Link to="/tasks/available">
          <Button><ListChecks className="h-4 w-4" /> Browse available tasks</Button>
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
        {[
          { icon: ListChecks, label: "Assigned to me", value: inProgress.length, to: "/tasks/mine", tone: "" },
          { icon: Clock, label: "Submitted", value: submissions.filter((s) => s.status === "submitted" || s.status === "under_review").length, to: "/submissions", tone: "bg-[rgba(245,158,11,0.12)] text-warn" },
          { icon: CheckCircle2, label: "Approved", value: approved.length, to: "/submissions", tone: "bg-[rgba(34,197,94,0.12)] text-ok" },
          { icon: XCircle, label: "Rejected", value: rejected.length, to: "/submissions", tone: "bg-[rgba(239,68,68,0.12)] text-danger" },
          { icon: RefreshCcw, label: "Approval rate", value: approvalRate === null ? "—" : `${Math.round(approvalRate * 100)}%`, to: "/submissions", tone: "bg-[rgba(96,165,250,0.12)] text-info" },
        ].map((s) => (
          <Link key={s.label} to={s.to}>
            <Card className="h-full transition-colors hover:border-teal/40">
              <CardContent className="flex items-start gap-3 p-4">
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${s.tone || "bg-teal-soft text-teal"}`}>
                  <s.icon className="h-4.5 w-4.5" />
                </div>
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-fg-muted">{s.label}</div>
                  <div className="mt-0.5 text-xl font-bold text-fg">{s.value}</div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>My active tasks</CardTitle>
          <CardDescription>Tasks assigned to you that need work or are awaiting re-submission.</CardDescription>
        </CardHeader>
        <CardContent>
          {inProgress.length === 0 ? (
            <EmptyState icon={ListChecks} title="Nothing assigned right now"
              description="Claim tasks from the marketplace to get started."
              action={<Link to="/tasks/available"><Button variant="secondary">Browse tasks</Button></Link>} />
          ) : (
            <div className="space-y-2">
              {inProgress.map((t) => (
                <Link key={t.id} to={`/tasks/${t.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border p-3.5 transition-colors hover:border-teal/50 hover:bg-base-panel/40">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-fg">{t.title}</div>
                    <div className="mt-0.5 text-xs text-fg-muted">
                      {t.project_name} · {t.difficulty} · {t.estimated_minutes ?? "?"} min
                      {t.status === "revision_required" && " · revision requested"}
                    </div>
                  </div>
                  <StatusBadge status={t.status} />
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent feedback</CardTitle>
          <CardDescription>Latest reviewer decisions on your submissions.</CardDescription>
        </CardHeader>
        <CardContent>
          {submissions.slice(0, 5).map((s) => (
            <div key={s.id} className="flex items-center justify-between border-b border-border py-2.5 last:border-0">
              <div className="min-w-0">
                <div className="truncate text-sm text-fg">{s.task_title}</div>
                <div className="text-xs text-fg-muted">Attempt {s.attempt_number} · {fmtDateTime(s.submitted_at)}</div>
              </div>
              <StatusBadge status={s.status} />
            </div>
          ))}
          {submissions.length === 0 && (
            <div className="py-4 text-center text-sm text-fg-muted">No submissions yet.</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
