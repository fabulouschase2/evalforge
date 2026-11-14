// Data collection: dataset-level record browsing, manual creation, bulk paste,
// editing, deletion, custom fields, archive/restore and export.
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Upload, Pencil, Trash2, Archive, FileDown, ArchiveRestore, ClipboardPaste } from "lucide-react";
import { api } from "@/lib/api";
import { queries as v1queries } from "@/api/hooks";
import { isPlatformAdmin } from "@/lib/roles";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { truncate } from "@/lib/utils";
import type { Dataset, DatasetRecord, ProjectDetail } from "@/lib/types";

const BLANK_RECORD = {
  record_id: "", prompt: "", response: "", reference_answer: "",
  supporting_evidence: "", source_url: "", content_category: "",
  difficulty_level: "medium", language: "en", instructions: "",
  collection_status: "collected", custom_fields: {} as Record<string, unknown>,
};

export default function DataCollectionPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();

  const datasets = useQuery(v1queries.datasets());
  const projects = useQuery(v1queries.projects());
  const projectsList = (projects.data ?? []) as unknown as ProjectDetail[];
  const adminable = projectsList.filter((p) => p.is_admin);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<{ status?: string; category?: string; search?: string }>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [editing, setEditing] = useState<DatasetRecord | null>(null);
  const [deleteFor, setDeleteFor] = useState<DatasetRecord | null>(null);
  const [form, setForm] = useState({ ...BLANK_RECORD });
  const [pasteText, setPasteText] = useState("");

  const records = useQuery({
    queryKey: ["collection-records", selectedId, page, filters],
    queryFn: () => api.get<{ items: DatasetRecord[]; total: number; page: number; dataset_status: string }>(
      `/datasets/${selectedId}/records?page=${page}&page_size=20` +
      (filters.status ? `&status=${filters.status}` : "") +
      (filters.category ? `&category=${filters.category}` : "") +
      (filters.search ? `&search=${encodeURIComponent(filters.search)}` : ""),
    ),
    enabled: selectedId !== null,
  });

  const selectedDataset = (datasets.data as Dataset[] | undefined)?.find((d) => d.id === selectedId);
  const selectedIsAdmin = selectedDataset?.project_id
    ? projectsList.find((p) => p.id === selectedDataset.project_id)?.is_admin
    : isPlatformAdmin(user?.role ?? "");

  const createRecord = useMutation({
    mutationFn: () => api.post(`/datasets/${selectedId}/records`, form),
    onSuccess: () => { qc.invalidateQueries(); setCreateOpen(false); setForm({ ...BLANK_RECORD }); toast("success", "Record added"); },
    onError: (e) => toast("error", "Record rejected", formatDetail(e)),
  });

  const editRecord = useMutation({
    mutationFn: () => api.patch(`/datasets/${selectedId}/records/${editing!.id}`, form),
    onSuccess: () => { qc.invalidateQueries(); setEditing(null); toast("success", "Record updated"); },
    onError: (e) => toast("error", "Update rejected", formatDetail(e)),
  });

  const deleteRecord = useMutation({
    mutationFn: () => api.del(`/datasets/${selectedId}/records/${deleteFor!.id}`),
    onSuccess: () => { qc.invalidateQueries(); setDeleteFor(null); toast("success", "Record deleted"); },
    onError: (e) => { setDeleteFor(null); toast("error", "Cannot delete", (e as Error).message); },
  });

  const bulkPaste = useMutation({
    mutationFn: () => api.post<{ added: number; rejected: { row: number; errors: string[] }[] }>(
      `/datasets/${selectedId}/records/bulk`, { rows: JSON.parse(pasteText) }),
    onSuccess: (r: { added: number; rejected: { row: number; errors: string[] }[] }) => {
      qc.invalidateQueries(); setPasteOpen(false); setPasteText("");
      toast(r.rejected.length ? "info" : "success", `Imported ${r.added} record(s)`,
        r.rejected.length ? `${r.rejected.length} rejected: ${r.rejected.slice(0, 2).map((x) => x.errors[0]).join("; ")}` : undefined);
    },
    onError: (e) => toast("error", "Bulk import failed", formatDetail(e)),
  });

  const archive = useMutation({
    mutationFn: () => api.post(`/datasets/${selectedId}/${selectedDataset?.status === "archived" ? "restore" : "archive"}`),
    onSuccess: () => { qc.invalidateQueries(); toast("success", selectedDataset?.status === "archived" ? "Dataset restored" : "Dataset archived"); },
    onError: (e) => toast("error", "Failed", (e as Error).message),
  });

  function formatDetail(e: unknown): string {
    const msg = (e as Error).message;
    try {
      const parsed = JSON.parse(msg);
      if (parsed?.errors) return parsed.errors.join("; ");
    } catch { /* plain message */ }
    return msg;
  }

  const datasetList = (datasets.data as Dataset[] | undefined) ?? [];
  const visibleDatasets = datasetList.filter(
    (d) => !d.project_id || projectsList.some((p) => p.id === d.project_id),
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Data collection</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Browse records, add them manually or by pasting JSON, edit, delete, and export datasets.
            Records referenced by tasks are frozen for traceability.
          </p>
        </div>
        {selectedId !== null && selectedIsAdmin && selectedDataset?.status === "active" && (
          <div className="flex gap-2">
            <a href={`/api/datasets/${selectedId}/export?format=csv`} target="_blank" rel="noreferrer">
              <Button variant="ghost" size="sm"><FileDown className="h-4 w-4" /> Export CSV</Button>
            </a>
            <a href={`/api/datasets/${selectedId}/export?format=json`} target="_blank" rel="noreferrer">
              <Button variant="ghost" size="sm"><FileDown className="h-4 w-4" /> Export JSON</Button>
            </a>
            <Button variant="secondary" size="sm" onClick={() => { setForm({ ...BLANK_RECORD }); setCreateOpen(true); }}>
              <Plus className="h-3.5 w-3.5" /> Add record
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setPasteOpen(true)}>
              <ClipboardPaste className="h-3.5 w-3.5" /> Paste records
            </Button>
            <Button variant="outline" size="sm" onClick={() => archive.mutate()}>
              <Archive className="h-3.5 w-3.5" /> Archive
            </Button>
          </div>
        )}
        {selectedId !== null && selectedIsAdmin && selectedDataset?.status === "archived" && (
          <Button variant="outline" size="sm" onClick={() => archive.mutate()}>
            <ArchiveRestore className="h-3.5 w-3.5" /> Restore dataset
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
        {/* Dataset selector */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Datasets</CardTitle>
            <CardDescription>Select a dataset to browse its records.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {datasets.isLoading ? (
              <TableSkeleton rows={4} cols={1} />
            ) : visibleDatasets.length === 0 ? (
              <EmptyState title="No datasets" description="Create datasets on the Datasets page or import from files." />
            ) : (
              visibleDatasets.map((d) => (
                <button key={d.id} type="button" onClick={() => { setSelectedId(d.id); setPage(1); }}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    selectedId === d.id ? "border-teal/60 bg-teal-soft" : "border-border hover:bg-base-panel/50"
                  }`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium text-fg">{d.name}</span>
                    {d.is_demo && <Badge variant="warning">DEMO</Badge>}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-muted">
                    <span>v{d.current_version}</span>
                    {d.status === "archived" && <Badge variant="neutral">archived</Badge>}
                    {d.project_id && <span>· {projectsList.find((p) => p.id === d.project_id)?.name}</span>}
                  </div>
                </button>
              ))
            )}
            <Link to="/datasets" className="mt-2 block text-xs text-teal hover:underline">
              File import (CSV/JSON/JSONL) →
            </Link>
          </CardContent>
        </Card>

        {/* Records browser */}
        <Card className="lg:col-span-3">
          <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Records {selectedDataset ? `— ${selectedDataset.name}` : ""}</CardTitle>
              <CardDescription>
                {records.data ? `${records.data.total} records` : "Select a dataset"} · page {records.data?.page ?? 1}
                {selectedDataset?.status === "archived" && " · ARCHIVED (read-only)"}
              </CardDescription>
            </div>
            {selectedId !== null && (
              <div className="flex gap-2">
                <NativeSelect aria-label="Filter by status" className="h-8 w-36 text-xs" value={filters.status ?? ""}
                  onChange={(e) => { setFilters((f) => ({ ...f, status: e.target.value || undefined })); setPage(1); }}>
                  <option value="">All statuses</option>
                  <option value="collected">collected</option>
                  <option value="verified">verified</option>
                  <option value="flagged">flagged</option>
                </NativeSelect>
                <Input aria-label="Search records" placeholder="Search…" className="h-8 w-40 text-xs"
                  value={filters.search ?? ""} onChange={(e) => { setFilters((f) => ({ ...f, search: e.target.value || undefined })); setPage(1); }} />
              </div>
            )}
          </CardHeader>
          <CardContent>
            {selectedId === null ? (
              <EmptyState title="No dataset selected" description="Pick a dataset on the left to browse its records." />
            ) : records.isLoading ? (
              <TableSkeleton rows={6} cols={4} />
            ) : records.isError ? (
              <ErrorState message={(records.error as Error)?.message} retry={records.refetch} />
            ) : records.data!.items.length === 0 ? (
              <EmptyState title="No records" description="Add records manually or paste a JSON batch." />
            ) : (
              <>
                <div className="max-h-[520px] overflow-auto rounded-md border border-border scroll-thin">
                  <Table>
                    <THead className="sticky top-0 bg-base-card">
                      <TR>
                        <TH>ID</TH><TH>Prompt</TH><TH>Response</TH><TH>Category</TH><TH>Status</TH>
                        {selectedIsAdmin && selectedDataset?.status === "active" && <TH />}
                      </TR>
                    </THead>
                    <TBody>
                      {records.data!.items.map((r) => (
                        <TR key={r.id}>
                          <TD className="font-mono text-xs">{r.record_id}</TD>
                          <TD className="max-w-[220px] text-xs">{truncate(r.prompt, 90)}</TD>
                          <TD className="max-w-[220px] text-xs text-fg-muted">{truncate(r.response, 90)}</TD>
                          <TD className="text-xs text-fg-muted">{r.content_category ?? "—"}</TD>
                          <TD><Badge variant={r.collection_status === "verified" ? "success" : r.collection_status === "flagged" ? "danger" : "neutral"}>{r.collection_status}</Badge></TD>
                          {selectedIsAdmin && selectedDataset?.status === "active" && (
                            <TD className="text-right">
                              <div className="flex justify-end gap-1">
                                <Button variant="ghost" size="sm" title="Edit" onClick={() => {
                                  setEditing(r);
                                  setForm({
                                    record_id: r.record_id, prompt: r.prompt, response: r.response,
                                    reference_answer: r.reference_answer ?? "", supporting_evidence: r.supporting_evidence ?? "",
                                    source_url: r.source_url ?? "", content_category: r.content_category ?? "",
                                    difficulty_level: r.difficulty_level ?? "medium", language: r.language ?? "en",
                                    instructions: r.instructions ?? "", collection_status: r.collection_status ?? "collected",
                                    custom_fields: (r.custom_fields as Record<string, unknown>) ?? {},
                                  });
                                }}>
                                  <Pencil className="h-3.5 w-3.5" />
                                </Button>
                                <Button variant="ghost" size="sm" className="text-danger hover:text-danger" title="Delete"
                                  onClick={() => setDeleteFor(r)}>
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            </TD>
                          )}
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </div>
                {records.data!.total > 20 && (
                  <div className="mt-3 flex items-center justify-between text-sm text-fg-muted">
                    <span>Page {records.data!.page} of {Math.ceil(records.data!.total / 20)}</span>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                      <Button variant="outline" size="sm" disabled={page >= Math.ceil(records.data!.total / 20)} onClick={() => setPage((p) => p + 1)}>Next</Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Record create/edit dialog */}
      <Dialog open={createOpen || editing !== null} onOpenChange={(o) => { if (!o) { setCreateOpen(false); setEditing(null); } }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit record ${editing.record_id}` : "Add record manually"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "Records referenced by existing tasks cannot be modified (traceability guard)."
                : "The record joins the dataset's current version and is immediately available for task generation."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="r-prompt">Prompt (required)</Label>
              <Textarea id="r-prompt" className="font-sans text-sm" value={form.prompt}
                onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="r-response">AI response (required)</Label>
              <Textarea id="r-response" className="font-sans text-sm" value={form.response}
                onChange={(e) => setForm((f) => ({ ...f, response: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="r-ref">Reference answer</Label>
              <Input id="r-ref" value={form.reference_answer} onChange={(e) => setForm((f) => ({ ...f, reference_answer: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="r-cat">Content category</Label>
              <Input id="r-cat" value={form.content_category} onChange={(e) => setForm((f) => ({ ...f, content_category: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="r-diff">Difficulty</Label>
              <NativeSelect id="r-diff" value={form.difficulty_level} onChange={(e) => setForm((f) => ({ ...f, difficulty_level: e.target.value }))}>
                <option value="easy">easy</option><option value="medium">medium</option>
                <option value="hard">hard</option><option value="expert">expert</option>
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="r-lang">Language</Label>
              <Input id="r-lang" value={form.language} onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="r-status">Collection status</Label>
              <NativeSelect id="r-status" value={form.collection_status} onChange={(e) => setForm((f) => ({ ...f, collection_status: e.target.value }))}>
                <option value="collected">collected</option><option value="verified">verified</option>
                <option value="flagged">flagged</option>
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="r-src">Source URL</Label>
              <Input id="r-src" value={form.source_url} onChange={(e) => setForm((f) => ({ ...f, source_url: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="r-ev">Supporting evidence</Label>
              <Input id="r-ev" value={form.supporting_evidence} onChange={(e) => setForm((f) => ({ ...f, supporting_evidence: e.target.value }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setCreateOpen(false); setEditing(null); }}>Cancel</Button>
            {editing ? (
              <Button onClick={() => editRecord.mutate()} disabled={editRecord.isPending}>
                {editRecord.isPending ? "Saving…" : "Save changes"}
              </Button>
            ) : (
              <Button onClick={() => createRecord.mutate()} disabled={!form.prompt.trim() || !form.response.trim() || createRecord.isPending}>
                {createRecord.isPending ? "Adding…" : "Add record"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk paste dialog */}
      <Dialog open={pasteOpen} onOpenChange={setPasteOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Paste records (JSON array)</DialogTitle>
            <DialogDescription>
              Each object needs at least <code className="font-mono text-xs">prompt</code> and{" "}
              <code className="font-mono text-xs">response</code>. Optional: record_id, reference_answer,
              content_category, difficulty_level, language, supporting_evidence, source_url, collection_status, custom_fields.
            </DialogDescription>
          </DialogHeader>
          <Textarea aria-label="Records JSON" className="min-h-[220px]" value={pasteText}
            onChange={(e) => setPasteText(e.target.value)} spellCheck={false}
            placeholder='[{"prompt": "...", "response": "..."}]' />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPasteOpen(false)}>Cancel</Button>
            <Button onClick={() => bulkPaste.mutate()} disabled={bulkPaste.isPending || !pasteText.trim()}>
              {bulkPaste.isPending ? "Importing…" : "Import batch"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteFor !== null}
        onOpenChange={(o) => !o && setDeleteFor(null)}
        title={`Delete record "${deleteFor?.record_id}"?`}
        description="This permanently removes the record from the dataset. Records referenced by tasks cannot be deleted."
        confirmLabel="Delete record"
        destructive
        busy={deleteRecord.isPending}
        onConfirm={() => deleteRecord.mutate()}
      />
    </div>
  );
}
