// My Tasks: assigned, in-progress, revision-required, submitted and decided work.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ListChecks } from "lucide-react";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";

const FILTERS = [
  { value: "", label: "All mine" },
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In progress" },
  { value: "revision_required", label: "Revision required" },
  { value: "submitted", label: "Submitted" },
  { value: "under_review", label: "Under review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
];

export default function MyTasksPage() {
  const [status, setStatus] = useState("");
  const tasks = useQuery(v2queries.myTasks(status || undefined));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">My tasks</h1>
          <p className="mt-1 text-sm text-fg-muted">Everything assigned to you, across every stage of the pipeline.</p>
        </div>
        <NativeSelect aria-label="Filter tasks by status" className="w-52" value={status}
          onChange={(e) => setStatus(e.target.value)}>
          {FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </NativeSelect>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Tasks ({tasks.data?.total ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {tasks.isLoading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : tasks.isError ? (
            <ErrorState message={(tasks.error as Error)?.message} retry={tasks.refetch} />
          ) : tasks.data!.items.length === 0 ? (
            <EmptyState icon={ListChecks} title="Nothing here"
              description="Claim available tasks to start working, or pick a different filter." />
          ) : (
            <div className="space-y-2">
              {tasks.data!.items.map((t) => (
                <div key={t.id} className="flex items-center justify-between gap-3 rounded-md border border-border p-3.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-fg">{t.title}</div>
                    <div className="mt-0.5 text-xs text-fg-muted">
                      {t.project_name} · {t.status === "revision_required" ? "revision requested · " : ""}
                      attempt {t.attempt_count}/{t.max_attempts}
                      {t.claimed_at ? ` · claimed ${fmtDateTime(t.claimed_at)}` : ""}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={t.status} />
                    {["assigned", "in_progress", "revision_required"].includes(t.status) && (
                      <Link to={`/tasks/${t.id}`}>
                        <Button size="sm">
                          {t.status === "revision_required" ? "Revise & resubmit" : t.status === "assigned" ? "Start" : "Continue"}
                        </Button>
                      </Link>
                    )}
                    {["submitted", "under_review", "approved", "rejected"].includes(t.status) && (
                      <Link to={`/submissions`} className="text-xs text-teal hover:underline">View feedback</Link>
                    )}
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
