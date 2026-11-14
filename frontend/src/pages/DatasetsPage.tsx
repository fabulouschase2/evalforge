import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Database } from "lucide-react";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/roles";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import type { Dataset } from "@/lib/types";

export default function DatasetsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const canEdit = isStaff(user?.role ?? "");

  const { data, isLoading, isError, error, refetch } = useQuery(queries.datasets());
  const { data: projects } = useQuery(queries.projects());

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [deleting, setDeleting] = useState<Dataset | null>(null);

  const create = useMutation({
    mutationFn: () => api.post<Dataset>("/datasets", {
      name, description: description || null,
      project_id: projectId ? Number(projectId) : null,
    }),
    onSuccess: (ds) => {
      qc.invalidateQueries();
      setOpen(false);
      setName("");
      setDescription("");
      toast("success", "Dataset created", `${ds.name} — now import records on the dataset page.`);
    },
    onError: (e) => toast("error", "Could not create dataset", (e as Error).message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/datasets/${id}`),
    onSuccess: () => {
      qc.invalidateQueries();
      setDeleting(null);
      toast("success", "Dataset deleted");
    },
    onError: (e) => {
      setDeleting(null);
      toast("error", "Cannot delete dataset", (e as Error).message);
    },
  });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">Datasets</h1>
          <p className="mt-1 text-sm text-fg-muted">
            CSV, JSON and JSONL evaluation records with versioning and duplicate detection.
          </p>
        </div>
        {canEdit && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New dataset</Button>}
      </div>

      {isLoading ? (
        <TableSkeleton rows={5} cols={5} />
      ) : isError ? (
        <ErrorState message={(error as Error)?.message} retry={refetch} />
      ) : (data as Dataset[]).length === 0 ? (
        <EmptyState
          icon={Database}
          title="No datasets yet"
          description="Create a dataset and import evaluation records (CSV / JSON / JSONL) with prompts, AI responses and optional reference answers."
          action={canEdit ? <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New dataset</Button> : undefined}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Format</TH>
                  <TH>Version</TH>
                  <TH>Source</TH>
                  <TH>Created</TH>
                  {canEdit && <TH />}
                </TR>
              </THead>
              <TBody>
                {(data as Dataset[]).map((ds) => (
                  <TR key={ds.id}>
                    <TD>
                      <Link to={`/datasets/${ds.id}`} className="font-medium text-teal hover:underline">
                        {ds.name}
                      </Link>
                      {ds.is_demo && <Badge variant="warning" className="ml-2">DEMO</Badge>}
                      {ds.description && <div className="mt-0.5 max-w-md truncate text-xs text-fg-muted">{ds.description}</div>}
                    </TD>
                    <TD><Badge variant="info">{ds.format.toUpperCase()}</Badge></TD>
                    <TD>v{ds.current_version}</TD>
                    <TD className="max-w-[180px] truncate text-fg-muted">{ds.source_filename ?? "—"}</TD>
                    <TD className="text-fg-muted">{fmtDateTime(ds.created_at)}</TD>
                    {canEdit && (
                      <TD className="text-right">
                        <Button
                          variant="ghost" size="sm" className="text-danger hover:text-danger"
                          onClick={() => setDeleting(ds)}
                          aria-label={`Delete ${ds.name}`}
                        >
                          Delete
                        </Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create dataset</DialogTitle>
            <DialogDescription>
              After creating the dataset you will import records on the dataset page (CSV, JSON or JSONL).
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="d-name">Name</Label>
              <Input id="d-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Support responses Q3" />
            </div>
            <div>
              <Label htmlFor="d-proj">Project (optional)</Label>
              <NativeSelect id="d-proj" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">— None —</option>
                {(projects ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="d-desc">Description (optional)</Label>
              <Textarea id="d-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create dataset"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete dataset "${deleting?.name}"?`}
        description="This permanently removes the dataset and its records. Datasets referenced by existing evaluation runs cannot be deleted (historical evaluations must remain reproducible)."
        confirmLabel="Delete dataset"
        destructive
        busy={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}
