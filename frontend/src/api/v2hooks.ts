// v2 platform queries/mutations (tasks, submissions, quality, notifications, admin).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, pageParams } from "@/lib/api";
import type {
  AdjudicationQueueItem, AdminOverview, AgreementAnalysis, NotificationItem,
  Paginated, PlatformTask, ProjectDetail, ProjectMember, QualityOverview,
  ReviewerConsistency, SubmissionSummary, TaskWorkspace, TesterQuality, User,
} from "@/lib/types";

export const v2queries = {
  adminOverview: () => ({
    queryKey: ["admin-overview"],
    queryFn: () => api.get<AdminOverview>("/analytics/admin-overview"),
  }),
  project: (id: number) => ({
    queryKey: ["v2-project", id],
    queryFn: () => api.get<ProjectDetail>(`/projects/${id}`),
  }),
  members: (projectId: number) => ({
    queryKey: ["members", projectId],
    queryFn: () => api.get<ProjectMember[]>(`/projects/${projectId}/members`),
  }),
  organizations: () => ({
    queryKey: ["organizations"],
    queryFn: () => api.get<{ id: number; name: string }[]>("/organizations"),
  }),
  projectTypes: () => ({
    queryKey: ["project-types"],
    queryFn: () => api.get<{ types: string[]; statuses: string[] }>("/projects/types"),
  }),
  tasks: (page: number, filters: Record<string, string | number | undefined>) => ({
    queryKey: ["tasks", page, filters],
    queryFn: () => api.get<Paginated<PlatformTask>>(`/tasks${pageParams(page, 25, filters)}`),
  }),
  availableTasks: (page: number) => ({
    queryKey: ["tasks-available", page],
    queryFn: () => api.get<Paginated<PlatformTask>>(`/tasks/available${pageParams(page, 20)}`),
  }),
  myTasks: (status: string | undefined) => ({
    queryKey: ["tasks-mine", status ?? "all"],
    queryFn: () => api.get<Paginated<PlatformTask>>(`/tasks/mine${pageParams(1, 100, { status })}`),
  }),
  workspace: (taskId: number) => ({
    queryKey: ["task-workspace", taskId],
    queryFn: () => api.get<TaskWorkspace>(`/submissions/tasks/${taskId}/workspace`),
  }),
  mySubmissions: (status: string | undefined) => ({
    queryKey: ["my-submissions", status ?? "all"],
    queryFn: () => api.get<Paginated<SubmissionSummary>>(`/submissions/mine${pageParams(1, 100, { status })}`),
  }),
  submissions: (page: number, filters: Record<string, string | number | undefined>) => ({
    queryKey: ["submissions", page, filters],
    queryFn: () => api.get<Paginated<SubmissionSummary>>(`/submissions${pageParams(page, 25, filters)}`),
  }),
  submission: (id: number) => ({
    queryKey: ["submission", id],
    queryFn: () => api.get<SubmissionSummary>(`/submissions/${id}`),
  }),
  reviewQueue: (page: number, projectId?: number) => ({
    queryKey: ["review-queue-v2", page, projectId ?? "all"],
    queryFn: () => api.get<Paginated<SubmissionSummary>>(`/submissions/review-queue${pageParams(page, 25, { project_id: projectId })}`),
  }),
  users: () => ({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/auth/users"),
  }),
  notifications: (page: number, unreadOnly: boolean) => ({
    queryKey: ["notifications", page, unreadOnly],
    queryFn: () => api.get<Paginated<NotificationItem>>(`/notifications${pageParams(page, 30, { unread_only: unreadOnly })}`),
  }),
  unreadCount: () => ({
    queryKey: ["notifications-unread"],
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: 30000,
  }),
  qualityOverview: () => ({
    queryKey: ["quality-overview"],
    queryFn: () => api.get<QualityOverview>("/quality/overview"),
  }),
  adjudicationQueue: (page: number) => ({
    queryKey: ["adjudication-queue", page],
    queryFn: () => api.get<Paginated<AdjudicationQueueItem>>(`/quality/adjudication-queue${pageParams(page, 25)}`),
  }),
  reviewerConsistency: () => ({
    queryKey: ["reviewer-consistency"],
    queryFn: () => api.get<ReviewerConsistency>("/quality/reviewer-consistency"),
  }),
  testerQuality: () => ({
    queryKey: ["tester-quality"],
    queryFn: () => api.get<TesterQuality>("/quality/tester-quality"),
  }),
  agreement: () => ({
    queryKey: ["quality-agreement"],
    queryFn: () => api.get<AgreementAnalysis>("/quality/agreement"),
  }),
};

export function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function useTaskMutations(onDone?: () => void) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries();
    onDone?.();
  };
  const post = (path: string, json?: unknown) => api.post(path, json).then(invalidate);

  return {
    claim: (taskId: number) => post(`/tasks/${taskId}/claim`),
    start: (taskId: number) => post(`/tasks/${taskId}/start`),
    assign: (taskId: number, testerId: number) => post(`/tasks/${taskId}/assign`, { tester_id: testerId }),
    reassign: (taskId: number, testerId: number) => post(`/tasks/${taskId}/reassign`, { tester_id: testerId }),
    release: (taskId: number) => post(`/tasks/${taskId}/release`),
    pause: (taskId: number) => post(`/tasks/${taskId}/pause`),
    unpause: (taskId: number) => post(`/tasks/${taskId}/unpause`),
    cancel: (taskId: number) => post(`/tasks/${taskId}/cancel`),
    generate: (payload: unknown) => post("/tasks/generate", payload),
    createManual: (payload: unknown) => post("/tasks/manual", payload),
    bulkManual: (payload: unknown) => post("/tasks/bulk-manual", payload),
    expireAssignments: () => post("/tasks/maintenance/expire-assignments"),
  };
}

export function useSubmissionMutations(onDone?: () => void) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries();
    onDone?.();
  };
  return {
    saveDraft: (taskId: number, payload: unknown) =>
      api.post(`/submissions/tasks/${taskId}/draft`, { payload }).then(() => qc.invalidateQueries({ queryKey: ["task-workspace", taskId] })),
    submit: (taskId: number, body: unknown) =>
      api.post(`/submissions/tasks/${taskId}/submit`, body).then(invalidate),
    claimReview: (submissionId: number) => post(`/submissions/${submissionId}/claim-review`),
    decide: (submissionId: number, body: unknown) => post(`/submissions/${submissionId}/review`, body),
    adjudicate: (submissionId: number, body: unknown) => post(`/quality/submissions/${submissionId}/adjudicate`, body),
    markRead: (id: number) => post(`/notifications/${id}/read`),
    markAllRead: () => post("/notifications/read-all"),
  };
  function post(path: string, json?: unknown) {
    return api.post(path, json).then(invalidate);
  }
}
