// Staff-side client engagement for one project: reply to the client thread
// (with internal notes) and publish approved-result deliverables.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Lock, PackagePlus, Send } from "lucide-react";
import { api } from "@/lib/api";
import { adminRequestQueries, type ClientDeliverable, type ClientMessage } from "@/api/clientHooks";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

export default function ProjectClientPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const toast = useToast();
  const { user } = useAuth();
  const [draft, setDraft] = useState("");
  const [internalNote, setInternalNote] = useState(false);
  const [pubLabel, setPubLabel] = useState("");
  const [pubFormat, setPubFormat] = useState("json");
  const [pubDescription, setPubDescription] = useState("");

  const project = useQuery({
    queryKey: ["v2-project", projectId],
    queryFn: () => api.get<{ id: number; name: string; organization_name: string | null; organization_id: number | null; is_admin: boolean }>(`/projects/${projectId}`),
  });
  const messages = useQuery(adminRequestQueries.messages(projectId));
  const deliverables = useQuery(adminRequestQueries.deliverables(projectId));

  const isSuperAdmin = user?.role === "super_admin";
  const canEngage = isSuperAdmin || (project.data?.is_admin ?? false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin-project-messages", projectId] });
    qc.invalidateQueries({ queryKey: ["admin-project-deliverables", projectId] });
  };

  const send = useMutation({
    mutationFn: () => api.post(`/admin/projects/${projectId}/messages`,
      { body: draft, is_internal: internalNote }),
    onSuccess: () => {
      setDraft(""); setInternalNote(false); invalidate();
      toast("success", internalNote ? "Internal note added" : "Reply sent to client");
    },
    onError: (e) => toast("error", "Could not send", (e as Error).message),
  });

  const publish = useMutation({
    mutationFn: () => api.post(`/admin/projects/${projectId}/deliverables`, {
      label: pubLabel || undefined, format: pubFormat, description: pubDescription || undefined,
    }),
    onSuccess: () => {
      setPubLabel(""); setPubDescription(""); invalidate();
      toast("success", "Deliverable published", "The client organization has been notified.");
    },
    onError: (e) => toast("error", "Publish failed", (e as Error).message),
  });

  if (project.isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (project.isError) return <ErrorState message={(project.error as Error)?.message} retry={project.refetch} />;

  const p = project.data!;
  const msgList: ClientMessage[] = messages.data ?? [];
  const delList: ClientDeliverable[] = deliverables.data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Link to={`/projects/${projectId}`} className="text-fg-muted hover:text-fg"><ArrowLeft className="h-4 w-4" /></Link>
            <h1 className="text-xl font-bold text-fg">Client engagement — {p.name}</h1>
          </div>
          <p className="mt-1 text-sm text-fg-muted">
            {p.organization_name ? `Organization: ${p.organization_name}` : "This project has no client organization (internal project)."}
          </p>
        </div>
      </div>

      {!p.organization_id ? (
        <EmptyState title="No client organization"
          description="Only projects linked to a client organization have a client thread and deliverables." />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Thread */}
          <Card>
            <CardHeader>
              <CardTitle>Client thread</CardTitle>
              <CardDescription>Replies notify the organization. Internal notes stay staff-only.</CardDescription>
            </CardHeader>
            <CardContent>
              {messages.isLoading ? (
                <TableSkeleton rows={3} cols={1} />
              ) : messages.isError ? (
                <ErrorState message={(messages.error as Error)?.message} retry={messages.refetch} />
              ) : msgList.length === 0 ? (
                <EmptyState title="No messages yet" />
              ) : (
                <div className="max-h-[45vh] space-y-2.5 overflow-y-auto pr-1">
                  {msgList.map((m) => (
                    <div key={m.id} className={`rounded-lg border px-3 py-2 text-sm ${
                      m.is_internal ? "border-amber-500/40 bg-amber-500/10" : "border-line bg-surface-raised"
                    }`}>
                      <div className="mb-0.5 flex items-center gap-2 text-xs text-fg-muted">
                        <span className="font-medium">{m.sender_name}</span>
                        <Badge variant={m.sender_side === "client" ? "info" : "success"}>{m.sender_side}</Badge>
                        {m.is_internal && <Badge variant="warning"><Lock className="mr-1 inline h-3 w-3" />internal</Badge>}
                        <span className="ml-auto">{fmtDateTime(m.created_at)}</span>
                      </div>
                      <p className="whitespace-pre-wrap text-fg">{m.body}</p>
                    </div>
                  ))}
                </div>
              )}
              {canEngage && (
                <div className="mt-4 border-t border-line pt-3">
                  <textarea
                    className="w-full rounded-md border border-line bg-surface p-2 text-sm text-fg placeholder:text-fg-muted"
                    rows={2}
                    placeholder={internalNote ? "Internal note (never shown to the client)…" : "Reply to the client…"}
                    value={draft} onChange={(e) => setDraft(e.target.value)}
                  />
                  <div className="mt-2 flex items-center justify-between">
                    <label className="flex items-center gap-2 text-xs text-fg-muted">
                      <input type="checkbox" checked={internalNote}
                        onChange={(e) => setInternalNote(e.target.checked)} />
                      Internal note
                    </label>
                    <Button size="sm" onClick={() => send.mutate()} disabled={!draft.trim() || send.isPending}>
                      <Send className="h-3.5 w-3.5" /> {send.isPending ? "Sending…" : "Send"}
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Deliverables */}
          <Card>
            <CardHeader>
              <CardTitle>Deliverables</CardTitle>
              <CardDescription>Publish the approved results — clients download and every download is audited.</CardDescription>
            </CardHeader>
            <CardContent>
              {deliverables.isLoading ? (
                <TableSkeleton rows={3} cols={3} />
              ) : deliverables.isError ? (
                <ErrorState message={(deliverables.error as Error)?.message} retry={deliverables.refetch} />
              ) : delList.length === 0 ? (
                <EmptyState title="Nothing published yet"
                  description="Publish a package of approved results below." />
              ) : (
                <Table>
                  <THead>
                    <TR><TH>Label</TH><TH>Format</TH><TH>Records</TH><TH>Published</TH><TH>Downloads</TH></TR>
                  </THead>
                  <TBody>
                    {delList.map((d) => (
                      <TR key={d.id}>
                        <TD className="max-w-[160px] truncate text-sm text-fg">{d.label}</TD>
                        <TD><Badge variant="info">{d.export_format.toUpperCase()}</Badge></TD>
                        <TD className="text-xs text-fg-muted">{d.record_count}</TD>
                        <TD className="text-xs text-fg-muted">{fmtDateTime(d.published_at)}</TD>
                        <TD className="text-xs text-fg-muted">{d.download_count}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
              {canEngage && (
                <div className="mt-4 space-y-2 border-t border-line pt-3">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="pub-label">Label</Label>
                      <Input id="pub-label" value={pubLabel} placeholder="Batch 1 — approved results"
                        onChange={(e) => setPubLabel(e.target.value)} />
                    </div>
                    <div>
                      <Label htmlFor="pub-format">Format</Label>
                      <NativeSelect id="pub-format" value={pubFormat} onChange={(e) => setPubFormat(e.target.value)}>
                        <option value="json">JSON</option>
                        <option value="csv">CSV</option>
                        <option value="jsonl">JSONL</option>
                      </NativeSelect>
                    </div>
                  </div>
                  <Input value={pubDescription} placeholder="Description (optional)"
                    onChange={(e) => setPubDescription(e.target.value)} />
                  <Button size="sm" onClick={() => publish.mutate()} disabled={publish.isPending}>
                    <PackagePlus className="h-3.5 w-3.5" />
                    {publish.isPending ? "Publishing…" : "Publish approved results"}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
