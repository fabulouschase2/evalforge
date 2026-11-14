// Admin queue for client project requests: review, approve/reject, convert to project.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FolderPlus, MessageSquareWarning, Search, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { adminRequestQueries, type ClientRequest } from "@/api/clientHooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

const STATUS_VARIANTS: Record<string, "info" | "success" | "danger" | "warning" | "neutral"> = {
  draft: "neutral", submitted: "info", under_review: "info",
  more_info_required: "warning", approved: "success", rejected: "danger", converted: "success",
};

export default function ProjectRequestsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [detail, setDetail] = useState<ClientRequest | null>(null);
  const [note, setNote] = useState("");
  const [action, setAction] = useState<{ req: ClientRequest; kind: "approve" | "reject" | "more_info" | "under_review" } | null>(null);
  const [convertFor, setConvertFor] = useState<ClientRequest | null>(null);

  const reqs = useQuery(adminRequestQueries.all(status || undefined));
  const list = reqs.data ?? [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin-project-requests"] });
    qc.invalidateQueries({ queryKey: ["client-requests"] });
    qc.invalidateQueries({ queryKey: ["client-dashboard"] });
  };

  const review = useMutation({
    mutationFn: () => api.post<ClientRequest>(`/admin/project-requests/${action!.req.id}/review`,
      { action: action!.kind, note }),
    onSuccess: (data: ClientRequest) => {
      invalidate(); setAction(null); setNote("");
      toast("success", "Request updated", `Status is now "${data.status.replace(/_/g, " ")}".`);
    },
    onError: (e) => toast("error", "Review failed", (e as Error).message),
  });

  const convert = useMutation({
    mutationFn: () => api.post<{ project_id: number }>(`/admin/project-requests/${convertFor!.id}/convert`),
    onSuccess: (data) => {
      invalidate(); setConvertFor(null);
      toast("success", "Project created", `Project #${data.project_id} is now active.`);
    },
    onError: (e) => toast("error", "Conversion failed", (e as Error).message),
  });

  const pending = list.filter((r) => ["submitted", "under_review", "more_info_required"].includes(r.status));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Client project requests</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Approve, reject or ask for more information. Approved requests convert into real projects
          without losing any submitted details.
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Queue {pending.length > 0 && <Badge variant="warning">{pending.length} pending</Badge>}</CardTitle>
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-fg-muted" />
            <NativeSelect aria-label="Filter by status" className="w-48" value={status}
              onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {["submitted", "under_review", "more_info_required", "approved", "rejected", "converted"].map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </NativeSelect>
          </div>
        </CardHeader>
        <CardContent>
          {reqs.isLoading ? (
            <TableSkeleton rows={5} cols={5} />
          ) : reqs.isError ? (
            <ErrorState message={(reqs.error as Error)?.message} retry={reqs.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="No requests" description="Client requests will appear here for review." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Request</TH><TH>Organization</TH><TH>Category</TH><TH>Volume</TH><TH>Status</TH><TH>Submitted</TH><TH /></TR>
              </THead>
              <TBody>
                {list.map((r) => (
                  <TR key={r.id}>
                    <TD className="max-w-[220px] truncate text-sm font-medium text-fg">{r.title}</TD>
                    <TD className="text-xs text-fg-muted">{r.organization_name}</TD>
                    <TD className="text-xs text-fg-muted">{r.category.replace(/_/g, " ")}</TD>
                    <TD className="text-xs text-fg-muted">{r.expected_task_volume ?? "—"}</TD>
                    <TD><Badge variant={STATUS_VARIANTS[r.status] ?? "neutral"}>{r.status.replace(/_/g, " ")}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(r.created_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setDetail(r)}>View</Button>
                        {!["converted", "rejected"].includes(r.status) && (
                          <Button variant="ghost" size="sm"
                            onClick={() => setAction({ req: r, kind: "approve" })}>
                            <Check className="h-3.5 w-3.5 text-ok" /> Approve
                          </Button>
                        )}
                        {r.status === "approved" && (
                          <Button variant="ghost" size="sm"
                            onClick={() => setConvertFor(r)}>
                            <FolderPlus className="h-3.5 w-3.5" /> Convert
                          </Button>
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

      {/* Detail */}
      <Dialog open={detail !== null} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{detail?.title}</DialogTitle>
            <DialogDescription>
              {detail?.organization_name} · submitted by {detail?.submitted_by_name ?? "—"} ·{" "}
              <Badge variant={STATUS_VARIANTS[detail?.status ?? "draft"] ?? "neutral"}>
                {detail?.status.replace(/_/g, " ")}
              </Badge>
            </DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="space-y-3 text-sm">
              <div className="grid gap-2 sm:grid-cols-2">
                <div><span className="text-fg-muted">Category:</span> {detail.category.replace(/_/g, " ")}</div>
                <div><span className="text-fg-muted">Volume:</span> {detail.expected_task_volume ?? "—"}</div>
                <div><span className="text-fg-muted">Languages:</span> {detail.required_languages.join(", ") || "—"}</div>
                <div><span className="text-fg-muted">Skills:</span> {detail.required_skills.join(", ") || "—"}</div>
                <div><span className="text-fg-muted">Dataset:</span> {detail.dataset_availability ?? "—"}</div>
                <div><span className="text-fg-muted">Delivery:</span> {fmtDateTime(detail.expected_delivery) || "—"}</div>
              </div>
              {detail.description && <p className="whitespace-pre-wrap">{detail.description}</p>}
              {detail.quality_requirements && <p><span className="text-fg-muted">Quality:</span> {detail.quality_requirements}</p>}
              {detail.special_instructions && <p><span className="text-fg-muted">Instructions:</span> {detail.special_instructions}</p>}
              {detail.attachments.length > 0 && (
                <div className="text-xs text-fg-muted">
                  Attachments: {detail.attachments.map((a) => a.filename).join(", ")}
                </div>
              )}
              <div className="rounded-md border border-line bg-surface-raised p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">History</div>
                <ul className="mt-1.5 space-y-1 text-xs text-fg-muted">
                  {(detail.admin_history ?? []).map((h, i) => (
                    <li key={i}>{h.at.slice(0, 16).replace("T", " ")} — {h.role}: {h.action}{h.note ? ` — ${h.note}` : ""}</li>
                  ))}
                </ul>
              </div>
              {!["converted", "rejected"].includes(detail.status) && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => { setAction({ req: detail, kind: "approve" }); setDetail(null); }}>
                    <Check className="h-3.5 w-3.5" /> Approve
                  </Button>
                  <Button size="sm" variant="secondary"
                    onClick={() => { setAction({ req: detail, kind: "more_info" }); setDetail(null); }}>
                    <MessageSquareWarning className="h-3.5 w-3.5" /> Request info
                  </Button>
                  <Button size="sm" variant="secondary"
                    onClick={() => { setAction({ req: detail, kind: "reject" }); setDetail(null); }}>
                    <X className="h-3.5 w-3.5" /> Reject
                  </Button>
                </div>
              )}
              {detail.status === "approved" && (
                <Button size="sm" onClick={() => { setConvertFor(detail); setDetail(null); }}>
                  <FolderPlus className="h-3.5 w-3.5" /> Convert to project
                </Button>
              )}
              {detail.converted_project_id && (
                <Link to={`/projects/${detail.converted_project_id}`} className="text-xs text-teal hover:underline">
                  Open the converted project →
                </Link>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Review dialog */}
      <Dialog open={action !== null} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {action?.kind === "approve" && "Approve request"}
              {action?.kind === "reject" && "Reject request"}
              {action?.kind === "more_info" && "Request more information"}
              {action?.kind === "under_review" && "Move to review"}
            </DialogTitle>
            <DialogDescription>
              {action?.kind === "reject" || action?.kind === "more_info"
                ? "An explanation is required — the client sees it."
                : "Optionally add a note for the client."}
            </DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="rev-note">Note to the client</Label>
            <Textarea id="rev-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>Cancel</Button>
            <Button
              onClick={() => review.mutate()}
              disabled={review.isPending ||
                ((action?.kind === "reject" || action?.kind === "more_info") && !note.trim())}
            >
              {review.isPending ? "Saving…" : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Convert dialog */}
      <Dialog open={convertFor !== null} onOpenChange={(o) => !o && setConvertFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Convert “{convertFor?.title}” into a project?</DialogTitle>
            <DialogDescription>
              The project is created for {convertFor?.organization_name} with the submitted scope
              (category, volume, languages, skills, quality requirements, instructions). The request
              keeps its full history.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConvertFor(null)}>Cancel</Button>
            <Button onClick={() => convert.mutate()} disabled={convert.isPending}>
              {convert.isPending ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
