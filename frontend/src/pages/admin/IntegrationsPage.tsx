// Admin integrations: API credentials + webhook endpoints (with delivery history).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, RefreshCw, Trash2, Webhook } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, ConfirmDialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

const SCOPES = [
  "projects:read", "datasets:read", "datasets:write", "tasks:read", "tasks:write",
  "submissions:read", "results:read",
];
const EVENTS = [
  "project.created", "project.updated", "dataset.imported", "task.created", "task.assigned",
  "task.submitted", "review.completed", "submission.approved", "submission.rejected",
  "adjudication.completed", "project.completed",
];

interface ApiKey {
  id: number; name: string; key_prefix: string; scopes: string[]; is_revoked: boolean;
  expires_at: string | null; last_used_at: string | null; created_at: string | null;
}
interface WebhookEp {
  id: number; url: string; events: string[]; is_active: boolean; created_at: string | null;
}
interface Delivery {
  id: number; event_type: string; status: string; attempts: number;
  response_code: number | null; error: string | null; created_at: string | null;
}

export default function IntegrationsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"keys" | "webhooks">("keys");

  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api.get<ApiKey[]>("/admin/api-keys") });
  const webhooks = useQuery({ queryKey: ["webhooks"], queryFn: () => api.get<WebhookEp[]>("/admin/webhooks") });
  const [deliveriesFor, setDeliveriesFor] = useState<WebhookEp | null>(null);
  const deliveries = useQuery({
    queryKey: ["webhook-deliveries", deliveriesFor?.id],
    queryFn: () => api.get<{ total: number; items: Delivery[] }>(`/admin/webhooks/${deliveriesFor!.id}/deliveries`),
    enabled: !!deliveriesFor,
  });

  const [createKeyOpen, setCreateKeyOpen] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [keyScopes, setKeyScopes] = useState<string[]>(["projects:read"]);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [revokeFor, setRevokeFor] = useState<ApiKey | null>(null);

  const [createWebhookOpen, setCreateWebhookOpen] = useState(false);
  const [whUrl, setWhUrl] = useState("");
  const [whEvents, setWhEvents] = useState<string[]>(["project.created"]);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [webhookForDelete, setWebhookForDelete] = useState<WebhookEp | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["api-keys"] });
    qc.invalidateQueries({ queryKey: ["webhooks"] });
    qc.invalidateQueries({ queryKey: ["webhook-deliveries"] });
  };

  const createKey = useMutation({
    mutationFn: () => api.post<{ key: string }>("/admin/api-keys", { name: keyName, scopes: keyScopes }),
    onSuccess: (d) => {
      invalidate(); setCreateKeyOpen(false); setKeyName("");
      setCreatedKey(d.key);
      toast("success", "API key created", "Copy it now — it is shown only once.");
    },
    onError: (e) => toast("error", "Could not create key", (e as Error).message),
  });
  const rotateKey = useMutation({
    mutationFn: (k: ApiKey) => api.post<{ key: string }>(`/admin/api-keys/${k.id}/rotate`),
    onSuccess: (d) => { invalidate(); setCreatedKey(d.key); toast("success", "Key rotated", "The old key is revoked."); },
    onError: (e) => toast("error", "Rotation failed", (e as Error).message),
  });
  const revokeKey = useMutation({
    mutationFn: () => api.del(`/admin/api-keys/${revokeFor!.id}`),
    onSuccess: () => { invalidate(); setRevokeFor(null); toast("success", "Key revoked"); },
    onError: (e) => { setRevokeFor(null); toast("error", "Revoke failed", (e as Error).message); },
  });

  const createWebhook = useMutation({
    mutationFn: () => api.post<{ secret: string }>("/admin/webhooks", { url: whUrl, events: whEvents }),
    onSuccess: (d) => {
      invalidate(); setCreateWebhookOpen(false); setWhUrl("");
      setCreatedSecret(d.secret);
      toast("success", "Webhook endpoint created", "Store the signing secret now.");
    },
    onError: (e) => toast("error", "Could not create webhook", (e as Error).message),
  });
  const toggleWebhook = useMutation({
    mutationFn: (w: WebhookEp) => api.put(`/admin/webhooks/${w.id}`, { is_active: !w.is_active }),
    onSuccess: () => { invalidate(); toast("success", "Webhook updated"); },
    onError: (e) => toast("error", "Update failed", (e as Error).message),
  });
  const testWebhook = useMutation({
    mutationFn: (w: WebhookEp) => api.post(`/admin/webhooks/${w.id}/test`),
    onSuccess: () => toast("success", "Test delivery queued", "Check the delivery history in a few seconds."),
    onError: (e) => toast("error", "Test failed", (e as Error).message),
  });
  const replayDelivery = useMutation({
    mutationFn: (d: Delivery) => api.post(`/admin/webhooks/deliveries/${d.id}/replay`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["webhook-deliveries"] }); toast("success", "Delivery replayed"); },
    onError: (e) => toast("error", "Replay failed", (e as Error).message),
  });
  const deleteWebhook = useMutation({
    mutationFn: () => api.put(`/admin/webhooks/${webhookForDelete!.id}`, { is_active: false }),
    onSuccess: () => { invalidate(); setWebhookForDelete(null); toast("success", "Webhook disabled"); },
    onError: (e) => { setWebhookForDelete(null); toast("error", "Failed", (e as Error).message); },
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">API integrations</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Scoped API keys for external applications and signed webhook deliveries.
        </p>
      </div>

      <div className="flex gap-2">
        <Button variant={tab === "keys" ? "default" : "secondary"} size="sm" onClick={() => setTab("keys")}>
          <KeyRound className="h-4 w-4" /> API keys
        </Button>
        <Button variant={tab === "webhooks" ? "default" : "secondary"} size="sm" onClick={() => setTab("webhooks")}>
          <Webhook className="h-4 w-4" /> Webhooks
        </Button>
      </div>

      {tab === "keys" && (
        <Card>
          <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>Credentials ({(keys.data ?? []).length})</CardTitle>
            <Button size="sm" onClick={() => setCreateKeyOpen(true)}><Plus className="h-4 w-4" /> New key</Button>
          </CardHeader>
          <CardContent>
            {keys.isLoading ? <TableSkeleton rows={3} cols={5} />
              : keys.isError ? <ErrorState message={(keys.error as Error)?.message} retry={keys.refetch} />
                : (keys.data ?? []).length === 0 ? (
                  <EmptyState title="No API keys yet" description="Create a scoped key for an external application." />
                ) : (
                  <Table>
                    <THead><TR><TH>Name</TH><TH>Key</TH><TH>Scopes</TH><TH>Last used</TH><TH>Status</TH><TH /></TR></THead>
                    <TBody>
                      {(keys.data ?? []).map((k) => (
                        <TR key={k.id}>
                          <TD className="text-sm font-medium text-fg">{k.name}</TD>
                          <TD className="font-mono text-xs text-fg-muted">{k.key_prefix}…</TD>
                          <TD className="max-w-[220px]">
                            <div className="flex flex-wrap gap-1">
                              {k.scopes.map((s) => <Badge key={s} variant="info">{s}</Badge>)}
                            </div>
                          </TD>
                          <TD className="text-xs text-fg-muted">{fmtDateTime(k.last_used_at) || "never"}</TD>
                          <TD>{k.is_revoked ? <Badge variant="danger">revoked</Badge> : <Badge variant="success">active</Badge>}</TD>
                          <TD className="text-right">
                            {!k.is_revoked && (
                              <div className="flex justify-end gap-1">
                                <Button variant="ghost" size="sm" onClick={() => rotateKey.mutate(k)}>
                                  <RefreshCw className="h-3.5 w-3.5" /> Rotate
                                </Button>
                                <Button variant="ghost" size="sm" className="text-danger hover:text-danger"
                                  onClick={() => setRevokeFor(k)}>
                                  <Trash2 className="h-3.5 w-3.5" /> Revoke
                                </Button>
                              </div>
                            )}
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
          </CardContent>
        </Card>
      )}

      {tab === "webhooks" && (
        <Card>
          <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>Endpoints ({(webhooks.data ?? []).length})</CardTitle>
            <Button size="sm" onClick={() => setCreateWebhookOpen(true)}><Plus className="h-4 w-4" /> New endpoint</Button>
          </CardHeader>
          <CardContent>
            {webhooks.isLoading ? <TableSkeleton rows={3} cols={4} />
              : webhooks.isError ? <ErrorState message={(webhooks.error as Error)?.message} retry={webhooks.refetch} />
                : (webhooks.data ?? []).length === 0 ? (
                  <EmptyState title="No webhooks configured" description="Register a public HTTPS endpoint to receive events." />
                ) : (
                  <Table>
                    <THead><TR><TH>URL</TH><TH>Events</TH><TH>Status</TH><TH /></TR></THead>
                    <TBody>
                      {(webhooks.data ?? []).map((w) => (
                        <TR key={w.id}>
                          <TD className="max-w-[280px] truncate font-mono text-xs text-fg">{w.url}</TD>
                          <TD className="max-w-[240px]">
                            <div className="flex flex-wrap gap-1">
                              {w.events.slice(0, 4).map((e) => <Badge key={e} variant="neutral">{e}</Badge>)}
                              {w.events.length > 4 && <Badge variant="neutral">+{w.events.length - 4}</Badge>}
                            </div>
                          </TD>
                          <TD>{w.is_active ? <Badge variant="success">active</Badge> : <Badge variant="neutral">disabled</Badge>}</TD>
                          <TD className="text-right">
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" size="sm" onClick={() => testWebhook.mutate(w)}>Test</Button>
                              <Button variant="ghost" size="sm" onClick={() => setDeliveriesFor(w)}>History</Button>
                              <Button variant="ghost" size="sm" onClick={() => toggleWebhook.mutate(w)}>
                                {w.is_active ? "Disable" : "Enable"}
                              </Button>
                            </div>
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
          </CardContent>
        </Card>
      )}

      {/* Create key dialog */}
      <Dialog open={createKeyOpen} onOpenChange={setCreateKeyOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New API credential</DialogTitle>
            <DialogDescription>Scope the key narrowly — it never inherits admin permissions.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="k-name">Name</Label>
              <Input id="k-name" value={keyName} onChange={(e) => setKeyName(e.target.value)}
                placeholder="Client portal integration" /></div>
            <div>
              <Label>Scopes</Label>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {SCOPES.map((s) => (
                  <button key={s} type="button"
                    onClick={() => setKeyScopes((sc) => sc.includes(s) ? sc.filter((x) => x !== s) : [...sc, s])}
                    className={`rounded-full border px-2.5 py-1 text-xs ${keyScopes.includes(s) ? "border-teal-500 bg-teal-500/15 text-teal" : "border-line text-fg-muted hover:text-fg"}`}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateKeyOpen(false)}>Cancel</Button>
            <Button onClick={() => createKey.mutate()} disabled={!keyName || !keyScopes.length || createKey.isPending}>
              {createKey.isPending ? "Creating…" : "Create key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Secret-shown-once dialog */}
      <Dialog open={createdKey !== null || createdSecret !== null} onOpenChange={(o) => { if (!o) { setCreatedKey(null); setCreatedSecret(null); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{createdKey ? "API key created" : "Webhook signing secret"}</DialogTitle>
            <DialogDescription>Copy it now — this value is never shown again.</DialogDescription>
          </DialogHeader>
          <code className="block break-all rounded-md border border-teal-500/40 bg-teal-500/10 p-3 text-xs text-fg">
            {createdKey ?? createdSecret}
          </code>
          <DialogFooter>
            <Button onClick={() => { navigator.clipboard?.writeText(createdKey ?? createdSecret ?? ""); toast("success", "Copied"); }}>
              Copy
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create webhook dialog */}
      <Dialog open={createWebhookOpen} onOpenChange={setCreateWebhookOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New webhook endpoint</DialogTitle>
            <DialogDescription>Public HTTPS only — internal network targets are blocked (SSRF protection).</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="w-url">Endpoint URL</Label>
              <Input id="w-url" value={whUrl} onChange={(e) => setWhUrl(e.target.value)}
                placeholder="https://your-app.example.com/hooks/evalforge" /></div>
            <div>
              <Label>Events</Label>
              <div className="mt-1 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                {EVENTS.map((e) => (
                  <button key={e} type="button"
                    onClick={() => setWhEvents((ev) => ev.includes(e) ? ev.filter((x) => x !== e) : [...ev, e])}
                    className={`rounded-full border px-2.5 py-1 text-xs ${whEvents.includes(e) ? "border-teal-500 bg-teal-500/15 text-teal" : "border-line text-fg-muted hover:text-fg"}`}>
                    {e}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateWebhookOpen(false)}>Cancel</Button>
            <Button onClick={() => createWebhook.mutate()} disabled={!whUrl || !whEvents.length || createWebhook.isPending}>
              {createWebhook.isPending ? "Creating…" : "Create endpoint"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delivery history */}
      <Dialog open={deliveriesFor !== null} onOpenChange={(o) => !o && setDeliveriesFor(null)}>
        <DialogContent className="max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Delivery history — {deliveriesFor?.url}</DialogTitle>
            <DialogDescription>{deliveries.data?.total ?? 0} deliveries. Failed deliveries can be replayed.</DialogDescription>
          </DialogHeader>
          {deliveries.isLoading ? <TableSkeleton rows={4} cols={4} /> : (
            <Table>
              <THead><TR><TH>Event</TH><TH>Status</TH><TH>Attempts</TH><TH>Response</TH><TH>When</TH><TH /></TR></THead>
              <TBody>
                {(deliveries.data?.items ?? []).map((d) => (
                  <TR key={d.id}>
                    <TD className="text-xs text-fg">{d.event_type}</TD>
                    <TD><Badge variant={d.status === "delivered" ? "success" : d.status === "pending" ? "warning" : "danger"}>{d.status}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{d.attempts}</TD>
                    <TD className="text-xs text-fg-muted">{d.response_code ?? d.error?.slice(0, 30) ?? "—"}</TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(d.created_at)}</TD>
                    <TD className="text-right">
                      {d.status !== "delivered" && (
                        <Button variant="ghost" size="sm" onClick={() => replayDelivery.mutate(d)}>Replay</Button>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={revokeFor !== null}
        onOpenChange={(o) => !o && setRevokeFor(null)}
        title={`Revoke API key “${revokeFor?.name}”?`}
        description="External applications using this key stop working immediately."
        confirmLabel="Revoke" destructive busy={revokeKey.isPending}
        onConfirm={() => revokeKey.mutate()}
      />
      <ConfirmDialog
        open={webhookForDelete !== null}
        onOpenChange={(o) => !o && setWebhookForDelete(null)}
        title="Disable this webhook endpoint?"
        description="Pending deliveries are disabled; history is preserved."
        confirmLabel="Disable" destructive busy={deleteWebhook.isPending}
        onConfirm={() => deleteWebhook.mutate()}
      />
    </div>
  );
}
