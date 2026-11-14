// Client deliverables: published result packages with audited downloads.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { clientQueries, downloadDeliverable } from "@/api/clientHooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { NativeSelect } from "@/components/ui/input";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

function humanSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

export default function ClientDeliverables() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const projectFilter = params.get("project") ?? "";
  const [busyId, setBusyId] = useState<number | null>(null);

  const projects = useQuery(clientQueries.projects());
  const deliverables = useQuery(clientQueries.deliverables(projectFilter ? Number(projectFilter) : undefined));

  const doDownload = async (id: number, label: string, format: string) => {
    setBusyId(id);
    try {
      const { blob, disposition } = await downloadDeliverable(id);
      const match = /filename="?([^";]+)"?/.exec(disposition ?? "");
      const name = match?.[1] ?? `${label.replace(/\s+/g, "_")}.${format}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      URL.revokeObjectURL(url);
      toast("success", "Download started", `${name} — the download is recorded in the audit trail.`);
    } catch (e) {
      toast("error", "Download failed", (e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const list = deliverables.data ?? [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Deliverables</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Final approved results published by the delivery team. Every download is audited.
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Published packages</CardTitle>
          <NativeSelect aria-label="Filter by project" className="w-56" value={projectFilter}
            onChange={(e) => setParams(e.target.value ? { project: e.target.value } : {})}>
            <option value="">All projects</option>
            {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </NativeSelect>
        </CardHeader>
        <CardContent>
          {deliverables.isLoading ? (
            <TableSkeleton rows={3} cols={5} />
          ) : deliverables.isError ? (
            <ErrorState message={(deliverables.error as Error)?.message} retry={deliverables.refetch} />
          ) : list.length === 0 ? (
            <EmptyState title="No deliverables yet"
              description="Published result packages appear here when the team delivers." />
          ) : (
            <Table>
              <THead>
                <TR><TH>Label</TH><TH>Project</TH><TH>Format</TH><TH>Records</TH><TH>Size</TH><TH>Published</TH><TH>Downloads</TH><TH /></TR>
              </THead>
              <TBody>
                {list.map((d) => (
                  <TR key={d.id}>
                    <TD className="max-w-[200px]">
                      <div className="truncate text-sm font-medium text-fg">{d.label}</div>
                      {d.description && <div className="truncate text-xs text-fg-muted">{d.description}</div>}
                    </TD>
                    <TD className="text-xs text-fg-muted">{d.project_name ?? `#${d.project_id}`}</TD>
                    <TD><Badge variant="info">{d.export_format.toUpperCase()}</Badge></TD>
                    <TD className="text-xs text-fg-muted">{d.record_count}</TD>
                    <TD className="text-xs text-fg-muted">{humanSize(d.file_size)}</TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(d.published_at)}</TD>
                    <TD className="text-xs text-fg-muted">{d.download_count}</TD>
                    <TD className="text-right">
                      <Button size="sm" onClick={() => doDownload(d.id, d.label, d.export_format)}
                        disabled={busyId === d.id}>
                        <Download className="h-3.5 w-3.5" /> {busyId === d.id ? "…" : "Download"}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          {list.length > 0 && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-fg-muted">
              <ShieldCheck className="h-3.5 w-3.5 text-ok" />
              Checksums (SHA-256) are available on each file for integrity verification on your side.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
