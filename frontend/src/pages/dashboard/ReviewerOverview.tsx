// Reviewer overview: queue status, decisions, quality metrics.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Inbox, CheckCircle2, XCircle, Undo2, Clock } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/utils";
import type { Paginated, SubmissionSummary } from "@/lib/types";

export default function ReviewerOverview() {
  const { user } = useAuth();
  const queue = useQuery(v2queries.reviewQueue(1));
  const subs = useQuery({
    queryKey: ["reviewer-my-decisions"],
    queryFn: () => api.get<Paginated<SubmissionSummary>>("/submissions?page=1&page_size=100"),
  });

  if (queue.isLoading || subs.isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (queue.isError) return <ErrorState message={(queue.error as Error)?.message} retry={queue.refetch} />;

  const all = subs.data?.items ?? [];
  const myDecisions = all.filter((s: { reviews?: { reviewer_id: number }[] }) =>
    (s.reviews ?? []).some((rv) => rv.reviewer_id === user?.id));
  const approved = myDecisions.filter((s: { status: string }) => s.status === "approved").length;
  const rejected = myDecisions.filter((s: { status: string }) => s.status === "rejected").length;
  const revisions = myDecisions.filter((s: { status: string }) => s.status === "revision_required").length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Reviewer workspace</h1>
          <p className="mt-1 text-sm text-fg-muted">Review submitted work, request revisions and track quality.</p>
        </div>
        <Link to="/review-queue"><Button><Inbox className="h-4 w-4" /> Open review queue</Button></Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
        {[
          { icon: Inbox, label: "Pending in queue", value: queue.data?.total ?? 0, tone: "bg-[rgba(245,158,11,0.12)] text-warn" },
          { icon: Clock, label: "Under review", value: all.filter((s: { status: string }) => s.status === "under_review").length, tone: "bg-[rgba(96,165,250,0.12)] text-info" },
          { icon: CheckCircle2, label: "My approvals", value: approved, tone: "bg-[rgba(34,197,94,0.12)] text-ok" },
          { icon: XCircle, label: "My rejections", value: rejected, tone: "bg-[rgba(239,68,68,0.12)] text-danger" },
          { icon: Undo2, label: "Revisions requested", value: revisions, tone: "" },
        ].map((s) => (
          <Card key={s.label}>
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
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Next in your queue</CardTitle>
          <CardDescription>Submitted work awaiting a decision. Tester identity is hidden for blind review.</CardDescription>
        </CardHeader>
        <CardContent>
          {(queue.data?.items ?? []).slice(0, 6).map((s) => (
            <Link key={s.id} to={`/review-queue/${s.id}`}
              className="mb-2 flex items-center justify-between gap-3 rounded-md border border-border p-3.5 transition-colors hover:border-teal/50 hover:bg-base-panel/40">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-fg">{s.task_title}</div>
                <div className="mt-0.5 text-xs text-fg-muted">
                  {s.project_name} · attempt {s.attempt_number} · {fmtDateTime(s.submitted_at)}
                </div>
              </div>
              <StatusBadge status={s.status} />
            </Link>
          ))}
          {(queue.data?.items ?? []).length === 0 && (
            <EmptyState icon={Inbox} title="Queue is clear"
              description="New submissions from your projects will appear here." />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
