// Reviewer queue: submitted work awaiting decisions in the reviewer's projects.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Inbox } from "lucide-react";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime } from "@/lib/utils";

export default function ReviewQueuePage() {
  const [page, setPage] = useState(1);
  const queue = useQuery(v2queries.reviewQueue(page));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Review queue</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Submitted tasks from your projects. Tester identity is hidden while the review is blind
          (configurable per project). Claiming marks the submission as under review.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Awaiting review ({queue.data?.total ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {queue.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : queue.isError ? (
            <ErrorState message={(queue.error as Error)?.message} retry={queue.refetch} />
          ) : queue.data!.items.length === 0 ? (
            <EmptyState icon={Inbox} title="Nothing to review"
              description="Submissions from your projects appear here as testers complete their tasks." />
          ) : (
            <div className="space-y-2">
              {queue.data!.items.map((s) => (
                <Link key={s.id} to={`/review-queue/${s.id}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border p-3.5 transition-colors hover:border-teal/50 hover:bg-base-panel/40">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-fg">{s.task_title}</div>
                    <div className="mt-0.5 text-xs text-fg-muted">
                      {s.project_name} · attempt {s.attempt_number} · {fmtDateTime(s.submitted_at)}
                      {s.label && <Badge variant="neutral" className="ml-2">label: {s.label}</Badge>}
                    </div>
                  </div>
                  <span className="rounded-md bg-teal px-3 py-1.5 text-xs font-semibold text-[#0B1518]">
                    Review →
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
