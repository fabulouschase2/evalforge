// Quality lead: golden task results, per-worker accuracy and alert triage.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";

interface GoldenReport {
  attempts: number; passed: number; failed: number; accuracy: number | null;
  insufficient_reason: string | null;
  by_difficulty: Record<string, { attempts: number; passed: number; accuracy: number | null }>;
  by_worker: { worker_id: number; attempts: number; passed: number; accuracy: number | null }[];
  calculation: Record<string, unknown>;
  note: string;
}

interface Alert {
  id: number; project_id: number | null; worker_id: number | null;
  alert_type: string; severity: string; message: string; evidence: Record<string, unknown>;
  resolved: boolean; created_at: string | null;
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

export default function GoldenMonitoringPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [resolveFor, setResolveFor] = useState<Alert | null>(null);
  const [note, setNote] = useState("");

  const report = useQuery({
    queryKey: ["golden-report"],
    queryFn: () => api.get<GoldenReport>("/quality/golden/report"),
  });
  const alerts = useQuery({
    queryKey: ["golden-alerts"],
    queryFn: () => api.get<Alert[]>("/quality/golden/alerts"),
  });

  const resolve = useMutation({
    mutationFn: () => api.post(`/quality/golden/alerts/${resolveFor!.id}/resolve`, { note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["golden-alerts"] });
      setResolveFor(null); setNote("");
      toast("success", "Alert resolved");
    },
    onError: (e) => toast("error", "Could not resolve", (e as Error).message),
  });

  const r = report.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Golden task monitoring</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Worker accuracy on known-answer probes. Computed only from stored scoring records.
        </p>
      </div>

      {report.isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : report.isError ? (
        <ErrorState message={(report.error as Error)?.message} retry={report.refetch} />
      ) : r && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Card><CardContent className="p-4">
              <div className="text-2xl font-bold text-fg">{r.attempts}</div>
              <div className="text-xs text-fg-muted">Golden attempts</div>
            </CardContent></Card>
            <Card><CardContent className="p-4">
              <div className="text-2xl font-bold text-ok">{r.passed}</div>
              <div className="text-xs text-fg-muted">Passed</div>
            </CardContent></Card>
            <Card><CardContent className="p-4">
              <div className="text-2xl font-bold text-danger">{r.failed}</div>
              <div className="text-xs text-fg-muted">Failed</div>
            </CardContent></Card>
            <Card><CardContent className="p-4">
              <div className="text-2xl font-bold text-fg">{pct(r.accuracy)}</div>
              <div className="text-xs text-fg-muted">Overall accuracy</div>
            </CardContent></Card>
          </div>

          {r.accuracy === null && (
            <Card><CardContent className="p-4 text-sm text-fg-muted">
              {r.insufficient_reason ?? "Insufficient data to compute accuracy."}
            </CardContent></Card>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Accuracy by difficulty</CardTitle>
                <CardDescription>{r.note}</CardDescription>
              </CardHeader>
              <CardContent>
                {Object.keys(r.by_difficulty).length === 0 ? (
                  <EmptyState title="No data yet" />
                ) : (
                  <Table>
                    <THead><TR><TH>Difficulty</TH><TH>Attempts</TH><TH>Accuracy</TH></TR></THead>
                    <TBody>
                      {Object.entries(r.by_difficulty).map(([d, b]) => (
                        <TR key={d}>
                          <TD className="text-sm text-fg">{d}</TD>
                          <TD className="text-xs text-fg-muted">{b.attempts}</TD>
                          <TD className="text-sm font-medium text-fg">{pct(b.accuracy)}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Per-worker accuracy</CardTitle>
                <CardDescription>Golden-task results only — not overall task quality.</CardDescription>
              </CardHeader>
              <CardContent>
                {r.by_worker.length === 0 ? (
                  <EmptyState title="No attempts yet" />
                ) : (
                  <Table>
                    <THead><TR><TH>Worker</TH><TH>Attempts</TH><TH>Passed</TH><TH>Accuracy</TH></TR></THead>
                    <TBody>
                      {r.by_worker.map((w) => (
                        <TR key={w.worker_id}>
                          <TD className="text-sm text-fg">Worker #{w.worker_id}</TD>
                          <TD className="text-xs text-fg-muted">{w.attempts}</TD>
                          <TD className="text-xs text-fg-muted">{w.passed}</TD>
                          <TD>
                            <Badge variant={(w.accuracy ?? 1) >= 0.8 ? "success" : (w.accuracy ?? 1) >= 0.6 ? "warning" : "danger"}>
                              {pct(w.accuracy)}
                            </Badge>
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400" /> Quality alerts
          </CardTitle>
          <CardDescription>Indicators for human investigation — never automatic suspensions.</CardDescription>
        </CardHeader>
        <CardContent>
          {alerts.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : alerts.isError ? (
            <ErrorState message={(alerts.error as Error)?.message} retry={alerts.refetch} />
          ) : (alerts.data ?? []).length === 0 ? (
            <EmptyState title="No open alerts" description="Thresholds are configurable per project in Golden Tasks → Queue config." />
          ) : (
            <Table>
              <THead><TR><TH>Type</TH><TH>Severity</TH><TH>Message</TH><TH>Project</TH><TH>Raised</TH><TH /></TR></THead>
              <TBody>
                {(alerts.data ?? []).map((a) => (
                  <TR key={a.id}>
                    <TD><Badge variant="warning">{a.alert_type.replace(/_/g, " ")}</Badge></TD>
                    <TD><Badge variant={a.severity === "info" ? "neutral" : "warning"}>{a.severity}</Badge></TD>
                    <TD className="max-w-[340px] text-sm text-fg">{a.message}</TD>
                    <TD className="text-xs text-fg-muted">{a.project_id ?? "—"}</TD>
                    <TD className="text-xs text-fg-muted">{fmtDateTime(a.created_at)}</TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setResolveFor(a)}>
                        <ShieldCheck className="h-3.5 w-3.5" /> Resolve
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={resolveFor !== null} onOpenChange={(o) => !o && setResolveFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Resolve alert</DialogTitle>
            <DialogDescription>Record what was investigated and the outcome.</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-fg-muted">{resolveFor?.message}</p>
          <textarea
            className="w-full rounded-md border border-line bg-surface p-2 text-sm text-fg"
            rows={3} placeholder="Resolution note…" value={note} onChange={(e) => setNote(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setResolveFor(null)}>Cancel</Button>
            <Button onClick={() => resolve.mutate()} disabled={resolve.isPending}>Resolve</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
