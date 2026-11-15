import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { ToastProvider } from "@/components/ui/toast";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, TableSkeleton } from "@/components/ui/states";

// V3.1 performance: route-level code splitting. Every page is lazy-loaded so
// the initial bundle only contains the app shell, auth and the login route.
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const RegisterPage = lazy(() => import("@/pages/RegisterPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const ProjectsPage = lazy(() => import("@/pages/ProjectsPage"));
const ProjectDetailPage = lazy(() => import("@/pages/admin/ProjectDetailPage"));
const DatasetsPage = lazy(() => import("@/pages/DatasetsPage"));
const DatasetDetailPage = lazy(() => import("@/pages/DatasetDetailPage"));
const DataCollectionPage = lazy(() => import("@/pages/admin/DataCollectionPage"));
const TasksAdminPage = lazy(() => import("@/pages/admin/TasksAdminPage"));
const WorkersPage = lazy(() => import("@/pages/admin/WorkersPage"));
const RubricsPage = lazy(() => import("@/pages/RubricsPage"));
const RubricNewPage = lazy(() => import("@/pages/RubricNewPage"));
const RubricDetailPage = lazy(() => import("@/pages/RubricDetailPage"));
const EvaluationsPage = lazy(() => import("@/pages/EvaluationsPage"));
const EvaluationDetailPage = lazy(() => import("@/pages/EvaluationDetailPage"));
const ReviewsPage = lazy(() => import("@/pages/ReviewsPage"));
const ReviewDetailPage = lazy(() => import("@/pages/ReviewDetailPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const AuditLogsPage = lazy(() => import("@/pages/AuditLogsPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const OrganizationsPage = lazy(() => import("@/pages/OrganizationsPage"));
const ProjectRequestsPage = lazy(() => import("@/pages/admin/ProjectRequestsPage"));
const ProjectClientPage = lazy(() => import("@/pages/admin/ProjectClientPage"));
const GoldenTasksPage = lazy(() => import("@/pages/admin/GoldenTasksPage"));
const GoldenMonitoringPage = lazy(() => import("@/pages/quality/GoldenMonitoringPage"));
const QualificationsPage = lazy(() => import("@/pages/admin/QualificationsPage"));
const QualificationGradingPage = lazy(() => import("@/pages/quality/QualificationGradingPage"));
const MyQualificationsPage = lazy(() => import("@/pages/tester/MyQualificationsPage"));
const MultimodalPage = lazy(() => import("@/pages/admin/MultimodalPage"));
const IntegrationsPage = lazy(() => import("@/pages/admin/IntegrationsPage"));
const ClientDashboard = lazy(() => import("@/pages/client/ClientDashboard"));
const ClientRequests = lazy(() => import("@/pages/client/ClientRequests"));
const ClientProjects = lazy(() => import("@/pages/client/ClientProjects"));
const ClientDatasets = lazy(() => import("@/pages/client/ClientDatasets"));
const ClientMessages = lazy(() => import("@/pages/client/ClientMessages"));
const ClientDeliverables = lazy(() => import("@/pages/client/ClientDeliverables"));
const TaskMarketplacePage = lazy(() => import("@/pages/tester/TaskMarketplacePage"));
const MyTasksPage = lazy(() => import("@/pages/tester/MyTasksPage"));
const TaskWorkspacePage = lazy(() => import("@/pages/tester/TaskWorkspacePage"));
const SubmissionsPage = lazy(() => import("@/pages/tester/SubmissionsPage"));
const ReviewQueuePage = lazy(() => import("@/pages/reviewer/ReviewQueuePage"));
const SubmissionReviewPage = lazy(() => import("@/pages/reviewer/SubmissionReviewPage"));
const QualityPagesModule = () => import("@/pages/quality/QualityPages");
const AdjudicationQueuePage = lazy(() => QualityPagesModule().then((m) => ({ default: m.AdjudicationQueuePage })));
const ReviewerPerformancePage = lazy(() => QualityPagesModule().then((m) => ({ default: m.ReviewerPerformancePage })));
const TesterPerformancePage = lazy(() => QualityPagesModule().then((m) => ({ default: m.TesterPerformancePage })));
const AgreementAnalysisPage = lazy(() => QualityPagesModule().then((m) => ({ default: m.AgreementAnalysisPage })));
const NotificationsPage = lazy(() => import("@/pages/NotificationsPage"));
const ProfilePage = lazy(() => import("@/pages/ProfilePage"));

import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
  },
});

function RouteFallback() {
  return (
    <div className="p-6">
      <TableSkeleton rows={6} cols={4} />
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

class DebugErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto mt-16 max-w-2xl rounded-lg border border-danger/40 bg-[rgba(239,68,68,0.06)] p-6">
          <h2 className="text-lg font-bold text-danger">Something went wrong</h2>
          <p className="mt-2 text-sm text-fg-muted">
            The interface hit an unexpected error. Reload the page to continue; the incident is
            recorded in the browser console.
          </p>
          <pre className="mt-3 overflow-auto rounded-md border border-border bg-base-card p-3 font-mono text-xs text-fg-muted scroll-thin">
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 rounded-md bg-teal px-4 py-2 text-sm font-semibold text-[#0B1518] hover:bg-teal/90"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function RequireRoles({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!roles.includes(user?.role ?? "")) {
    return (
      <EmptyState
        title="This area is not part of your workspace"
        description={`Your role (${user?.role}) does not have access to this page. The attempt is enforced server-side as well.`}
      />
    );
  }
  return <>{children}</>;
}

const STAFF = ["super_admin", "project_admin", "project_manager"];
const ADMIN = ["super_admin", "project_admin"];
const TESTER = ["tester"];
const REVIEWERS = ["reviewer", "senior_reviewer", "super_admin", "project_admin"];
const QUALITY = ["senior_reviewer", "super_admin"];
const CLIENT = ["client_owner", "client_project_manager", "client_viewer"];
const STAFF_OR_CLIENT = [...STAFF, ...CLIENT];

function App() {
  const { token } = useAuth();
  return (
    <DebugErrorBoundary>
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
      <Route path="/register" element={token ? <Navigate to="/dashboard" replace /> : <RegisterPage />} />

      <Route path="/dashboard" element={<RequireAuth><DashboardPage /></RequireAuth>} />
      <Route path="/notifications" element={<RequireAuth><NotificationsPage /></RequireAuth>} />
      <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />

      {/* Admin / staff */}
      <Route path="/projects" element={<RequireAuth><RequireRoles roles={STAFF}><ProjectsPage /></RequireRoles></RequireAuth>} />
      <Route path="/projects/:id" element={<RequireAuth><RequireRoles roles={STAFF}><ProjectDetailPage /></RequireRoles></RequireAuth>} />
      <Route path="/data-collection" element={<RequireAuth><RequireRoles roles={STAFF}><DataCollectionPage /></RequireRoles></RequireAuth>} />
      <Route path="/tasks" element={<RequireAuth><RequireRoles roles={STAFF}><TasksAdminPage /></RequireRoles></RequireAuth>} />
      <Route path="/workers" element={<RequireAuth><RequireRoles roles={STAFF}><WorkersPage /></RequireRoles></RequireAuth>} />
      <Route path="/rubrics" element={<RequireAuth><RequireRoles roles={STAFF}><RubricsPage /></RequireRoles></RequireAuth>} />
      <Route path="/rubrics/new" element={<RequireAuth><RequireRoles roles={STAFF}><RubricNewPage /></RequireRoles></RequireAuth>} />
      <Route path="/rubrics/:id" element={<RequireAuth><RequireRoles roles={STAFF}><RubricDetailPage /></RequireRoles></RequireAuth>} />
      <Route path="/evaluations" element={<RequireAuth><RequireRoles roles={STAFF}><EvaluationsPage /></RequireRoles></RequireAuth>} />
      <Route path="/evaluations/:id" element={<RequireAuth><RequireRoles roles={STAFF}><EvaluationDetailPage /></RequireRoles></RequireAuth>} />
      <Route path="/reviews" element={<RequireAuth><RequireRoles roles={STAFF}><ReviewsPage /></RequireRoles></RequireAuth>} />
      <Route path="/reviews/:id" element={<RequireAuth><RequireRoles roles={STAFF}><ReviewDetailPage /></RequireRoles></RequireAuth>} />
      <Route path="/analytics" element={<RequireAuth><RequireRoles roles={STAFF}><AnalyticsPage /></RequireRoles></RequireAuth>} />
      <Route path="/audit-logs" element={<RequireAuth><RequireRoles roles={ADMIN}><AuditLogsPage /></RequireRoles></RequireAuth>} />
      <Route path="/settings" element={<RequireAuth><RequireRoles roles={ADMIN}><SettingsPage /></RequireRoles></RequireAuth>} />
      <Route path="/datasets" element={<RequireAuth><RequireRoles roles={STAFF}><DatasetsPage /></RequireRoles></RequireAuth>} />
      <Route path="/datasets/:id" element={<RequireAuth><RequireRoles roles={STAFF}><DatasetDetailPage /></RequireRoles></RequireAuth>} />
      <Route path="/organizations" element={<RequireAuth><RequireRoles roles={STAFF_OR_CLIENT}><OrganizationsPage /></RequireRoles></RequireAuth>} />
      <Route path="/golden-tasks" element={<RequireAuth><RequireRoles roles={STAFF}><GoldenTasksPage /></RequireRoles></RequireAuth>} />
      <Route path="/quality/golden" element={<RequireAuth><RequireRoles roles={QUALITY}><GoldenMonitoringPage /></RequireRoles></RequireAuth>} />
      <Route path="/qualifications" element={<RequireAuth><RequireRoles roles={STAFF}><QualificationsPage /></RequireRoles></RequireAuth>} />
      <Route path="/quality/qualifications" element={<RequireAuth><RequireRoles roles={[...QUALITY, ...STAFF]}><QualificationGradingPage /></RequireRoles></RequireAuth>} />
      <Route path="/my-qualifications" element={<RequireAuth><RequireRoles roles={TESTER}><MyQualificationsPage /></RequireRoles></RequireAuth>} />
      <Route path="/multimodal" element={<RequireAuth><RequireRoles roles={STAFF}><MultimodalPage /></RequireRoles></RequireAuth>} />
      <Route path="/integrations" element={<RequireAuth><RequireRoles roles={ADMIN}><IntegrationsPage /></RequireRoles></RequireAuth>} />

      {/* Admin: client portal management */}
      <Route path="/client-requests" element={<RequireAuth><RequireRoles roles={STAFF}><ProjectRequestsPage /></RequireRoles></RequireAuth>} />
      <Route path="/projects/:id/client" element={<RequireAuth><RequireRoles roles={STAFF}><ProjectClientPage /></RequireRoles></RequireAuth>} />

      {/* Client portal */}
      <Route path="/client" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientDashboard /></RequireRoles></RequireAuth>} />
      <Route path="/client/requests" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientRequests /></RequireRoles></RequireAuth>} />
      <Route path="/client/projects" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientProjects /></RequireRoles></RequireAuth>} />
      <Route path="/client/datasets" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientDatasets /></RequireRoles></RequireAuth>} />
      <Route path="/client/messages" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientMessages /></RequireRoles></RequireAuth>} />
      <Route path="/client/deliverables" element={<RequireAuth><RequireRoles roles={CLIENT}><ClientDeliverables /></RequireRoles></RequireAuth>} />

      {/* Tester */}
      <Route path="/tasks/available" element={<RequireAuth><RequireRoles roles={TESTER}><TaskMarketplacePage /></RequireRoles></RequireAuth>} />
      <Route path="/tasks/mine" element={<RequireAuth><RequireRoles roles={TESTER}><MyTasksPage /></RequireRoles></RequireAuth>} />
      <Route path="/tasks/:id" element={<RequireAuth><RequireRoles roles={TESTER}><DebugErrorBoundary><TaskWorkspacePage /></DebugErrorBoundary></RequireRoles></RequireAuth>} />
      <Route path="/submissions" element={<RequireAuth><RequireRoles roles={[...TESTER, ...REVIEWERS, ...STAFF]}><SubmissionsPage /></RequireRoles></RequireAuth>} />

      {/* Reviewer */}
      <Route path="/review-queue" element={<RequireAuth><RequireRoles roles={REVIEWERS}><ReviewQueuePage /></RequireRoles></RequireAuth>} />
      <Route path="/review-queue/:id" element={<RequireAuth><RequireRoles roles={REVIEWERS}><SubmissionReviewPage /></RequireRoles></RequireAuth>} />

      {/* Quality lead */}
      <Route path="/quality/adjudication" element={<RequireAuth><RequireRoles roles={QUALITY}><AdjudicationQueuePage /></RequireRoles></RequireAuth>} />
      <Route path="/quality/reviewers" element={<RequireAuth><RequireRoles roles={QUALITY}><ReviewerPerformancePage /></RequireRoles></RequireAuth>} />
      <Route path="/quality/testers" element={<RequireAuth><RequireRoles roles={QUALITY}><TesterPerformancePage /></RequireRoles></RequireAuth>} />
      <Route path="/quality/agreement" element={<RequireAuth><RequireRoles roles={QUALITY}><AgreementAnalysisPage /></RequireRoles></RequireAuth>} />

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
    </Suspense>
    </DebugErrorBoundary>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
