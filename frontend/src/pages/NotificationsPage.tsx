// Shared notifications page: history with read/unread management.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries } from "@/api/v2hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";
import type { NotificationItem } from "@/lib/types";

const TYPE_TONES: Record<string, string> = {
  task_assigned: "info", submission_received: "warning", review_decision: "success",
  revision_requested: "danger", adjudication_decided: "info", project_assigned: "info",
};

export default function NotificationsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const notes = useQuery(v2queries.notifications(page, unreadOnly));

  const markAll = useMutationMarkAll();

  function useMutationMarkAll() {
    const toast2 = toast;
    return {
      isPending: false,
      mutate: async () => {
        await api.post("/notifications/read-all");
        await qc.invalidateQueries();
        toast2("success", "All notifications marked as read");
      },
    };
  }

  const markRead = async (id: number) => {
    await api.post(`/notifications/${id}/read`);
    await qc.invalidateQueries();
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Notifications</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Task assignments, review decisions, revision requests and platform updates.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => { setUnreadOnly((v) => !v); setPage(1); }}>
            {unreadOnly ? "Showing unread" : "Show unread only"}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => markAll.mutate()}>
            <CheckCheck className="h-3.5 w-3.5" /> Mark all read
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Bell className="h-4 w-4 text-teal" /> History</CardTitle>
          <CardDescription>{notes.data?.total ?? 0} notifications.</CardDescription>
        </CardHeader>
        <CardContent>
          {notes.isLoading ? (
            <TableSkeleton rows={5} cols={3} />
          ) : notes.isError ? (
            <ErrorState message={(notes.error as Error)?.message} retry={notes.refetch} />
          ) : notes.data!.items.length === 0 ? (
            <EmptyState icon={Bell} title="No notifications" description="You're all caught up." />
          ) : (
            <div className="space-y-2">
              {notes.data!.items.map((n: NotificationItem) => (
                <button key={n.id} type="button"
                  onClick={() => !n.read && markRead(n.id)}
                  className={`w-full rounded-md border p-3.5 text-left transition-colors ${
                    n.read ? "border-border opacity-70" : "border-teal/40 bg-teal-soft/40 hover:border-teal/70"
                  }`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={(TYPE_TONES[n.type] ?? "neutral") as "info"}>
                      {n.type.replace(/_/g, " ")}
                    </Badge>
                    <span className="text-sm font-medium text-fg">{n.title}</span>
                    {!n.read && <Badge variant="warning">new</Badge>}
                    <span className="ml-auto text-xs text-fg-muted">{fmtDateTime(n.created_at)}</span>
                  </div>
                  {n.body && <p className="mt-1 text-sm text-fg-muted">{n.body}</p>}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
