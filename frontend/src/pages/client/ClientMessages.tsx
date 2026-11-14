// Client messaging: project-scoped thread with the delivery team.
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { clientQueries } from "@/api/clientHooks";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { NativeSelect, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";

export default function ClientMessages() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const projects = useQuery(clientQueries.projects());
  const projectList = projects.data ?? [];
  const activeId = params.get("project")
    ? Number(params.get("project"))
    : projectList[0]?.id;
  const canWrite = user?.role === "client_owner" || user?.role === "client_project_manager";

  const messages = useQuery({
    ...clientQueries.messages(activeId ?? 0),
    enabled: activeId != null,
    refetchInterval: 15000,
  });

  const send = useMutation({
    mutationFn: () => api.post(`/client/projects/${activeId}/messages`, { body: draft }),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey: ["client-messages", activeId] });
      qc.invalidateQueries({ queryKey: ["client-dashboard"] });
    },
    onError: (e) => toast("error", "Could not send", (e as Error).message),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length]);

  if (projects.isLoading) return <TableSkeleton rows={5} cols={2} />;
  if (projects.isError) return <ErrorState message={(projects.error as Error)?.message} retry={projects.refetch} />;
  if (projectList.length === 0) {
    return <EmptyState title="No projects yet" description="Messages open once your request becomes a project." />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Messages</h1>
          <p className="mt-1 text-sm text-fg-muted">Talk to the delivery team per project.</p>
        </div>
        <NativeSelect aria-label="Select project" className="w-56" value={activeId ?? ""}
          onChange={(e) => setParams({ project: e.target.value })}>
          {projectList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </NativeSelect>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Conversation</CardTitle>
          <CardDescription>Internal staff notes are never visible to your organization.</CardDescription>
        </CardHeader>
        <CardContent>
          {messages.isLoading ? (
            <TableSkeleton rows={3} cols={1} />
          ) : messages.isError ? (
            <ErrorState message={(messages.error as Error)?.message} retry={messages.refetch} />
          ) : (messages.data ?? []).length === 0 ? (
            <EmptyState title="No messages yet"
              description={canWrite ? "Send the first message — the team is notified instantly." : "The team has not written yet."} />
          ) : (
            <div className="max-h-[55vh] space-y-3 overflow-y-auto pr-1">
              {(messages.data ?? []).map((m) => (
                <div key={m.id} className={`flex ${m.sender_side === "client" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                    m.sender_side === "client"
                      ? "bg-teal/15 text-fg"
                      : "border border-line bg-surface-raised text-fg"
                  }`}>
                    <div className="mb-0.5 flex items-center gap-2 text-xs text-fg-muted">
                      <span className="font-medium">{m.sender_name}</span>
                      <Badge variant={m.sender_side === "client" ? "info" : "success"}>{m.sender_side}</Badge>
                      <span className="ml-auto">{fmtDateTime(m.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-wrap">{m.body}</p>
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          )}

          {canWrite && activeId != null && (
            <div className="mt-4 border-t border-line pt-3">
              <Textarea rows={2} placeholder="Write a message to the project team…"
                value={draft} onChange={(e) => setDraft(e.target.value)} />
              <div className="mt-2 flex justify-end">
                <Button onClick={() => send.mutate()} disabled={!draft.trim() || send.isPending}>
                  <Send className="h-4 w-4" /> {send.isPending ? "Sending…" : "Send"}
                </Button>
              </div>
            </div>
          )}
          {!canWrite && (
            <p className="mt-3 text-xs text-fg-muted">Your role is read-only; ask a project manager or owner to reply.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
