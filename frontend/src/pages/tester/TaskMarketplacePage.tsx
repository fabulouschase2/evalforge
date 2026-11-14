// Task marketplace: eligible available tasks with one-click claiming.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ListChecks, Play } from "lucide-react";
import { v2queries, useTaskMutations } from "@/api/v2hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { truncate } from "@/lib/utils";

export default function TaskMarketplacePage() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const tasks = useQuery(v2queries.availableTasks(page));
  const m = useTaskMutations(() => toast("success", "Task claimed", "It is now in My Tasks — open it to start working."));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Available tasks</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Tasks from projects you are assigned to. Claiming a task gives you exclusive access to it.
        </p>
      </div>

      {tasks.isLoading ? (
        <TableSkeleton rows={5} cols={3} />
      ) : tasks.isError ? (
        <ErrorState message={(tasks.error as Error)?.message} retry={tasks.refetch} />
      ) : tasks.data!.items.length === 0 ? (
        <EmptyState icon={ListChecks} title="No tasks available right now"
          description="New tasks appear here as soon as project admins publish them for your projects." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {tasks.data!.items.map((t) => (
              <Card key={t.id} className="flex h-full flex-col">
                <CardHeader>
                  <CardTitle className="flex items-start justify-between gap-2">
                    <span className="line-clamp-2 text-sm">{t.title}</span>
                    <Badge variant={t.priority === "urgent" ? "danger" : t.priority === "high" ? "warning" : "neutral"}>
                      {t.priority}
                    </Badge>
                  </CardTitle>
                  <CardDescription>
                    {t.project_name} · {t.task_type.replace(/_/g, " ")} · {t.difficulty}
                    {t.estimated_minutes ? ` · ~${t.estimated_minutes} min` : ""}
                    {t.deadline ? ` · due ${new Date(t.deadline).toLocaleDateString()}` : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent className="mt-auto flex items-center justify-between gap-2">
                  <div className="min-w-0 text-xs text-fg-muted">
                    {t.record ? truncate(t.record.prompt, 60) : t.instructions ? truncate(t.instructions, 60) : "No preview"}
                  </div>
                  <Button size="sm" onClick={() => { setClaimingId(t.id); m.claim(t.id).finally(() => setClaimingId(null)); }}
                    disabled={claimingId !== null}>
                    {claimingId === t.id ? "Claiming…" : (<><Play className="h-3.5 w-3.5" /> Start task</>)}
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
          {tasks.data!.total > 20 && (
            <div className="flex items-center justify-between text-sm text-fg-muted">
              <span>Page {tasks.data!.page} of {Math.ceil(tasks.data!.total / 20)}</span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" disabled={page >= Math.ceil(tasks.data!.total / 20)} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
