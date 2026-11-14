import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Upload, Download, Wand2, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, NativeSelect, Textarea } from "@/components/ui/input";
import { IssueList, emptyCriterion, emptyRubric, parseRubricJson, weightSum } from "@/lib/rubricBuilder";
import { CHECK_TYPES, type CheckDefinition, type CriterionDefinition, type RubricDefinition, type ValidationIssue } from "@/lib/types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";

const CHECK_PARAM_HINTS: Record<string, string> = {
  format_regex: '{"pattern": "^Answer:", "case_insensitive": true}',
  json_valid: '{"required_keys": ["summary", "detail"]}',
  min_words: '{"min": 10}',
  max_words: '{"max": 350}',
  min_chars: '{"min": 20}',
  max_chars: '{"max": 5000}',
  sentence_count: '{"min": 1, "max": 6}',
  required_keywords: '{"keywords": ["refund"], "mode": "all"}',
  forbidden_patterns: '{"patterns": ["https?://", "TODO"]}',
  required_fields: '{"fields": ["Summary", "Details"]}',
  completeness: '{}',
  evidence_citation: '{"min_citations": 1}',
  numeric_match: '{"tolerance": 0.01}',
  reference_overlap: '{"support_threshold": 0.45}',
};

export default function RubricNewPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [rubric, setRubric] = useState<RubricDefinition>(emptyRubric());
  const [rubricName, setRubricName] = useState("");
  const [description, setDescription] = useState("");
  const [jsonText, setJsonText] = useState(JSON.stringify(emptyRubric(), null, 2));
  const [issues, setIssues] = useState<{ errors: ValidationIssue[]; warnings: ValidationIssue[]; valid: boolean | null }>({ errors: [], warnings: [], valid: null });

  const validate = useMutation({
    mutationFn: (def: RubricDefinition) => api.post<{ valid: boolean; errors: ValidationIssue[]; warnings: ValidationIssue[] }>("/rubrics/validate", { definition: def }),
    onSuccess: (r) => setIssues(r),
  });

  const create = useMutation({
    mutationFn: (payload: { definition: RubricDefinition }) =>
      api.post<{ id: number }>("/rubrics", {
        name: rubricName || payload.definition.name,
        description,
        definition: payload.definition,
      }),
    onSuccess: (r) => {
      toast("success", "Rubric created", "Version 1 stored immutably.");
      navigate(`/rubrics/${r.id}`);
    },
    onError: (e) => {
      const msg = (e as Error).message;
      // Validation errors arrive structured — surface them inline.
      try {
        const parsed = JSON.parse(msg);
        if (parsed?.errors) setIssues({ valid: false, errors: parsed.errors, warnings: [] });
        else setIssues({ valid: false, errors: [{ level: "error", path: "$", message: parsed?.message ?? msg }], warnings: [] });
      } catch {
        setIssues({ valid: false, errors: [{ level: "error", path: "$", message: msg }], warnings: [] });
      }
    },
  });

  const update = (fn: (r: RubricDefinition) => void) => {
    setRubric((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
  };

  const updateCriterion = (idx: number, fn: (c: CriterionDefinition) => void) => {
    update((r) => fn(r.criteria[idx]));
  };

  const doValidate = () => {
    const def = mode === "json" ? (() => { const d = parseRubricJson(jsonText); setRubric(d); return d; })() : rubric;
    validate.mutate(def);
  };

  const doCreate = () => {
    const def = mode === "json" ? parseRubricJson(jsonText) : rubric;
    create.mutate({ definition: def });
  };

  const importJson = () => {
    try {
      const d = parseRubricJson(jsonText);
      setRubric(d);
      setRubricName(d.name || rubricName);
      setDescription(d.description || description);
      setMode("visual");
      toast("info", "JSON imported into the visual editor");
    } catch (e) {
      toast("error", "Invalid rubric JSON", (e as Error).message);
    }
  };

  const sum = weightSum(rubric);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-fg">New rubric</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Define criteria, weights, scoring scales and deterministic checks. Saving stores immutable version 1.
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/rubrics")}><ArrowLeft className="h-4 w-4" /> Back</Button>
      </div>

      <div className="mb-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <Label htmlFor="r-name">Rubric name</Label>
          <Input id="r-name" value={rubricName} onChange={(e) => setRubricName(e.target.value)} placeholder="Support Response Quality" />
        </div>
        <div>
          <Label htmlFor="r-desc">Description</Label>
          <Input id="r-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What does this rubric evaluate?" />
        </div>
      </div>

      <Tabs value={mode} onValueChange={(v) => setMode(v as "visual" | "json")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList aria-label="Editor mode">
            <TabsTrigger value="visual">Visual editor</TabsTrigger>
            <TabsTrigger value="json">JSON</TabsTrigger>
          </TabsList>
          <div className="flex gap-2">
            {mode === "json" && <Button variant="secondary" size="sm" onClick={importJson}><Upload className="h-3.5 w-3.5" /> Import to editor</Button>}
            <Button variant="secondary" size="sm" onClick={() => {
              const text = JSON.stringify(mode === "json" ? (() => { try { return parseRubricJson(jsonText); } catch { return rubric; } })() : rubric, null, 2);
              setJsonText(text);
              if (mode === "visual") setMode("json");
              toast("info", "Exported current definition to JSON");
            }}>
              <Download className="h-3.5 w-3.5" /> Export JSON
            </Button>
            <Button variant="secondary" size="sm" onClick={doValidate} disabled={validate.isPending}>
              <Wand2 className="h-3.5 w-3.5" /> {validate.isPending ? "Validating…" : "Validate"}
            </Button>
          </div>
        </div>

        {issues.valid === false && (
          <div className="mt-4 space-y-2">
            <IssueList issues={issues.errors} level="error" />
            <IssueList issues={issues.warnings} level="warning" />
          </div>
        )}
        {issues.valid === true && (
          <div className="mt-4 rounded-md border border-ok/40 bg-[rgba(34,197,94,0.07)] px-4 py-3 text-sm text-ok" role="status">
            Rubric definition is valid{issues.warnings.length > 0 ? ` (with ${issues.warnings.length} warning(s))` : ""}.
          </div>
        )}

        <TabsContent value="visual">
          <div className="space-y-4">
            {rubric.criteria.map((crit, idx) => (
              <Card key={idx}>
                <CardHeader className="flex-row items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    Criterion {idx + 1}
                    <span className="font-mono text-xs font-normal text-fg-muted">({crit.id})</span>
                  </CardTitle>
                  <Button
                    variant="ghost" size="icon" aria-label={`Remove criterion ${idx + 1}`}
                    className="text-danger hover:text-danger"
                    disabled={rubric.criteria.length <= 1}
                    onClick={() => update((r) => { r.criteria.splice(idx, 1); })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                    <div className="sm:col-span-2">
                      <Label htmlFor={`crit-name-${idx}`}>Criterion name</Label>
                      <Input id={`crit-name-${idx}`} value={crit.name} onChange={(e) => updateCriterion(idx, (c) => { c.name = e.target.value; })} placeholder="Format compliance" />
                    </div>
                    <div>
                      <Label htmlFor={`crit-id-${idx}`}>ID (unique)</Label>
                      <Input id={`crit-id-${idx}`} value={crit.id} onChange={(e) => updateCriterion(idx, (c) => { c.id = e.target.value; })} className="font-mono text-xs" />
                    </div>
                    <div>
                      <Label htmlFor={`crit-weight-${idx}`}>Weight</Label>
                      <Input id={`crit-weight-${idx}`} type="number" step="0.05" min="0.01" value={crit.weight}
                        onChange={(e) => updateCriterion(idx, (c) => { c.weight = Number(e.target.value); })} />
                    </div>
                  </div>
                  <div>
                    <Label htmlFor={`crit-desc-${idx}`}>Description</Label>
                    <Input id={`crit-desc-${idx}`} value={crit.description ?? ""} onChange={(e) => updateCriterion(idx, (c) => { c.description = e.target.value; })} />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                    <div>
                      <Label>Scale type</Label>
                      <NativeSelect
                        value={crit.scoring_scale.type}
                        onChange={(e) => {
                          const t = e.target.value as "binary" | "likert";
                          updateCriterion(idx, (c) => {
                            c.scoring_scale = t === "binary" ? { type: "binary", min: 0, max: 1 } : { type: "likert", min: 0, max: 4 };
                            c.pass_threshold = t === "binary" ? 1 : 2;
                          });
                        }}
                      >
                        <option value="binary">binary (0/1)</option>
                        <option value="likert">likert (0..N)</option>
                      </NativeSelect>
                    </div>
                    <div>
                      <Label>Scale min</Label>
                      <Input type="number" value={crit.scoring_scale.min ?? 0}
                        onChange={(e) => updateCriterion(idx, (c) => { c.scoring_scale.min = Number(e.target.value); })} />
                    </div>
                    <div>
                      <Label>Scale max</Label>
                      <Input type="number" value={crit.scoring_scale.max ?? 1}
                        onChange={(e) => updateCriterion(idx, (c) => { c.scoring_scale.max = Number(e.target.value); })} />
                    </div>
                    <div>
                      <Label>Pass threshold (on scale)</Label>
                      <Input type="number" value={crit.pass_threshold}
                        onChange={(e) => updateCriterion(idx, (c) => { c.pass_threshold = Number(e.target.value); })} />
                    </div>
                  </div>

                  {/* Checks */}
                  <div>
                    <Label>Automatic checks ({crit.checks.length})</Label>
                    <div className="space-y-2">
                      {crit.checks.map((check, ci) => (
                        <div key={ci} className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-base-panel/40 p-2.5">
                          <NativeSelect
                            aria-label={`Check ${ci + 1} type`}
                            className="h-8 w-48 text-xs"
                            value={check.type}
                            onChange={(e) => updateCriterion(idx, (c) => { c.checks[ci].type = e.target.value; })}
                          >
                            {CHECK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                          </NativeSelect>
                          <Input
                            aria-label={`Check ${ci + 1} params JSON`}
                            className="h-8 flex-1 font-mono text-xs"
                            value={JSON.stringify(check.params ?? {})}
                            onChange={(e) => {
                              try {
                                const params = JSON.parse(e.target.value || "{}");
                                updateCriterion(idx, (c) => { c.checks[ci].params = params; });
                              } catch { /* keep typing; validate catches it */ }
                            }}
                          />
                          <NativeSelect
                            aria-label={`Check ${ci + 1} severity`}
                            className="h-8 w-28 text-xs"
                            value={check.severity ?? "medium"}
                            onChange={(e) => updateCriterion(idx, (c) => { c.checks[ci].severity = e.target.value; })}
                          >
                            <option value="low">low</option>
                            <option value="medium">medium</option>
                            <option value="high">high</option>
                            <option value="critical">critical</option>
                          </NativeSelect>
                          <Button variant="ghost" size="icon" aria-label={`Remove check ${ci + 1}`} className="text-danger hover:text-danger"
                            onClick={() => updateCriterion(idx, (c) => { c.checks.splice(ci, 1); })}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                          <div className="w-full text-[10px] text-fg-muted/70">params e.g. {CHECK_PARAM_HINTS[check.type] ?? "{}"}</div>
                        </div>
                      ))}
                    </div>
                    <Button variant="outline" size="sm" className="mt-2"
                      onClick={() => updateCriterion(idx, (c) => { c.checks.push({ type: "completeness", params: {} } as CheckDefinition); })}>
                      <Plus className="h-3.5 w-3.5" /> Add check
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}

            <Button variant="secondary" onClick={() => update((r) => r.criteria.push(emptyCriterion(r.criteria.length)))}>
              <Plus className="h-4 w-4" /> Add criterion
            </Button>

            <Card>
              <CardHeader>
                <CardTitle>Evaluation form (what testers fill in)</CardTitle>
                <CardDescription>
                  Structured fields rendered dynamically in the tester workspace: yes/no, single/multi-select,
                  numeric ratings, likert scales, free text and evidence lists — with conditional questions.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {(rubric.form?.fields ?? []).map((f, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-base-panel/40 p-2.5">
                    <NativeSelect
                      aria-label={`Form field ${i + 1} type`} className="h-8 w-40 text-xs"
                      value={f.type}
                      onChange={(e) => update((r) => {
                        const fields = (r.form ??= { fields: [] }).fields;
                        fields[i] = { ...fields[i], type: e.target.value as typeof f.type } as typeof f;
                      })}
                    >
                      <option value="yes_no">yes/no</option>
                      <option value="single_select">single select</option>
                      <option value="multi_select">multi select</option>
                      <option value="numeric">numeric</option>
                      <option value="likert">likert</option>
                      <option value="text">free text</option>
                      <option value="evidence">evidence list</option>
                    </NativeSelect>
                    <Input aria-label={`Form field ${i + 1} label`} className="h-8 flex-1 text-xs" value={f.label}
                      placeholder="Question shown to the tester"
                      onChange={(e) => update((r) => {
                        const fields = (r.form ??= { fields: [] }).fields;
                        fields[i] = { ...fields[i], label: e.target.value } as typeof f;
                      })} />
                    <label className="flex items-center gap-1.5 text-xs text-fg-muted">
                      <input type="checkbox" className="h-3.5 w-3.5 accent-[#16B8A6]" checked={!!f.required}
                        onChange={(e) => update((r) => {
                          const fields = (r.form ??= { fields: [] }).fields;
                          fields[i] = { ...fields[i], required: e.target.checked } as typeof f;
                        })} />
                      required
                    </label>
                    <Button variant="ghost" size="icon" aria-label={`Remove form field ${i + 1}`}
                      className="text-danger hover:text-danger"
                      onClick={() => update((r) => { (r.form ??= { fields: [] }).fields.splice(i, 1); })}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                    <div className="w-full text-[10px] text-fg-muted/70">
                      id: {f.id || "(auto)"}{f.options ? ` · options: ${JSON.stringify(f.options)}` : ""}
                      {f.scale ? ` · scale: ${f.scale.min}–${f.scale.max}` : ""}
                      {f.conditional_on ? ` · shown when ${f.conditional_on.field_id} ∈ ${JSON.stringify(f.conditional_on.values)}` : ""}
                    </div>
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button variant="outline" size="sm"
                    onClick={() => update((r) => {
                      const fields = (r.form ??= { fields: [] }).fields;
                      fields.push({ id: `field_${fields.length + 1}`, type: "yes_no", label: "", required: false } as typeof fields[number]);
                    })}>
                    <Plus className="h-3.5 w-3.5" /> Add form field
                  </Button>
                  <span className="self-center text-xs text-fg-muted">
                    For select options, scales and conditional logic, switch to the JSON tab — the form section is
                    <code className="mx-1 font-mono">form.fields</code>.
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Thresholds &amp; policies</CardTitle></CardHeader>
              <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <div>
                  <Label>Passing threshold (0..1)</Label>
                  <Input type="number" step="0.01" min="0" max="1" value={rubric.passing_threshold}
                    onChange={(e) => update((r) => { r.passing_threshold = Number(e.target.value); })} />
                </div>
                <div>
                  <Label>Borderline: confidence below</Label>
                  <Input type="number" step="0.05" min="0" max="1" value={rubric.borderline_rules?.confidence_below ?? 0.6}
                    onChange={(e) => update((r) => { if (r.borderline_rules) r.borderline_rules.confidence_below = Number(e.target.value); })} />
                </div>
                <div>
                  <Label>Borderline: score margin</Label>
                  <Input type="number" step="0.01" min="0" max="0.5" value={rubric.borderline_rules?.score_margin ?? 0.08}
                    onChange={(e) => update((r) => { if (r.borderline_rules) r.borderline_rules.score_margin = Number(e.target.value); })} />
                </div>
                <div>
                  <Label>Review when failed?</Label>
                  <NativeSelect
                    value={String(rubric.human_review_policy?.when_failed ?? false)}
                    onChange={(e) => update((r) => { if (r.human_review_policy) r.human_review_policy.when_failed = e.target.value === "true"; })}
                  >
                    <option value="false">No — borderline only</option>
                    <option value="true">Yes — route all failures</option>
                  </NativeSelect>
                </div>
                <div className="sm:col-span-4 text-xs text-fg-muted">
                  Criteria weights currently sum to <span className={Math.abs(sum - 1) > 0.001 ? "text-warn" : "text-ok"}>{sum.toFixed(3)}</span>
                  {" "}— weights are normalized automatically, but a sum near 1.0 is easier to reason about.
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="json">
          <Textarea
            aria-label="Rubric JSON"
            className="min-h-[480px] text-xs leading-relaxed"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            spellCheck={false}
          />
        </TabsContent>
      </Tabs>

      <div className="mt-6 flex justify-end gap-2">
        <Button variant="outline" onClick={() => navigate("/rubrics")}>Cancel</Button>
        <Button onClick={doCreate} disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create rubric (version 1)"}
        </Button>
      </div>
    </div>
  );
}
