// Worker management: create users, change roles, suspend accounts, project membership.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus, ShieldOff, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { v2queries, useInvalidateAll } from "@/api/v2hooks";
import { queries as v1queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ROLE_LABELS, ROLE_OPTIONS, isPlatformAdmin, type Role } from "@/lib/roles";
import { fmtDateTime } from "@/lib/utils";
import type { ProjectDetail } from "@/lib/types";

export default function WorkersPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const invalidate = useInvalidateAll();
  const [search, setSearch] = useState("");

  const users = useQuery(v2queries.users());
  const projects = useQuery(v1queries.projects());
  const projectsList = (projects.data ?? []) as unknown as ProjectDetail[];

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", password: "", role: "tester" as Role });
  const [roleFor, setRoleFor] = useState<{ id: number; name: string; role: string } | null>(null);
  const [newRole, setNewRole] = useState<Role>("tester");
  const [suspendFor, setSuspendFor] = useState<{ id: number; name: string; active: boolean } | null>(null);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignForm, setAssignForm] = useState({ email: "", project_id: "", role: "tester" });

  const canManage = isPlatformAdmin(user?.role ?? "");

  const createUser = useMutation({
    mutationFn: () => api.post("/auth/users", form),
    onSuccess: () => { invalidate(); setCreateOpen(false); toast("success", "Account created", form.email); },
    onError: (e) => toast("error", "Could not create account", (e as Error).message),
  });

  const changeRole = useMutation({
    mutationFn: () => api.put(`/auth/users/${roleFor!.id}/role`, { role: newRole }),
    onSuccess: () => { invalidate(); setRoleFor(null); toast("success", "Role updated"); },
    onError: (e) => { setRoleFor(null); toast("error", "Role change failed", (e as Error).message); },
  });

  const changeStatus = useMutation({
    mutationFn: () => api.put(`/auth/users/${suspendFor!.id}/status`, { is_active: !suspendFor!.active }),
    onSuccess: () => { invalidate(); setSuspendFor(null); toast("success", suspendFor!.active ? "Account suspended" : "Account reactivated"); },
    onError: (e) => { setSuspendFor(null); toast("error", "Status change failed", (e as Error).message); },
  });

  const assignMember = useMutation({
    mutationFn: () => api.post(`/projects/${assignForm.project_id}/members`, {
      email: assignForm.email, role: assignForm.role,
    }),
    onSuccess: () => { invalidate(); setAssignOpen(false); toast("success", "User assigned to project"); },
    onError: (e) => toast("error", "Assignment failed", (e as Error).message),
  });

  const filtered = (users.data ?? []).filter(
    (u) => !search || u.name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Workers &amp; reviewers</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Accounts, platform roles, suspensions and project assignments. Every change is audited.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setAssignOpen(true)}>Assign to project</Button>
          {canManage && (
            <Button onClick={() => setCreateOpen(true)}><UserPlus className="h-4 w-4" /> Create account</Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Accounts</CardTitle>
            <CardDescription>{users.data?.length ?? 0} registered users.</CardDescription>
          </div>
          <Input aria-label="Search users" placeholder="Search name or email…" className="h-8 w-56 text-xs"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </CardHeader>
        <CardContent>
          {users.isLoading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : users.isError ? (
            <ErrorState message={(users.error as Error)?.message} retry={users.refetch} />
          ) : filtered.length === 0 ? (
            <EmptyState title="No users match" />
          ) : (
            <Table>
              <THead>
                <TR><TH>User</TH><TH>Platform role</TH><TH>Status</TH><TH>Created</TH>{canManage && <TH />}</TR>
              </THead>
              <TBody>
                {filtered.map((u) => (
                  <TR key={u.id}>
                    <TD>
                      <div className="text-sm font-medium text-fg">{u.name}</div>
                      <div className="text-xs text-fg-muted">{u.email}</div>
                    </TD>
                    <TD>
                      <Badge variant={u.role.includes("admin") ? "default" : u.role === "tester" ? "info" : "neutral"}>
                        {ROLE_LABELS[u.role as Role] ?? u.role}
                      </Badge>
                    </TD>
                    <TD>
                      {u.is_active
                        ? <Badge variant="success">active</Badge>
                        : <Badge variant="danger">suspended</Badge>}
                    </TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime((u as unknown as { created_at: string }).created_at)}</TD>
                    {canManage && (
                      <TD className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => { setRoleFor({ id: u.id, name: u.name, role: u.role }); setNewRole(u.role as Role); }}>
                            Change role
                          </Button>
                          <Button variant="ghost" size="sm"
                            className={u.is_active ? "text-danger hover:text-danger" : "text-ok hover:text-ok"}
                            onClick={() => setSuspendFor({ id: u.id, name: u.name, active: u.is_active ?? true })}
                            title={u.is_active ? "Suspend account" : "Reactivate account"}>
                            {u.is_active ? <ShieldOff className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                          </Button>
                        </div>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create account */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create account</DialogTitle>
            <DialogDescription>The user can sign in immediately with these credentials.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="w-email">Email</Label>
              <Input id="w-email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="w-name">Full name</Label>
              <Input id="w-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="w-pass">Temporary password (min. 8 chars)</Label>
              <Input id="w-pass" type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="w-role">Platform role</Label>
              <NativeSelect id="w-role" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))}>
                {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
              </NativeSelect>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => createUser.mutate()} disabled={!form.email || !form.name || form.password.length < 8 || createUser.isPending}>
              {createUser.isPending ? "Creating…" : "Create account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Change role */}
      <Dialog open={roleFor !== null} onOpenChange={(o) => !o && setRoleFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change role — {roleFor?.name}</DialogTitle>
            <DialogDescription>Current role: {roleFor ? ROLE_LABELS[roleFor.role as Role] ?? roleFor.role : ""}. Takes effect immediately.</DialogDescription>
          </DialogHeader>
          <NativeSelect aria-label="New role" value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}>
            {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </NativeSelect>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleFor(null)}>Cancel</Button>
            <Button onClick={() => changeRole.mutate()} disabled={changeRole.isPending}>Confirm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={suspendFor !== null}
        onOpenChange={(o) => !o && setSuspendFor(null)}
        title={suspendFor?.active ? `Suspend ${suspendFor?.name}?` : `Reactivate ${suspendFor?.name}?`}
        description={suspendFor?.active
          ? "The account cannot sign in and existing tokens stop working immediately."
          : "The account will be able to sign in again."}
        confirmLabel={suspendFor?.active ? "Suspend" : "Reactivate"}
        destructive={suspendFor?.active ?? false}
        busy={changeStatus.isPending}
        onConfirm={() => changeStatus.mutate()}
      />

      {/* Assign to project */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign user to project</DialogTitle>
            <DialogDescription>Membership controls which projects a user can access. Role must match their platform role.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="a-email">User email</Label>
              <Input id="a-email" value={assignForm.email} onChange={(e) => setAssignForm((f) => ({ ...f, email: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="a-project">Project</Label>
              <NativeSelect id="a-project" value={assignForm.project_id}
                onChange={(e) => setAssignForm((f) => ({ ...f, project_id: e.target.value, role: e.target.value ? (projectsList.find((x) => x.id === Number(e.target.value))?.is_admin ? "admin" : f.role) : f.role }))}>
                <option value="">— Select —</option>
                {projectsList.filter((p) => p.is_admin).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="a-role">Membership role</Label>
              <NativeSelect id="a-role" value={assignForm.role} onChange={(e) => setAssignForm((f) => ({ ...f, role: e.target.value }))}>
                <option value="tester">tester</option>
                <option value="reviewer">reviewer</option>
                <option value="admin">admin</option>
              </NativeSelect>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>Cancel</Button>
            <Button onClick={() => assignMember.mutate()} disabled={!assignForm.email || !assignForm.project_id || assignMember.isPending}>
              {assignMember.isPending ? "Assigning…" : "Assign"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
