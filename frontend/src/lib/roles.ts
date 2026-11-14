// Role-based navigation and capability helpers (server still enforces everything).

export type Role =
  | "super_admin" | "project_admin" | "project_manager"
  | "tester" | "reviewer" | "senior_reviewer"
  | "client_owner" | "client_project_manager" | "client_viewer";

export const ROLE_LABELS: Record<Role, string> = {
  super_admin: "Super Admin",
  project_admin: "Project Admin",
  project_manager: "Project Manager",
  tester: "Tester / Annotator",
  reviewer: "Reviewer",
  senior_reviewer: "Senior Reviewer / Quality Lead",
  client_owner: "Client Owner",
  client_project_manager: "Client Project Manager",
  client_viewer: "Client Viewer",
};

export const ROLE_OPTIONS = Object.keys(ROLE_LABELS) as Role[];

export const CLIENT_ROLE_OPTIONS: Role[] = [
  "client_owner", "client_project_manager", "client_viewer",
];

const STAFF: Role[] = ["super_admin", "project_admin", "project_manager"];
const REVIEWERS: Role[] = ["reviewer", "senior_reviewer", "super_admin", "project_admin"];
const CLIENT_ROLES: Role[] = ["client_owner", "client_project_manager", "client_viewer"];

export function isStaff(role: string): boolean {
  return STAFF.includes(role as Role);
}

export function isPlatformAdmin(role: string): boolean {
  return role === "super_admin" || role === "project_admin";
}

export function isTester(role: string): boolean {
  return role === "tester";
}

export function isClientRole(role: string): boolean {
  return CLIENT_ROLES.includes(role as Role);
}

export function canReview(role: string): boolean {
  return REVIEWERS.includes(role as Role);
}

export function canAdjudicate(role: string): boolean {
  return role === "senior_reviewer" || role === "super_admin";
}

export interface NavItem {
  to: string;
  label: string;
}

export function navForRole(role: string): NavItem[] {
  if (isClientRole(role)) {
    // Client portal navigation (V3 Phase 2 fills the workspace pages).
    return [
      { to: "/client", label: "Client Dashboard" },
      { to: "/client/requests", label: "Project Requests" },
      { to: "/client/projects", label: "My Projects" },
      { to: "/client/datasets", label: "Datasets" },
      { to: "/client/messages", label: "Messages" },
      { to: "/client/deliverables", label: "Deliverables" },
      { to: "/organizations", label: "Organization" },
      { to: "/notifications", label: "Notifications" },
      { to: "/profile", label: "Profile" },
    ];
  }
  if (isStaff(role)) {
    const items: NavItem[] = [
      { to: "/dashboard", label: "Overview" },
      { to: "/projects", label: "Projects" },
      { to: "/data-collection", label: "Data Collection" },
      { to: "/tasks", label: "Task Management" },
      { to: "/workers", label: "Workers" },
      { to: "/client-requests", label: "Client Requests" },
      { to: "/organizations", label: "Organizations" },
      { to: "/golden-tasks", label: "Golden Tasks" },
      { to: "/qualifications", label: "Qualifications" },
      { to: "/multimodal", label: "Multimodal Annotation" },
      { to: "/rubrics", label: "Rubric Builder" },
      { to: "/analytics", label: "Analytics" },
    ];
    if (isPlatformAdmin(role)) {
      items.push({ to: "/integrations", label: "API Management" });
      items.push({ to: "/audit-logs", label: "Audit Logs" });
      items.push({ to: "/settings", label: "Settings" });
    }
    items.push({ to: "/notifications", label: "Notifications" });
    items.push({ to: "/profile", label: "Profile" });
    return items;
  }
  if (isTester(role)) {
    return [
      { to: "/dashboard", label: "Overview" },
      { to: "/tasks/available", label: "Available Tasks" },
      { to: "/tasks/mine", label: "My Tasks" },
      { to: "/my-qualifications", label: "Qualifications" },
      { to: "/submissions", label: "Submissions & Feedback" },
      { to: "/notifications", label: "Notifications" },
      { to: "/profile", label: "Profile" },
    ];
  }
  if (role === "senior_reviewer") {
    return [
      { to: "/dashboard", label: "Overview" },
      { to: "/quality/adjudication", label: "Adjudication" },
      { to: "/quality/golden", label: "Golden Task Results" },
      { to: "/quality/qualifications", label: "Qualification Results" },
      { to: "/quality/reviewers", label: "Reviewer Performance" },
      { to: "/quality/testers", label: "Tester Performance" },
      { to: "/quality/agreement", label: "Agreement Analysis" },
      { to: "/notifications", label: "Notifications" },
      { to: "/profile", label: "Profile" },
    ];
  }
  // reviewer
  return [
    { to: "/dashboard", label: "Overview" },
    { to: "/review-queue", label: "Review Queue" },
    { to: "/submissions", label: "Completed Reviews" },
    { to: "/notifications", label: "Notifications" },
    { to: "/profile", label: "Profile" },
  ];
}

export const PROJECT_TYPE_LABELS: Record<string, string> = {
  ai_response_evaluation: "AI response evaluation",
  data_annotation: "Data annotation",
  text_classification: "Text classification",
  factuality_verification: "Factuality verification",
  instruction_following_evaluation: "Instruction-following evaluation",
  coding_evaluation: "Coding evaluation",
  image_annotation: "Image annotation",
  video_annotation: "Video annotation",
  audio_evaluation: "Audio evaluation",
  safety_evaluation: "Safety evaluation",
  custom_evaluation: "Custom evaluation",
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  available: "Available",
  assigned: "Assigned",
  in_progress: "In Progress",
  submitted: "Submitted",
  under_review: "Under Review",
  revision_required: "Revision Required",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
};
