// Client Portal queries/mutations — everything under /api/client (V3).
import { useQuery } from "@tanstack/react-query";
import { api, pageParams } from "@/lib/api";

export interface ClientDashboard {
  organization: { id: number; name: string };
  projects: { total: number; active: number; completed: number; paused: number; draft: number; archived: number };
  tasks: {
    total: number; available: number; in_progress: number; under_review: number;
    approved: number; rejected: number; cancelled: number; completion_rate: number | null;
  };
  requests: { total: number; pending: number; approved: number; rejected: number };
  deliverables: number;
  unread_messages: number;
  recent_activity: { kind: string; project_id: number | null; title: string; detail: string; at: string | null }[];
}

export interface ClientProject {
  id: number; name: string; description: string | null; project_type: string;
  status: string; instructions: string | null; deadline: string | null;
  start_date: string | null; quality_requirements: string | null;
  target_task_volume: number | null;
  tasks: {
    total: number; pending: number; in_progress: number; under_review: number;
    approved: number; rejected: number; completion_rate: number | null;
  };
  datasets: { id: number; name: string; format: string; current_version: number; status: string; created_at: string | null }[];
  deliverables: number;
  source_request_id: number | null;
  recent_activity?: { kind: string; project_id: number | null; title: string; detail: string; at: string | null }[];
}

export interface ClientRequest {
  id: number; title: string; description: string | null; category: string;
  evaluation_types: string[]; expected_task_volume: number | null;
  required_languages: string[]; required_skills: string[];
  dataset_availability: string | null; expected_delivery: string | null;
  quality_requirements: string | null; special_instructions: string | null;
  attachments: { filename: string; size: number }[];
  status: string; admin_response: string | null;
  admin_history: { by: string; role: string; action: string; note?: string; at: string }[];
  converted_project_id: number | null;
  created_at: string | null; updated_at: string | null;
  organization_name?: string; submitted_by_name?: string;
}

export interface ClientMessage {
  id: number; sender_side: "client" | "staff"; sender_name: string;
  body: string; attachment: { name: string } | null; created_at: string | null;
  is_internal?: boolean; read_by_staff?: boolean;
}

export interface ClientDeliverable {
  id: number; project_id: number; project_name: string | null; label: string;
  description: string | null; export_format: string; record_count: number;
  file_size: number; checksum_sha256: string | null; download_count: number;
  published_at: string | null;
}

export const clientQueries = {
  dashboard: () => ({
    queryKey: ["client-dashboard"],
    queryFn: () => api.get<ClientDashboard>("/client/dashboard"),
  }),
  projects: (status?: string) => ({
    queryKey: ["client-projects", status ?? "all"],
    queryFn: () => api.get<ClientProject[]>(`/client/projects${pageParams(1, 100, { status })}`),
  }),
  project: (id: number) => ({
    queryKey: ["client-project", id],
    queryFn: () => api.get<ClientProject>(`/client/projects/${id}`),
  }),
  requests: (status?: string) => ({
    queryKey: ["client-requests", status ?? "all"],
    queryFn: () => api.get<ClientRequest[]>(`/client/requests${pageParams(1, 100, { status })}`),
  }),
  messages: (projectId: number) => ({
    queryKey: ["client-messages", projectId],
    queryFn: () => api.get<ClientMessage[]>(`/client/projects/${projectId}/messages`),
  }),
  deliverables: (projectId?: number) => ({
    queryKey: ["client-deliverables", projectId ?? "all"],
    queryFn: () => api.get<ClientDeliverable[]>(`/client/deliverables${pageParams(1, 100, { project_id: projectId })}`),
  }),
};

export const adminRequestQueries = {
  all: (status?: string) => ({
    queryKey: ["admin-project-requests", status ?? "all"],
    queryFn: () => api.get<ClientRequest[]>(`/admin/project-requests${pageParams(1, 100, { status })}`),
  }),
  messages: (projectId: number) => ({
    queryKey: ["admin-project-messages", projectId],
    queryFn: () => api.get<ClientMessage[]>(`/admin/projects/${projectId}/messages`),
  }),
  deliverables: (projectId: number) => ({
    queryKey: ["admin-project-deliverables", projectId],
    queryFn: () => api.get<ClientDeliverable[]>(`/admin/projects/${projectId}/deliverables`),
  }),
};

export function downloadDeliverable(id: number) {
  // Authenticated blob fetch keeps the Authorization header (direct <a href>
  // would drop it).
  return api.getRawBlob(`/client/deliverables/${id}/download`);
}
