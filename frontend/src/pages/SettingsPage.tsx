import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff, isPlatformAdmin } from "@/lib/roles";
import { useToast } from "@/components/ui/toast";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { Switch } from "@/components/ui/controls";
import { ErrorState, TableSkeleton } from "@/components/ui/states";
import type { AppSettings } from "@/lib/types";

export default function SettingsPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const isAdmin = isPlatformAdmin(user?.role ?? "");
  const { data, isLoading, isError, error, refetch } = useQuery(queries.settings());

  const [form, setForm] = useState<AppSettings | null>(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const save = useMutation({
    mutationFn: (updates: Partial<AppSettings>) => api.put<AppSettings>("/settings", updates),
    onSuccess: (s) => {
      qc.invalidateQueries();
      setForm(s);
      toast("success", "Settings saved");
    },
    onError: (e) => toast("error", "Could not save settings", (e as Error).message),
  });

  if (isLoading) return <TableSkeleton rows={4} cols={3} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;
  if (!form) return null;

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Settings</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Workspace-level evaluation defaults. Changes apply to future runs; existing results are never
          reclassified retroactively. {isAdmin ? "" : "Read-only for your role — changes require an administrator."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Human review workflow</CardTitle>
          <CardDescription>How flagged results are routed to independent reviewers.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-center justify-between rounded-md border border-border p-4">
            <div>
              <div className="text-sm font-medium text-fg">Blind reviews by default</div>
              <div className="mt-0.5 text-xs text-fg-muted">
                Reviewers cannot see peer assessments until their own is submitted.
              </div>
            </div>
            <Switch
              checked={form.review_blind_by_default}
              disabled={!isAdmin}
              onCheckedChange={(v) => set("review_blind_by_default", v)}
              aria-label="Blind reviews by default"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="s-reviewers">Reviewers per flagged result</Label>
              <NativeSelect
                id="s-reviewers" disabled={!isAdmin} className="w-40"
                value={String(form.reviewers_per_result)}
                onChange={(e) => set("reviewers_per_result", Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </NativeSelect>
              <div className="mt-1 text-xs text-fg-muted">More reviewers enable kappa calculations.</div>
            </div>
            <div>
              <Label htmlFor="s-upload">Max upload size (MB)</Label>
              <Input
                id="s-upload" type="number" min={1} max={200} disabled={!isAdmin}
                value={form.max_upload_mb}
                onChange={(e) => set("max_upload_mb", Number(e.target.value))}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Borderline detection thresholds</CardTitle>
          <CardDescription>
            Rubric-level rules override these workspace defaults. Low confidence never auto-classifies a
            response as incorrect — it routes to human review.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="s-conf">Route when automated confidence below</Label>
            <div className="flex items-center gap-3">
              <Input
                id="s-conf" type="number" step="0.05" min="0" max="1" disabled={!isAdmin}
                value={form.borderline_confidence_below}
                onChange={(e) => set("borderline_confidence_below", Number(e.target.value))}
              />
              <Badge variant="warning">uncertain_automated_decision</Badge>
            </div>
          </div>
          <div>
            <Label htmlFor="s-margin">Borderline score margin to passing threshold</Label>
            <div className="flex items-center gap-3">
              <Input
                id="s-margin" type="number" step="0.01" min="0" max="0.5" disabled={!isAdmin}
                value={form.borderline_score_margin}
                onChange={(e) => set("borderline_score_margin", Number(e.target.value))}
              />
              <Badge variant="warning">partially_correct</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {isAdmin && (
        <div className="flex justify-end">
          <Button
            onClick={() =>
              save.mutate({
                review_blind_by_default: form.review_blind_by_default,
                reviewers_per_result: form.reviewers_per_result,
                borderline_confidence_below: form.borderline_confidence_below,
                borderline_score_margin: form.borderline_score_margin,
                max_upload_mb: form.max_upload_mb,
              })
            }
            disabled={save.isPending}
          >
            {save.isPending ? "Saving…" : "Save settings"}
          </Button>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Environment</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 text-sm text-fg-muted sm:grid-cols-2">
          <div>Backend API: <span className="font-mono text-fg">/api (proxied to :8000)</span></div>
          <div>Auth: <span className="font-mono text-fg">JWT bearer tokens (bcrypt password hashing)</span></div>
          <div>Roles: <span className="font-mono text-fg">administrator · project_manager · evaluator · reviewer</span></div>
          <div>Your role: <Badge variant="default">{user?.role.replace(/_/g, " ")}</Badge></div>
        </CardContent>
      </Card>
    </div>
  );
}
