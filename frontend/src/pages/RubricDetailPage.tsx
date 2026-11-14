import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Wand2, History, Pencil } from "lucide-react";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { IssueList, parseRubricJson } from "@/lib/rubricBuilder";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Textarea, Input, Label } from "@/components/ui/input";
import { fmtDateTime } from "@/lib/utils";
import type { RubricVersion, ValidationIssue } from "@/lib/types";

export default function RubricDetailPage() {
  const { id } = useParams();
  const rubricId = Number(id);
  const toast = useToast();
  const qc = useQueryClient();

  const rubric = useQuery(queries.rubric(rubricId));
  const versions = useQuery(queries.rubricVersions(rubricId));
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editJson, setEditJson] = useState("");
  const [editName, setEditName] = useState("");
  const [issues, setIssues] = useState<{ errors: ValidationIssue[]; warnings: ValidationIssue[] } | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportText, setExportText] = useState("");

  const activeVersionNumber = selectedVersion ?? rubric.data?.current_version ?? 1;
  const activeVersion = (versions.data ?? []).find((v) => v.version_number === activeVersionNumber);

  const validate = useMutation({
    mutationFn: (def: unknown) =>
      api.post<{ valid: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] }>("/rubrics/validate", { definition: def }),
    onSuccess: (r) => setIssues({ errors: r.errors, warnings: r.warnings }),
  });

  const saveUpdate = useMutation({
    mutationFn: () => {
      const def = parseRubricJson(editJson);
      return api.put(`/rubrics/${rubricId}`, { name: editName || undefined, definition: def });
    },
    onSuccess: () => {
      qc.invalidateQueries();
      setEditOpen(false);
      setIssues(null);
      toast("success", "Rubric updated", "A new immutable version was created.");
    },
    onError: (e) => {
      try {
        const parsed = JSON.parse((e as Error).message);
        if (parsed?.errors) setIssues({ errors: parsed.errors, warnings: [] });
        else toast("error", "Update failed", (e as Error).message);
      } catch {
        toast("error", "Update failed", (e as Error).message);
      }
    },
  });

  const copyExport = () => {
    navigator.clipboard.writeText(exportText).then(
      () => toast("success", "Copied to clipboard"),
      () => toast("error", "Clipboard unavailable — select the text and copy manually"),
    );
  };

  const downloadExport = () => {
    const blob = new Blob([exportText], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rubric-${rubricId}-v${activeVersionNumber}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (rubric.isLoading) return <TableSkeleton rows={4} cols={3} />;
  if (rubric.isError) return <ErrorState message={(rubric.error as Error)?.message} retry={rubric.refetch} />;

  const r = rubric.data;
  if (!r) return null;
  const def = activeVersion?.definition;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-fg">
            {r.name}
            {r.is_demo && <Badge variant="warning">DEMO</Badge>}
          </h1>
          <p className="mt-1 text-sm text-fg-muted">{r.description ?? "No description"}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => {
            setExportText(JSON.stringify(def ?? {}, null, 2));
            setExportOpen(true);
          }}>
            <Download className="h-3.5 w-3.5" /> Export JSON
          </Button>
          <Button size="sm" onClick={() => {
            setEditJson(JSON.stringify(def ?? {}, null, 2));
            setEditName(r.name);
            setEditOpen(true);
          }}>
            <Pencil className="h-3.5 w-3.5" /> Edit (new version)
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-4">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><History className="h-4 w-4 text-teal" /> Versions</CardTitle>
            <CardDescription>Definitions are immutable.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(versions.data ?? []).map((v: RubricVersion) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setSelectedVersion(v.version_number)}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                  v.version_number === activeVersionNumber ? "border-teal/60 bg-teal-soft" : "border-border hover:bg-base-panel/50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-fg">v{v.version_number}</span>
                  {v.version_number === r.current_version && <Badge variant="default">current</Badge>}
                </div>
                <div className="mt-0.5 text-xs text-fg-muted">{fmtDateTime(v.created_at)}</div>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Definition (v{activeVersionNumber})</CardTitle>
            <CardDescription>
              {def?.criteria.length ?? 0} criteria · passing threshold {def?.passing_threshold}
              {def?.borderline_rules && ` · borderline: confidence < ${def.borderline_rules.confidence_below}, margin ${def.borderline_rules.score_margin}`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!def ? (
              <EmptyState title="No definition found" description="This rubric version could not be loaded." />
            ) : (
              <>
                {def.criteria.map((c) => (
                  <div key={c.id} className="rounded-md border border-border p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-semibold text-fg">{c.name}</span>
                        <span className="ml-2 font-mono text-xs text-fg-muted">{c.id}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="info">weight {(c.weight * 100).toFixed(0)}%</Badge>
                        <Badge variant="neutral">{c.scoring_scale.type} {c.scoring_scale.min}–{c.scoring_scale.max}</Badge>
                        <Badge variant="neutral">pass ≥ {c.pass_threshold}</Badge>
                      </div>
                    </div>
                    {c.description && <p className="mt-1.5 text-xs text-fg-muted">{c.description}</p>}
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {c.checks.map((chk, i) => (
                        <span key={i} className="inline-flex max-w-full items-center gap-1 rounded border border-border bg-base-panel/60 px-2 py-0.5 font-mono text-[11px] text-fg-muted">
                          {chk.type}
                          <span className="truncate">{JSON.stringify(chk.params)}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
                {def.human_review_policy && (
                  <div className="text-xs text-fg-muted">
                    Human review policy: when_borderline={String(def.human_review_policy.when_borderline)},
                    {" "}when_failed={String(def.human_review_policy.when_failed)},
                    {" "}sample_failed_pct={def.human_review_policy.sample_failed_pct ?? 0}
                  </div>
                )}
                {def.expected_evidence && <div className="text-xs text-fg-muted">Expected evidence: {def.expected_evidence}</div>}
                {def.borderline_conditions && <div className="text-xs text-fg-muted">Borderline conditions: {def.borderline_conditions}</div>}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={(o) => { setEditOpen(o); if (!o) setIssues(null); }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Edit rubric definition</DialogTitle>
            <DialogDescription>
              Definitions are never mutated in place — saving creates a new immutable version. Historical
              evaluations keep referencing the exact version they used.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="e-name">Rubric name</Label>
              <Input id="e-name" value={editName} onChange={(e) => setEditName(e.target.value)} />
            </div>
            <div className="flex items-center justify-between">
              <Label className="mb-0">Definition JSON</Label>
              <Button variant="secondary" size="sm" onClick={() => validate.mutate(parseRubricJson(editJson))} disabled={validate.isPending}>
                <Wand2 className="h-3.5 w-3.5" /> Validate
              </Button>
            </div>
            {issues && (
              <div className="space-y-2">
                <IssueList issues={issues.errors} level="error" />
                <IssueList issues={issues.warnings} level="warning" />
              </div>
            )}
            <Textarea
              aria-label="Rubric definition JSON"
              className="min-h-[320px]"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
              spellCheck={false}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button onClick={() => saveUpdate.mutate()} disabled={saveUpdate.isPending}>
              {saveUpdate.isPending ? "Saving…" : "Save as new version"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Export dialog */}
      <Dialog open={exportOpen} onOpenChange={setExportOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Export rubric JSON — {r.name} (v{activeVersionNumber})</DialogTitle>
            <DialogDescription>Copy or download the immutable definition for external tooling.</DialogDescription>
          </DialogHeader>
          <Textarea readOnly aria-label="Export JSON" className="min-h-[320px]" value={exportText} spellCheck={false} />
          <DialogFooter>
            <Button variant="secondary" onClick={copyExport}>Copy</Button>
            <Button variant="outline" onClick={downloadExport}>Download</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
