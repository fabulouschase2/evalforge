import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload, FileJson, FileSpreadsheet, AlertTriangle, CheckCircle2, Copy, FileUp } from "lucide-react";
import { api } from "@/lib/api";
import { queries, useImportCommit, useImportPreview } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff } from "@/lib/roles";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime, truncate } from "@/lib/utils";
import type { DatasetRecord, ImportReport } from "@/lib/types";

const CANONICAL_FIELDS = ["record_id", "prompt", "response", "reference_answer", "reference_sources", "expected_label", "gold_explanation", "metadata"];

function UploadWizard({ datasetId, onDone }: { datasetId: number; onDone: () => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [step, setStep] = useState<"select" | "review" | "mapped">("select");

  const preview = useImportPreview(datasetId);
  const commit = useImportCommit(datasetId, () => {
    toast("success", "Import committed", "A new immutable dataset version was created.");
    setFile(null);
    setReport(null);
    setStep("select");
    onDone();
  });

  const doPreview = (f: File) => {
    setFile(f);
    preview.mutate(
      { file: f },
      {
        onSuccess: (r) => {
          setReport(r);
          // Pre-fill mapping: identity for detected canonical names
          const m: Record<string, string> = {};
          for (const field of CANONICAL_FIELDS) {
            if (r.detected_columns.includes(field)) m[field] = field;
          }
          setMapping(m);
          setStep("review");
        },
        onError: (e) => toast("error", "Could not parse file", (e as Error).message),
      },
    );
  };

  const missing = ["prompt", "response"].filter((f) => !(mapping[f] && report?.detected_columns.includes(mapping[f])));

  const rePreview = () => {
    if (!file) return;
    preview.mutate(
      { file, columnMapping: mapping },
      {
        onSuccess: (r) => {
          setReport(r);
          setStep("mapped");
        },
        onError: (e) => toast("error", "Could not parse file", (e as Error).message),
      },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FileUp className="h-4 w-4 text-teal" /> Import records</CardTitle>
        <CardDescription>
          Upload CSV, JSON or JSONL. Files are parsed as data only — uploaded content is never executed.
          A new immutable version is created on commit.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.json,.jsonl,.ndjson"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) doPreview(f);
            e.target.value = "";
          }}
        />

        {step === "select" && (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex w-full flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-base-panel/30 px-6 py-10 text-center hover:border-teal/50 hover:bg-teal-soft/50"
          >
            <Upload className="h-8 w-8 text-teal" />
            <span className="text-sm font-medium text-fg">Choose a file to import</span>
            <span className="text-xs text-fg-muted">CSV, JSON, JSONL · max 25 MB · preview before commit</span>
          </button>
        )}

        {(step === "review" || step === "mapped") && report && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-md border border-border bg-base-panel/40 p-3 text-center">
                <div className="text-lg font-bold text-fg">{report.total_rows}</div>
                <div className="text-[10px] uppercase tracking-wide text-fg-muted">Total rows</div>
              </div>
              <div className="rounded-md border border-ok/30 bg-[rgba(34,197,94,0.08)] p-3 text-center">
                <div className="text-lg font-bold text-ok">{report.valid_count}</div>
                <div className="text-[10px] uppercase tracking-wide text-fg-muted">Valid</div>
              </div>
              <div className="rounded-md border border-danger/30 bg-[rgba(239,68,68,0.08)] p-3 text-center">
                <div className="text-lg font-bold text-danger">{report.invalid_count}</div>
                <div className="text-[10px] uppercase tracking-wide text-fg-muted">Invalid</div>
              </div>
              <div className="rounded-md border border-warn/30 bg-[rgba(245,158,11,0.08)] p-3 text-center">
                <div className="text-lg font-bold text-warn">{report.duplicate_count}</div>
                <div className="text-[10px] uppercase tracking-wide text-fg-muted">Duplicates</div>
              </div>
            </div>

            {report.missing_required_fields.length > 0 && report.missing_required_fields.some((f) => !mapping[f]) && (
              <div className="rounded-md border border-warn/40 bg-[rgba(245,158,11,0.08)] px-4 py-3 text-sm text-warn">
                <AlertTriangle className="mr-1 inline h-4 w-4" />
                Required fields not detected in the source columns: {report.missing_required_fields.join(", ")}. Map them below.
              </div>
            )}
            {report.warnings.map((w, i) => (
              <div key={i} className="rounded-md border border-border bg-base-panel/40 px-4 py-2.5 text-xs text-fg-muted">
                {w}
              </div>
            ))}

            {/* Column mapping */}
            <div>
              <Label>Column mapping</Label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {CANONICAL_FIELDS.map((field) => (
                  <div key={field} className="flex items-center gap-2">
                    <span className="w-36 font-mono text-xs text-fg-muted">{field}</span>
                    <NativeSelect
                      aria-label={`Map ${field}`}
                      className="h-8 flex-1 text-xs"
                      value={mapping[field] ?? ""}
                      onChange={(e) => setMapping((m) => ({ ...m, [field]: e.target.value }))}
                    >
                      <option value="">— not mapped —</option>
                      {report.detected_columns.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </NativeSelect>
                  </div>
                ))}
              </div>
              {step === "review" && (
                <Button variant="secondary" size="sm" className="mt-3" onClick={rePreview} disabled={preview.isPending}>
                  {preview.isPending ? "Analyzing…" : "Apply mapping & re-analyze"}
                </Button>
              )}
            </div>

            {/* Preview table */}
            <div>
              <Label>Preview (first {report.preview.length} rows)</Label>
              <div className="max-h-72 overflow-auto rounded-md border border-border scroll-thin">
                <Table>
                  <THead>
                    <TR>
                      <TH>Record ID</TH>
                      <TH>Prompt</TH>
                      <TH>Response</TH>
                      <TH>Gold label</TH>
                      <TH>Issues</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {report.preview.map((row, i) => (
                      <TR key={i}>
                        <TD className="font-mono text-xs">{row.record_id}</TD>
                        <TD className="max-w-[220px] text-xs text-fg-muted">{truncate(row.prompt, 90)}</TD>
                        <TD className="max-w-[220px] text-xs text-fg-muted">{truncate(row.response, 90)}</TD>
                        <TD>{row.expected_label ? <Badge variant={row.expected_label === "pass" ? "success" : row.expected_label === "fail" ? "danger" : "warning"}>{row.expected_label}</Badge> : "—"}</TD>
                        <TD>
                          {row.errors?.length
                            ? <span className="text-xs text-danger">{row.errors.join("; ")}</span>
                            : <CheckCircle2 className="h-4 w-4 text-ok" />}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            </div>

            {report.invalid_records.length > 0 && (
              <div>
                <Label>Invalid rows (skipped on commit)</Label>
                <div className="max-h-40 overflow-auto rounded-md border border-border p-3 text-xs text-fg-muted scroll-thin">
                  {report.invalid_records.map((r) => (
                    <div key={r.row} className="py-0.5 font-mono">
                      row {r.row} ({r.record_id}): {r.errors.join("; ")}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <Label htmlFor="imp-notes">Version notes (optional)</Label>
              <Input id="imp-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What changed in this version?" />
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => { setStep("select"); setReport(null); setFile(null); }}>
                Cancel
              </Button>
              <Button
                disabled={report.valid_count === 0 || missing.length > 0 || commit.isPending}
                onClick={() =>
                  commit.mutate({
                    file: file!,
                    columnMapping: mapping,
                    notes: notes || undefined,
                  })
                }
              >
                {commit.isPending ? "Committing…" : `Commit import (${report.valid_count} records)`}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function DatasetDetailPage() {
  const { id } = useParams();
  const datasetId = Number(id);
  const { user } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const canEdit = isStaff(user?.role ?? "");

  const dataset = useQuery(queries.dataset(datasetId));
  const versions = useQuery(queries.datasetVersions(datasetId));
  const [page, setPage] = useState(1);
  const [versionId, setVersionId] = useState<number | undefined>(undefined);
  const records = useQuery(queries.datasetRecords(datasetId, versionId, page, 20));

  const deleteVersion = useMutation({
    mutationFn: () => api.del(`/datasets/${datasetId}`),
    onSuccess: () => {
      qc.invalidateQueries();
      toast("success", "Dataset deleted");
    },
    onError: (e) => toast("error", "Cannot delete dataset", (e as Error).message),
  });

  const currentVersion = useMemo(
    () => (versions.data ?? []).find((v) => v.version_number === dataset.data?.current_version),
    [versions.data, dataset.data],
  );

  if (dataset.isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (dataset.isError) return <ErrorState message={(dataset.error as Error)?.message} retry={dataset.refetch} />;

  const ds = dataset.data;
  if (!ds) return null;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-fg">
            {ds.name}
            {ds.is_demo && <Badge variant="warning">DEMONSTRATION</Badge>}
          </h1>
          <p className="mt-1 text-sm text-fg-muted">{ds.description ?? "No description"}</p>
        </div>
        <div className="flex gap-2">
          <Badge variant="info">{ds.format.toUpperCase()}</Badge>
          <Badge variant="neutral">v{ds.current_version} · {currentVersion?.record_count ?? "?"} records</Badge>
        </div>
      </div>

      {canEdit && <UploadWizard datasetId={datasetId} onDone={() => qc.invalidateQueries()} />}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Records</CardTitle>
            <CardDescription>
              Normalized evaluation records. Gold labels (expected_label) enable accuracy / precision / recall analytics.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {records.isLoading ? (
              <TableSkeleton rows={5} cols={4} />
            ) : records.isError ? (
              <ErrorState message={(records.error as Error)?.message} retry={records.refetch} />
            ) : (records.data?.items.length ?? 0) === 0 ? (
              <EmptyState icon={FileSpreadsheet} title="No records in this version"
                description="Import records to populate this dataset version." />
            ) : (
              <>
                <div className="max-h-[520px] overflow-auto rounded-md border border-border scroll-thin">
                  <Table>
                    <THead className="sticky top-0 bg-base-card">
                      <TR>
                        <TH>Record ID</TH>
                        <TH>Prompt</TH>
                        <TH>Response</TH>
                        <TH>Reference</TH>
                        <TH>Gold</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {(records.data!.items as DatasetRecord[]).map((r) => (
                        <TR key={r.id ?? r.record_id}>
                          <TD className="font-mono text-xs">{r.record_id}</TD>
                          <TD className="max-w-[240px] text-xs">{truncate(r.prompt, 120)}</TD>
                          <TD className="max-w-[240px] text-xs text-fg-muted">{truncate(r.response, 120)}</TD>
                          <TD className="max-w-[160px] text-xs text-fg-muted">{r.reference_answer ? truncate(r.reference_answer, 80) : "—"}</TD>
                          <TD>
                            {r.expected_label
                              ? <Badge variant={r.expected_label === "pass" ? "success" : r.expected_label === "fail" ? "danger" : "warning"}>{r.expected_label}</Badge>
                              : "—"}
                          </TD>
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

        <Card>
          <CardHeader>
            <CardTitle>Versions</CardTitle>
            <CardDescription>Immutable versions preserve exact records for reproducibility.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(versions.data ?? []).map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => { setVersionId(v.id === currentVersion?.id ? undefined : v.id); setPage(1); }}
                className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors ${
                  (versionId ?? currentVersion?.id) === v.id ? "border-teal/60 bg-teal-soft" : "border-border hover:bg-base-panel/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-fg">Version {v.version_number}</span>
                  <Badge variant="neutral">{v.record_count} records</Badge>
                </div>
                <div className="mt-1 text-xs text-fg-muted">{fmtDateTime(v.created_at)}</div>
                {v.notes && <div className="mt-1 text-xs text-fg-muted italic">{v.notes}</div>}
                {v.content_hash && (
                  <div className="mt-1 flex items-center gap-1 font-mono text-[10px] text-fg-muted/70">
                    <Copy className="h-3 w-3" /> {v.content_hash.slice(0, 12)}…
                  </div>
                )}
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
