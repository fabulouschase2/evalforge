// Tester submissions & feedback: full history with reviewer decisions and comments.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquareWarning } from "lucide-react";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";

export default function SubmissionsPage() {
  const [status, setStatus] = useState("");
  const subs = useQuery(v2queries.mySubmissions(status || undefined));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Submissions &amp; feedback</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Every attempt you have submitted, with reviewer decisions and quality feedback.
          </p>
        </div>
        <NativeSelect aria-label="Filter submissions by status" className="w-52" value={status}
          onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option value="submitted">submitted</option>
          <option value="under_review">under review</option>
          <option value="approved">approved</option>
          <option value="rejected">rejected</option>
          <option value="revision_required">revision required</option>
        </NativeSelect>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>History ({subs.data?.total ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {subs.isLoading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : subs.isError ? (
            <ErrorState message={(subs.error as Error)?.message} retry={subs.refetch} />
          ) : subs.data!.items.length === 0 ? (
            <EmptyState icon={MessageSquareWarning} title="No submissions yet"
              description="Claim a task and submit your first evaluation." />
          ) : (
            <div className="space-y-3">
              {subs.data!.items.map((s) => (
                <div key={s.id} className="rounded-md border border-border p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-fg">{s.task_title}</div>
                      <div className="text-xs text-fg-muted">
                        {s.project_name} · attempt {s.attempt_number} · submitted {fmtDateTime(s.submitted_at)}
                      </div>
                    </div>
                    <StatusBadge status={s.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
