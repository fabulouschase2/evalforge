// Organization (tenant) management — admin creates orgs; client owners manage members.
// All actions hit the real /api/organizations endpoints (server enforces roles).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Copy, Mail, UserPlus, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, ConfirmDialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { CLIENT_ROLE_OPTIONS, ROLE_LABELS, isClientRole, isPlatformAdmin, type Role } from "@/lib/roles";
import { fmtDateTime } from "@/lib/utils";

interface OrgMember { id: number; user_id: number; name: string | null; email: string | null; role: string; created_at: string | null }
interface OrgInvitation { id: number; email: string; role: string; status: string; created_at: string | null }
interface Org {
  id: number; name: string; description: string | null; slug: string | null;
  status: string; contact_email: string | null; member_count?: number;
  my_role?: string | null; members?: OrgMember[]; created_at: string | null;
}

export default function OrganizationsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const isAdmin = isPlatformAdmin(user?.role ?? "");
  const isClient = isClientRole(user?.role ?? "");
  const canManageOrgs = isAdmin || user?.role === "client_owner";

  const orgs = useQuery({
    queryKey: ["organizations-page"],
    queryFn: () => api.get<Org[]>("/organizations"),
  });

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ name: "", description: "", contact_email: "", owner_email: "" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [memberForm, setMemberForm] = useState({ email: "", role: "client_viewer" as Role });
  const [inviteForm, setInviteForm] = useState({ email: "", role: "client_viewer" as Role });
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [removeMember, setRemoveMember] = useState<OrgMember | null>(null);

  const orgList = orgs.data ?? [];
  const selected = orgList.find((o) => o.id === selectedId) ?? orgList[0] ?? null;

  const members = useQuery({
    queryKey: ["org-members", selected?.id],
    queryFn: () => api.get<OrgMember[]>(`/organizations/${selected!.id}/members`),
    enabled: selected != null,
  });
  const invitations = useQuery({
    queryKey: ["org-invitations", selected?.id],
    queryFn: () => api.get<OrgInvitation[]>(`/organizations/${selected!.id}/invitations`),
    enabled: selected != null && canManageOrgs,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["organizations-page"] });
    qc.invalidateQueries({ queryKey: ["org-members"] });
    qc.invalidateQueries({ queryKey: ["org-invitations"] });
    qc.invalidateQueries({ queryKey: ["organizations"] });
  };

  const createOrg = useMutation({
    mutationFn: () => api.post("/organizations", {
      name: createForm.name,
      description: createForm.description || null,
      contact_email: createForm.contact_email || null,
      owner_email: createForm.owner_email || null,
    }),
    onSuccess: () => { invalidate(); setCreateOpen(false); setCreateForm({ name: "", description: "", contact_email: "", owner_email: "" }); toast("success", "Organization created"); },
    onError: (e) => toast("error", "Could not create organization", (e as Error).message),
  });

  const addMember = useMutation({
    mutationFn: () => api.post(`/organizations/${selected!.id}/members`, memberForm),
    onSuccess: () => { invalidate(); setMemberForm({ email: "", role: "client_viewer" }); toast("success", "Member added"); },
    onError: (e) => toast("error", "Could not add member", (e as Error).message),
  });

  const createInvite = useMutation({
    mutationFn: () => api.post<{ token: string }>(`/organizations/${selected!.id}/invitations`, inviteForm),
    onSuccess: (data) => {
      invalidate();
      setInviteToken(data.token);
      setInviteForm({ email: "", role: "client_viewer" });
      toast("success", "Invitation created", "Copy the token now — it is shown only once.");
    },
    onError: (e) => toast("error", "Could not create invitation", (e as Error).message),
  });

  const removeMemberMut = useMutation({
    mutationFn: () => api.del(`/organizations/${selected!.id}/members/${removeMember!.id}`),
    onSuccess: () => { invalidate(); setRemoveMember(null); toast("success", "Member removed"); },
    onError: (e) => { setRemoveMember(null); toast("error", "Could not remove member", (e as Error).message); },
  });

  const updateOrgStatus = useMutation({
    mutationFn: (status: string) => api.put(`/organizations/${selected!.id}`, { status }),
    onSuccess: () => { invalidate(); toast("success", "Organization updated"); },
    onError: (e) => toast("error", "Update failed", (e as Error).message),
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">
            {isClient ? "My organization" : "Client organizations"}
          </h1>
          <p className="mt-1 text-sm text-fg-muted">
            {isClient
              ? "Your organization membership and team."
              : "Tenants that own projects. Client users only ever see their own organization."}
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setCreateOpen(true)}><Building2 className="h-4 w-4" /> New organization</Button>
        )}
      </div>

      {orgs.isLoading ? (
        <Card><CardContent><TableSkeleton rows={4} cols={4} /></CardContent></Card>
      ) : orgs.isError ? (
        <ErrorState message={(orgs.error as Error)?.message} retry={orgs.refetch} />
      ) : orgList.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title={isAdmin ? "No organizations yet" : "You are not part of an organization"}
              description={isAdmin
                ? "Create the first client organization to enable multi-tenant projects."
                : "Ask the platform administrator for an invitation."}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          {/* Org list */}
          <div className="space-y-2">
            {orgList.map((o) => (
              <button
                key={o.id}
                onClick={() => setSelectedId(o.id)}
                className={`w-full rounded-lg border p-3 text-left transition-colors ${
                  selected?.id === o.id
                    ? "border-teal-500/60 bg-teal-500/10"
                    : "border-line bg-surface hover:bg-surface-raised"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-fg">{o.name}</span>
                  <Badge variant={o.status === "active" ? "success" : "danger"}>{o.status}</Badge>
                </div>
                <div className="mt-1 text-xs text-fg-muted">
                  {o.slug ?? `#${o.id}`}
                  {typeof o.member_count === "number" ? ` · ${o.member_count} member${o.member_count === 1 ? "" : "s"}` : ""}
                  {o.my_role ? ` · you: ${ROLE_LABELS[o.my_role as Role] ?? o.my_role}` : ""}
                </div>
              </button>
            ))}
          </div>

          {/* Org detail */}
          {selected && (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2"><Users className="h-4 w-4" /> Members — {selected.name}</CardTitle>
                  <CardDescription>
                    Client roles: Owner manages everything, Project Manager submits work, Viewer is read-only.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {members.isLoading ? (
                    <TableSkeleton rows={3} cols={3} />
                  ) : members.isError ? (
                    <ErrorState message={(members.error as Error)?.message} retry={members.refetch} />
                  ) : (members.data ?? []).length === 0 ? (
                    <EmptyState title="No members yet" description="Add members or send invitations below." />
                  ) : (
                    <Table>
                      <THead>
                        <TR><TH>Member</TH><TH>Role</TH><TH>Added</TH>{canManageOrgs && <TH />}</TR>
                      </THead>
                      <TBody>
                        {(members.data ?? []).map((m) => (
                          <TR key={m.id}>
                            <TD>
                              <div className="text-sm font-medium text-fg">{m.name ?? "—"}</div>
                              <div className="text-xs text-fg-muted">{m.email ?? ""}</div>
                            </TD>
                            <TD><Badge variant="info">{ROLE_LABELS[m.role as Role] ?? m.role}</Badge></TD>
                            <TD className="text-xs text-fg-muted">{fmtDateTime(m.created_at)}</TD>
                            {canManageOrgs && (
                              <TD className="text-right">
                                <Button variant="ghost" size="sm" className="text-danger hover:text-danger"
                                  onClick={() => setRemoveMember(m)}>
                                  Remove
                                </Button>
                              </TD>
                            )}
                          </TR>
                        ))}
                      </TBody>
                    </Table>
                  )}
                  {canManageOrgs && (
                    <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4">
                      <div>
                        <Label htmlFor="om-email">Add existing user by email</Label>
                        <Input id="om-email" type="email" className="w-56" value={memberForm.email}
                          onChange={(e) => setMemberForm((f) => ({ ...f, email: e.target.value }))} />
                      </div>
                      <div>
                        <Label htmlFor="om-role">Role</Label>
                        <NativeSelect id="om-role" className="w-52" value={memberForm.role}
                          onChange={(e) => setMemberForm((f) => ({ ...f, role: e.target.value as Role }))}>
                          {CLIENT_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                        </NativeSelect>
                      </div>
                      <Button variant="secondary" onClick={() => addMember.mutate()}
                        disabled={!memberForm.email || addMember.isPending}>
                        <UserPlus className="h-4 w-4" /> Add member
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>

              {canManageOrgs && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2"><Mail className="h-4 w-4" /> Invitations</CardTitle>
                    <CardDescription>Invite someone who does not have an account yet. The token is shown once.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap items-end gap-2">
                      <div>
                        <Label htmlFor="oi-email">Email</Label>
                        <Input id="oi-email" type="email" className="w-56" value={inviteForm.email}
                          onChange={(e) => setInviteForm((f) => ({ ...f, email: e.target.value }))} />
                      </div>
                      <div>
                        <Label htmlFor="oi-role">Role</Label>
                        <NativeSelect id="oi-role" className="w-52" value={inviteForm.role}
                          onChange={(e) => setInviteForm((f) => ({ ...f, role: e.target.value as Role }))}>
                          {CLIENT_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                        </NativeSelect>
                      </div>
                      <Button variant="secondary" onClick={() => createInvite.mutate()}
                        disabled={!inviteForm.email || createInvite.isPending}>
                        Create invitation
                      </Button>
                    </div>
                    {inviteToken && (
                      <div className="mt-3 rounded-md border border-teal-500/40 bg-teal-500/10 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <code className="break-all text-xs text-fg">{inviteToken}</code>
                          <Button variant="ghost" size="sm"
                            onClick={() => { navigator.clipboard?.writeText(inviteToken); toast("success", "Token copied"); }}>
                            <Copy className="h-3.5 w-3.5" /> Copy
                          </Button>
                        </div>
                        <p className="mt-1 text-xs text-fg-muted">
                          Share this token with {inviteForm.email || "the invitee"} — they accept it after signing in.
                          It is stored hashed and cannot be retrieved again.
                        </p>
                      </div>
                    )}
                    {invitations.data && invitations.data.length > 0 && (
                      <Table>
                        <THead>
                          <TR><TH>Email</TH><TH>Role</TH><TH>Status</TH><TH>Created</TH></TR>
                        </THead>
                        <TBody>
                          {invitations.data.map((i) => (
                            <TR key={i.id}>
                              <TD className="text-sm text-fg">{i.email}</TD>
                              <TD><Badge variant="info">{ROLE_LABELS[i.role as Role] ?? i.role}</Badge></TD>
                              <TD><Badge variant={i.status === "pending" ? "warning" : i.status === "accepted" ? "success" : "neutral"}>{i.status}</Badge></TD>
                              <TD className="text-xs text-fg-muted">{fmtDateTime(i.created_at)}</TD>
                            </TR>
                          ))}
                        </TBody>
                      </Table>
                    )}
                  </CardContent>
                </Card>
              )}

              {isAdmin && (
                <Card>
                  <CardHeader>
                    <CardTitle>Organization status</CardTitle>
                    <CardDescription>Suspended organizations block all client access (server-enforced at sign-in surfaces).</CardDescription>
                  </CardHeader>
                  <CardContent className="flex gap-2">
                    <Button variant="secondary" size="sm" disabled={selected.status === "active"}
                      onClick={() => updateOrgStatus.mutate("active")}>Set active</Button>
                    <Button variant="secondary" size="sm" disabled={selected.status === "suspended"}
                      onClick={() => updateOrgStatus.mutate("suspended")}>Suspend</Button>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* Create org dialog (admins) */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New client organization</DialogTitle>
            <DialogDescription>Organizations are the tenant boundary — their users only see their own projects.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="o-name">Name</Label>
              <Input id="o-name" value={createForm.name} onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="o-desc">Description</Label>
              <Input id="o-desc" value={createForm.description} onChange={(e) => setCreateForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="o-contact">Contact email</Label>
              <Input id="o-contact" type="email" value={createForm.contact_email} onChange={(e) => setCreateForm((f) => ({ ...f, contact_email: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="o-owner">Owner (existing user email, optional)</Label>
              <Input id="o-owner" type="email" value={createForm.owner_email} onChange={(e) => setCreateForm((f) => ({ ...f, owner_email: e.target.value }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => createOrg.mutate()} disabled={!createForm.name || createOrg.isPending}>
              {createOrg.isPending ? "Creating…" : "Create organization"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removeMember !== null}
        onOpenChange={(o) => !o && setRemoveMember(null)}
        title={`Remove ${removeMember?.name ?? "member"} from ${selected?.name ?? ""}?`}
        description="They immediately lose access to this organization's projects and data."
        confirmLabel="Remove"
        destructive
        busy={removeMemberMut.isPending}
        onConfirm={() => removeMemberMut.mutate()}
      />
    </div>
  );
}
