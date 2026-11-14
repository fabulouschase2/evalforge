// Client dataset uploads with live import report (valid/invalid/duplicate rows).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, FileUp } from "lucide-react";
import { api } from "@/lib/api";
import { clientQueries } from "@/api/clientHooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";

interface ImportReport {
  total_rows: number; valid_count: number; invalid_count: number; duplicate_count: number;
  invalid_rows?: { row: number; errors: string[] }[];
}

export default function ClientDatasets() {
  const qc = useQueryClient();
  const toast = useToast();
  const [projectId, setProjectId] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [lastReport, setLastReport] = useState<{ dataset: { id: number; name: string; version: number }; report: ImportReport } | null>(null);
  const [previewDataset, setPreviewDataset] = useState<number | null>(null);

  const projects = useQuery(clientQueries.projects());
  const projectList = projects.data ?? [];
  const selectedProject = projectId || (projectList[0]?.id ? String(projectList[0].id) : "");

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file!);
      if (datasetName) fd.append("dataset_name", datasetName);
      return api.upload<{ dataset: { id: number; name: string; format: string; version: number }; report: ImportReport }>(
        `/client/projects/${selectedProject}/datasets`, fd);
    },
    onSuccess: (data) => {
      setLastReport(data);
      setFile(null); setDatasetName("");
      qc.invalidateQueries({ queryKey: ["client-projects"] });
      qc.invalidateQueries({ queryKey: ["client-project"] });
      toast("success", "Dataset imported",
        `${data.report.valid_count} valid rows committed as version ${data.dataset.version}.`);
    },
    onError: (e) => toast("error", "Import failed", (e as Error).message),
  });

  // Real preview query (dataset records through the client-scoped endpoint).
  const previewQuery = useQuery({
    queryKey: ["client-dataset-preview", previewDataset],
    queryFn: async () => {
      const owner = projectList.find((p) => p.datasets.some((d) => d.id === previewDataset));
      if (!owner) throw new Error("Project not found");
      return api.get<{ items: { id: number; record_id: string; prompt: string; response: string }[]; total: number }>(
        `/client/projects/${owner.id}/datasets/${previewDataset}/records?page=1&page_size=10`);
    },
    enabled: previewDataset != null,
  });

  if (projects.isLoading) return <div className="space-y-4"><EmptyState title="Loading projects…" /></div>;
  if (projects.isError) return <ErrorState message={(projects.error as Error)?.message} retry={projects.refetch} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Datasets</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Upload CSV / JSON / JSONL data for your projects. Files are validated and every import is versioned.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><CloudUpload className="h-4 w-4" /> Upload a dataset</CardTitle>
          <CardDescription>Each upload creates a new immutable version with a full validation report.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {projectList.length === 0 ? (
            <EmptyState title="No projects available"
              description="Datasets attach to projects. Submit a project request first." />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <Label htmlFor="cd-project">Project *</Label>
                  <NativeSelect id="cd-project" value={selectedProject} onChange={(e) => setProjectId(e.target.value)}>
                    {projectList.filter((p) => ["draft", "active"].includes(p.status)).map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </NativeSelect>
                </div>
                <div>
                  <Label htmlFor="cd-name">Dataset name (optional)</Label>
                  <Input id="cd-name" value={datasetName} onChange={(e) => setDatasetName(e.target.value)} placeholder="Defaults to the file name" />
                </div>
              </div>
              <div>
                <Label htmlFor="cd-file">Data file (CSV, JSON, JSONL — max upload limit applies)</Label>
                <Input id="cd-file" type="file" accept=".csv,.json,.jsonl,.ndjson"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>
              <Button onClick={() => upload.mutate()} disabled={!file || !selectedProject || upload.isPending}>
                <FileUp className="h-4 w-4" /> {upload.isPending ? "Importing…" : "Upload & validate"}
              </Button>

              {lastReport && (
                <div className="rounded-md border border-line bg-surface-raised p-3 text-sm">
                  <div className="font-semibold text-fg">
                    {lastReport.dataset.name} — version {lastReport.dataset.version}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 text-xs">
                    <Badge variant="success">{lastReport.report.valid_count} valid</Badge>
                    <Badge variant={lastReport.report.invalid_count ? "danger" : "neutral"}>
                      {lastReport.report.invalid_count} invalid
                    </Badge>
                    <Badge variant={lastReport.report.duplicate_count ? "warning" : "neutral"}>
                      {lastReport.report.duplicate_count} duplicates
                    </Badge>
                  </div>
                  {lastReport.report.invalid_rows && lastReport.report.invalid_rows.length > 0 && (
                    <div className="mt-2 max-h-40 overflow-auto rounded border border-line bg-base p-2 text-xs">
                      <div className="mb-1 font-semibold text-fg-muted">Rejected rows</div>
                      {lastReport.report.invalid_rows.slice(0, 20).map((r, i) => (
                        <div key={i} className="text-danger">Row {r.row}: {r.errors.join("; ")}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Datasets by project</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {projectList.length === 0 ? (
            <EmptyState title="Nothing to show" />
          ) : projectList.every((p) => p.datasets.length === 0) ? (
            <EmptyState title="No datasets yet" description="Upload your first dataset above." />
          ) : (
            projectList.filter((p) => p.datasets.length > 0).map((p) => (
              <div key={p.id}>
                <div className="mb-1.5 text-sm font-semibold text-fg">{p.name}</div>
                <ul className="space-y-1.5">
                  {p.datasets.map((d) => (
                    <li key={d.id} className="flex items-center gap-2 text-sm">
                      <Badge variant="neutral">v{d.current_version}</Badge>
                      <span className="font-medium text-fg">{d.name}</span>
                      <span className="text-xs text-fg-muted">{d.format} · {fmtDateTime(d.created_at)}</span>
                      <Button variant="ghost" size="sm" className="ml-auto"
                        onClick={() => setPreviewDataset(d.id === previewDataset ? null : d.id)}>
                        {d.id === previewDataset ? "Hide preview" : "Preview"}
                      </Button>
                    </li>
                  ))}
                </ul>
                {previewDataset != null && p.datasets.some((d) => d.id === previewDataset) && (
                  <div className="mt-2 overflow-auto rounded-md border border-line">
                    {previewQuery.isLoading ? (
                      <div className="p-3 text-xs text-fg-muted">Loading preview…</div>
                    ) : previewQuery.isError ? (
                      <div className="p-3 text-xs text-danger">{(previewQuery.error as Error).message}</div>
                    ) : (
                      <table className="w-full text-xs">
                        <thead className="bg-surface-raised text-left text-fg-muted">
                          <tr><th className="p-2">Record</th><th className="p-2">Prompt</th><th className="p-2">Response</th></tr>
                        </thead>
                        <tbody>
                          {(previewQuery.data?.items ?? []).map((r) => (
                            <tr key={r.id} className="border-t border-line">
                              <td className="p-2 font-mono text-fg-muted">{r.record_id}</td>
                              <td className="max-w-[300px] truncate p-2 text-fg">{r.prompt}</td>
                              <td className="max-w-[300px] truncate p-2 text-fg-muted">{r.response}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
