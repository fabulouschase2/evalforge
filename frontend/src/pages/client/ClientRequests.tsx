// Client project requests: submit new requests, track status and admin history.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Paperclip } from "lucide-react";
import { api } from "@/lib/api";
import { clientQueries, type ClientRequest } from "@/api/clientHooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

const CATEGORIES = [
  { value: "ai_response_evaluation", label: "AI response evaluation" },
  { value: "data_annotation", label: "Data annotation" },
  { value: "text_classification", label: "Text classification" },
  { value: "factuality_verification", label: "Factuality verification" },
  { value: "instruction_following_evaluation", label: "Instruction-following evaluation" },
  { value: "coding_evaluation", label: "Coding evaluation" },
  { value: "image_annotation", label: "Image annotation" },
  { value: "video_annotation", label: "Video annotation" },
  { value: "audio_annotation", label: "Audio annotation" },
  { value: "speech_transcription", label: "Speech transcription" },
  { value: "multimodal_evaluation", label: "Multimodal evaluation" },
  { value: "ai_safety_evaluation", label: "AI safety evaluation" },
  { value: "custom_evaluation", label: "Custom evaluation" },
];

const STATUS_VARIANTS: Record<string, "info" | "success" | "danger" | "warning" | "neutral"> = {
  draft: "neutral", submitted: "info", under_review: "info",
  more_info_required: "warning", approved: "success", rejected: "danger", converted: "success",
};

const EMPTY_FORM = {
  title: "", description: "", category: "ai_response_evaluation",
  expected_task_volume: "", required_languages: "", required_skills: "",
  dataset_availability: "csv_upload", expected_delivery: "",
  quality_requirements: "", special_instructions: "",
};

function RequestDetail({ req }: { req: ClientRequest }) {
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <div><span className="text-fg-muted">Category:</span> {CATEGORIES.find((c) => c.value === req.category)?.label ?? req.category}</div>
        <div><span className="text-fg-muted">Expected volume:</span> {req.expected_task_volume ?? "—"}</div>
        <div><span className="text-fg-muted">Languages:</span> {req.required_languages.join(", ") || "—"}</div>
        <div><span className="text-fg-muted">Skills:</span> {req.required_skills.join(", ") || "—"}</div>
        <div><span className="text-fg-muted">Dataset:</span> {req.dataset_availability ?? "—"}</div>
        <div><span className="text-fg-muted">Expected delivery:</span> {fmtDateTime(req.expected_delivery) || "—"}</div>
      </div>
      {req.description && <p className="whitespace-pre-wrap text-fg-muted">{req.description}</p>}
      {req.quality_requirements && (
        <p><span className="text-fg-muted">Quality requirements:</span> {req.quality_requirements}</p>
      )}
      {req.special_instructions && (
        <p><span className="text-fg-muted">Special instructions:</span> {req.special_instructions}</p>
      )}
      {req.attachments.length > 0 && (
        <div>
          <span className="text-fg-muted">Attachments:</span>
          <ul className="mt-1 space-y-1">
            {req.attachments.map((a, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs text-fg">
                <Paperclip className="h-3 w-3" /> {a.filename} ({Math.round((a.size ?? 0) / 1024)} KB)
              </li>
            ))}
          </ul>
        </div>
      )}
      {req.admin_response && (
        <div className="rounded-md border border-line bg-surface-raised p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Team response</div>
          <p className="mt-1 whitespace-pre-wrap text-fg">{req.admin_response}</p>
        </div>
      )}
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">History</div>
        <ul className="mt-2 space-y-1.5">
          {(req.admin_history ?? []).map((h, i) => (
            <li key={i} className="flex items-center gap-2 text-xs text-fg-muted">
              <Badge variant={STATUS_VARIANTS[h.action === "approve" ? "approved" : h.action === "reject" ? "rejected" : "info"] ?? "neutral"}>
                {h.action}
              </Badge>
              <span>{h.note || ""}</span>
              <span className="ml-auto whitespace-nowrap">{fmtDateTime(h.at)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function ClientRequests() {
  const qc = useQueryClient();
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [detail, setDetail] = useState<ClientRequest | null>(null);
  const [attachFor, setAttachFor] = useState<ClientRequest | null>(null);
  const [attachFile, setAttachFile] = useState<File | null>(null);

  const reqs = useQuery(clientQueries.requests(statusFilter || undefined));

  const createReq = useMutation({
    mutationFn: () => api.post("/client/requests", {
      ...form,
      expected_task_volume: form.expected_task_volume ? Number(form.expected_task_volume) : null,
      required_languages: form.required_languages.split(",").map((s) => s.trim()).filter(Boolean),
      required_skills: form.required_skills.split(",").map((s) => s.trim()).filter(Boolean),
      expected_delivery: form.expected_delivery || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-requests"] });
      qc.invalidateQueries({ queryKey: ["client-dashboard"] });
      setCreateOpen(false); setForm(EMPTY_FORM);
      toast("success", "Request submitted", "Our team will review it shortly.");
    },
    onError: (e) => toast("error", "Could not submit request", (e as Error).message),
  });

  const uploadAttachment = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", attachFile!);
      return api.upload(`/client/requests/${attachFor!.id}/attachments`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-requests"] });
      setAttachFor(null); setAttachFile(null);
      toast("success", "Attachment added");
    },
    onError: (e) => toast("error", "Upload failed", (e as Error).message),
  });

  const list = reqs.data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Project requests</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Describe the work you need; our administrators review and convert approved requests into projects.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}><FilePlus2 className="h-4 w-4" /> New request</Button>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Your requests</CardTitle>
          <NativeSelect aria-label="Filter by status" className="w-48" value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {["submitted", "under_review", "more_info_required", "approved", "rejected", "converted"].map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </NativeSelect>
        </CardHeader>
        <CardContent>
          {reqs.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : reqs.isError ? (
            <ErrorState message={(reqs.error as Error)?.message} retry={reqs.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="No requests yet"
              description="Create your first request — you can attach sample data to it." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Title</TH><TH>Category</TH><TH>Volume</TH><TH>Status</TH><TH>Updated</TH><TH /></TR>
              </THead>
              <TBody>
                {list.map((r) => (
                  <TR key={r.id}>
                    <TD className="max-w-[240px] truncate text-sm font-medium text-fg">{r.title}</TD>
                    <TD className="text-xs text-fg-muted">{CATEGORIES.find((c) => c.value === r.category)?.label ?? r.category}</TD>
                    <TD className="text-xs text-fg-muted">{r.expected_task_volume ?? "—"}</TD>
                    <TD><Badge variant={STATUS_VARIANTS[r.status] ?? "neutral"}>{r.status.replace(/_/g, " ")}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(r.updated_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setDetail(r)}>Details</Button>
                        {["submitted", "more_info_required"].includes(r.status) && (
                          <Button variant="ghost" size="sm" onClick={() => setAttachFor(r)}>Attach</Button>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create request */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New project request</DialogTitle>
            <DialogDescription>All fields help us scope the right team and rubric for you.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div><Label htmlFor="r-title">Project title *</Label>
              <Input id="r-title" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} /></div>
            <div><Label htmlFor="r-cat">Project category</Label>
              <NativeSelect id="r-cat" value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </NativeSelect></div>
            <div><Label htmlFor="r-desc">Description</Label>
              <Textarea id="r-desc" rows={3} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} /></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label htmlFor="r-vol">Expected task volume</Label>
                <Input id="r-vol" type="number" min={0} value={form.expected_task_volume} onChange={(e) => setForm((f) => ({ ...f, expected_task_volume: e.target.value }))} /></div>
              <div><Label htmlFor="r-del">Expected delivery date</Label>
                <Input id="r-del" type="date" value={form.expected_delivery} onChange={(e) => setForm((f) => ({ ...f, expected_delivery: e.target.value }))} /></div>
              <div><Label htmlFor="r-lang">Required languages (comma-separated)</Label>
                <Input id="r-lang" value={form.required_languages} onChange={(e) => setForm((f) => ({ ...f, required_languages: e.target.value }))} /></div>
              <div><Label htmlFor="r-skill">Required skills (comma-separated)</Label>
                <Input id="r-skill" value={form.required_skills} onChange={(e) => setForm((f) => ({ ...f, required_skills: e.target.value }))} /></div>
              <div><Label htmlFor="r-data">Dataset availability</Label>
                <NativeSelect id="r-data" value={form.dataset_availability} onChange={(e) => setForm((f) => ({ ...f, dataset_availability: e.target.value }))}>
                  <option value="ready">Ready now</option>
                  <option value="csv_upload">Will upload (CSV)</option>
                  <option value="json_upload">Will upload (JSON)</option>
                  <option value="needs_collection">Needs collection support</option>
                  <option value="partial">Partial</option>
                </NativeSelect></div>
            </div>
            <div><Label htmlFor="r-quality">Quality requirements</Label>
              <Textarea id="r-quality" rows={2} value={form.quality_requirements} onChange={(e) => setForm((f) => ({ ...f, quality_requirements: e.target.value }))} /></div>
            <div><Label htmlFor="r-special">Special instructions</Label>
              <Textarea id="r-special" rows={2} value={form.special_instructions} onChange={(e) => setForm((f) => ({ ...f, special_instructions: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={() => createReq.mutate()} disabled={!form.title || createReq.isPending}>
              {createReq.isPending ? "Submitting…" : "Submit request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detail */}
      <Dialog open={detail !== null} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{detail?.title}</DialogTitle>
            <DialogDescription>
              Status: <Badge variant={STATUS_VARIANTS[detail?.status ?? "draft"] ?? "neutral"}>{detail?.status.replace(/_/g, " ")}</Badge>
            </DialogDescription>
          </DialogHeader>
          {detail && <RequestDetail req={detail} />}
        </DialogContent>
      </Dialog>

      {/* Attachment upload */}
      <Dialog open={attachFor !== null} onOpenChange={(o) => !o && setAttachFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Attach supporting file — {attachFor?.title}</DialogTitle>
            <DialogDescription>CSV, JSON or JSONL up to 10 MB.</DialogDescription>
          </DialogHeader>
          <Input type="file" accept=".csv,.json,.jsonl,.ndjson"
            onChange={(e) => setAttachFile(e.target.files?.[0] ?? null)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttachFor(null)}>Cancel</Button>
            <Button onClick={() => uploadAttachment.mutate()} disabled={!attachFile || uploadAttachment.isPending}>
              {uploadAttachment.isPending ? "Uploading…" : "Upload"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
