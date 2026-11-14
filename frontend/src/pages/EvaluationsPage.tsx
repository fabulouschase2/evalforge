import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, PlayCircle } from "lucide-react";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { fmtDateTime } from "@/lib/utils";
import type { EvaluationRun } from "@/lib/types";

export default function EvaluationsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const evaluations = useQuery(queries.evaluations());
  const datasets = useQuery(queries.datasets());
  const rubrics = useQuery(queries.rubrics());

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [rubricId, setRubricId] = useState("");

  const create = useMutation({
    mutationFn: () => api.post<EvaluationRun>("/evaluations", {
      name,
      dataset_id: Number(datasetId),
      rubric_id: Number(rubricId),
    }),
    onSuccess: (run) => {
      qc.invalidateQueries();
      setOpen(false);
      toast("info", "Evaluation created", "Press Run to execute the automated checks.");
      navigate(`/evaluations/${run.id}`);
    },
    onError: (e) => toast("error", "Could not create evaluation", (e as Error).message),
  });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">Evaluations</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Automated evaluation runs. Each run pins an exact dataset version and rubric version.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New evaluation</Button>
      </div>

      {evaluations.isLoading ? (
        <TableSkeleton rows={5} cols={6} />
      ) : evaluations.isError ? (
        <ErrorState message={(evaluations.error as Error)?.message} retry={evaluations.refetch} />
      ) : (evaluations.data as EvaluationRun[]).length === 0 ? (
        <EmptyState
          icon={PlayCircle}
          title="No evaluation runs yet"
          description="Create an evaluation run combining a dataset and a rubric, then execute the deterministic checks."
          action={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New evaluation</Button>}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>Run</TH>
                  <TH>Status</TH>
                  <TH>Records</TH>
                  <TH>Pass</TH>
                  <TH>Fail</TH>
                  <TH>Borderline</TH>
                  <TH>Avg score</TH>
                  <TH>Created</TH>
                </TR>
              </THead>
              <TBody>
                {(evaluations.data as EvaluationRun[]).map((run) => (
                  <TR key={run.id}>
                    <TD>
                      <Link to={`/evaluations/${run.id}`} className="font-medium text-teal hover:underline">
                        {run.name}
                      </Link>
                      {run.is_demo && <Badge variant="warning" className="ml-2">DEMO</Badge>}
                    </TD>
                    <TD><StatusBadge status={run.status} /></TD>
                    <TD>{run.total_records}</TD>
                    <TD className="text-ok">{run.passed_count}</TD>
                    <TD className="text-danger">{run.failed_count}</TD>
                    <TD className="text-warn">{run.borderline_count}</TD>
                    <TD>{run.avg_score !== null ? run.avg_score.toFixed(2) : "—"}</TD>
                    <TD className="text-fg-muted">{fmtDateTime(run.created_at)}</TD>
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
            <DialogTitle>New evaluation run</DialogTitle>
            <DialogDescription>
              The run uses the latest version of the selected dataset and rubric unless pinned versions exist.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="ev-name">Run name</Label>
              <Input id="ev-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Q3 support quality check" />
            </div>
            <div>
              <Label htmlFor="ev-ds">Dataset</Label>
              <NativeSelect id="ev-ds" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
                <option value="">— Select dataset —</option>
                {(datasets.data ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name} (v{d.current_version})</option>
                ))}
              </NativeSelect>
            </div>
            <div>
              <Label htmlFor="ev-ru">Rubric</Label>
              <NativeSelect id="ev-ru" value={rubricId} onChange={(e) => setRubricId(e.target.value)}>
                <option value="">— Select rubric —</option>
                {(rubrics.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>{r.name} (v{r.current_version})</option>
                ))}
              </NativeSelect>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim() || !datasetId || !rubricId || create.isPending}>
              {create.isPending ? "Creating…" : "Create run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
