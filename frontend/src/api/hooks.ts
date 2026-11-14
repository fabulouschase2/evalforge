import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api, pageParams } from "@/lib/api";
import type {
  Agreement, AuditLog, Dataset, DatasetRecord, DatasetVersion, EvaluationRun,
  ImportReport, Metrics, Overview, Paginated, Project, QueueItem, ReviewWorkspace,
  ReviewAssignment, Rubric, RubricVersion, User, AppSettings,
} from "@/lib/types";

// Note: ResultDetail is structurally EvaluationResult + findings
import type { EvaluationResult, Finding } from "@/lib/types";
export interface ResultDetail extends EvaluationResult {
  findings: Finding[];
}

export const queries = {
  overview: () => ({
    queryKey: ["overview"],
    queryFn: () => api.get<Overview>("/analytics/overview"),
  }),
  metrics: (runId?: number) => ({
    queryKey: ["metrics", runId ?? "all"],
    queryFn: () => api.get<Metrics>(`/analytics/metrics${runId ? `?run_id=${runId}` : ""}`),
  }),
  agreement: (runId?: number) => ({
    queryKey: ["agreement", runId ?? "all"],
    queryFn: () => api.get<Agreement>(`/analytics/agreement${runId ? `?run_id=${runId}` : ""}`),
  }),
  confusionMatrix: (runId?: number) => ({
    queryKey: ["confusion", runId ?? "all"],
    queryFn: () => api.get<{ labels: string[]; matrix: number[][]; gold_total: number; reason: string | null }>(
      `/analytics/confusion-matrix${runId ? `?run_id=${runId}` : ""}`,
    ),
  }),
  projects: () => ({
    queryKey: ["projects"],
    queryFn: () => api.get<Project[]>("/projects"),
  }),
  datasets: () => ({
    queryKey: ["datasets"],
    queryFn: () => api.get<Dataset[]>("/datasets"),
  }),
  dataset: (id: number) => ({
    queryKey: ["dataset", id],
    queryFn: () => api.get<Dataset>(`/datasets/${id}`),
  }),
  datasetVersions: (id: number) => ({
    queryKey: ["dataset-versions", id],
    queryFn: () => api.get<DatasetVersion[]>(`/datasets/${id}/versions`),
  }),
  datasetRecords: (id: number, versionId: number | undefined, page: number, pageSize: number) => ({
    queryKey: ["dataset-records", id, versionId ?? "current", page, pageSize],
    queryFn: () => api.get<Paginated<DatasetRecord>>(
      `/datasets/${id}/records${pageParams(page, pageSize, { version_id: versionId })}`,
    ),
  }),
  rubrics: () => ({
    queryKey: ["rubrics"],
    queryFn: () => api.get<Rubric[]>("/rubrics"),
  }),
  rubric: (id: number) => ({
    queryKey: ["rubric", id],
    queryFn: () => api.get<Rubric>(`/rubrics/${id}`),
  }),
  rubricVersions: (id: number) => ({
    queryKey: ["rubric-versions", id],
    queryFn: () => api.get<RubricVersion[]>(`/rubrics/${id}/versions`),
  }),
  evaluations: () => ({
    queryKey: ["evaluations"],
    queryFn: () => api.get<EvaluationRun[]>("/evaluations"),
  }),
  evaluation: (id: number) => ({
    queryKey: ["evaluation", id],
    queryFn: () => api.get<EvaluationRun>(`/evaluations/${id}`),
  }),
  results: (runId: number, page: number, filters: { status?: string; needs_review?: boolean }) => ({
    queryKey: ["results", runId, page, filters.status ?? "all", filters.needs_review ?? "all"],
    queryFn: () =>
      api.get<Paginated<EvaluationResult>>(
        `/evaluations/${runId}/results${pageParams(page, 25, filters)}`,
      ),
  }),
  result: (runId: number, resultId: number) => ({
    queryKey: ["result", runId, resultId],
    queryFn: () => api.get<ResultDetail>(`/evaluations/${runId}/results/${resultId}`),
  }),
  users: () => ({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/auth/users"),
  }),
  reviewQueue: () => ({
    queryKey: ["review-queue"],
    queryFn: () => api.get<{ items: QueueItem[]; total: number }>("/reviews/queue"),
  }),
  reviewWorkspace: (assignmentId: number) => ({
    queryKey: ["review-workspace", assignmentId],
    queryFn: () => api.get<ReviewWorkspace>(`/reviews/${assignmentId}`),
  }),
  assignments: () => ({
    queryKey: ["assignments"],
    queryFn: () => api.get<ReviewAssignment[]>("/reviews/assignments"),
  }),
  auditLogs: (page: number, filters: { action?: string; entity_type?: string }) => ({
    queryKey: ["audit-logs", page, filters.action ?? "", filters.entity_type ?? ""],
    queryFn: () => api.get<Paginated<AuditLog>>(`/audit-logs${pageParams(page, 50, filters)}`),
  }),
  settings: () => ({
    queryKey: ["settings"],
    queryFn: () => api.get<AppSettings>("/settings"),
  }),
};

export function useDemoLoader(onSuccess: (data: Record<string, unknown>) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Record<string, unknown>>("/demo/load"),
    onSuccess: (data) => {
      qc.invalidateQueries();
      onSuccess(data);
    },
  });
}

export function useImportPreview(datasetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { file: File; columnMapping?: Record<string, string>; recordIdColumn?: string; expectedLabelColumn?: string }) => {
      const form = new FormData();
      form.append("file", args.file);
      if (args.columnMapping) form.append("column_mapping", JSON.stringify(args.columnMapping));
      if (args.recordIdColumn) form.append("record_id_column", args.recordIdColumn);
      if (args.expectedLabelColumn) form.append("expected_label_column", args.expectedLabelColumn);
      return api.upload<ImportReport>(`/datasets/${datasetId}/upload/preview`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audit-logs"] }),
  });
}

export function useImportCommit(datasetId: number, onDone: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { file: File; columnMapping?: Record<string, string>; recordIdColumn?: string; expectedLabelColumn?: string; notes?: string }) => {
      const form = new FormData();
      form.append("file", args.file);
      if (args.columnMapping) form.append("column_mapping", JSON.stringify(args.columnMapping));
      if (args.recordIdColumn) form.append("record_id_column", args.recordIdColumn);
      if (args.expectedLabelColumn) form.append("expected_label_column", args.expectedLabelColumn);
      if (args.notes) form.append("notes", args.notes);
      return api.upload<DatasetVersion>(`/datasets/${datasetId}/upload/commit`, form);
    },
    onSuccess: () => {
      qc.invalidateQueries();
      onDone();
    },
  });
}
