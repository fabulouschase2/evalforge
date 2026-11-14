import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, FolderKanban, Database, ClipboardList, PlayCircle,
  UserCheck, BarChart3, ScrollText, Settings as SettingsIcon, ChevronLeft,
  ChevronRight, Bell, LogOut, Shield, ChevronDown, Sparkles,
  ListChecks, Users, HardHat, Scale,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { navForRole, ROLE_LABELS, type Role } from "@/lib/roles";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

const NAV_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "/dashboard": LayoutDashboard,
  "/projects": FolderKanban,
  "/data-collection": Database,
  "/tasks": ListChecks,
  "/tasks/available": ListChecks,
  "/tasks/mine": ListChecks,
  "/workers": Users,
  "/rubrics": ClipboardList,
  "/analytics": BarChart3,
  "/audit-logs": ScrollText,
  "/settings": SettingsIcon,
  "/submissions": CheckSquareIcon,
  "/review-queue": UserCheck,
  "/quality/adjudication": Scale,
  "/quality/reviewers": UserCheck,
  "/quality/testers": HardHat,
  "/quality/agreement": BarChart3,
  "/notifications": Bell,
  "/profile": UserIcon,
};

function CheckSquareIcon({ className }: { className?: string }) {
  return <ClipboardList className={className} />;
}
function UserIcon({ className }: { className?: string }) {
  return <UserCheck className={className} />;
}

const CRUMBS: { match: RegExp; label: string; root?: string; parent?: string }[] = [
  { match: /^\/dashboard/, label: "Overview" },
  { match: /^\/projects\/\d+/, label: "Project detail", root: "/projects", parent: "Projects" },
  { match: /^\/projects/, label: "Projects" },
  { match: /^\/data-collection/, label: "Data Collection" },
  { match: /^\/tasks\/available/, label: "Available Tasks" },
  { match: /^\/tasks\/mine/, label: "My Tasks" },
  { match: /^\/tasks\/\d+/, label: "Task workspace", root: "/tasks/mine", parent: "My Tasks" },
  { match: /^\/tasks/, label: "Task Management" },
  { match: /^\/workers/, label: "Workers" },
  { match: /^\/rubrics\/new/, label: "New rubric", root: "/rubrics", parent: "Rubric Builder" },
  { match: /^\/rubrics\/\d+/, label: "Rubric detail", root: "/rubrics", parent: "Rubric Builder" },
  { match: /^\/rubrics/, label: "Rubric Builder" },
  { match: /^\/submissions\/\d+/, label: "Submission detail", root: "/submissions", parent: "Submissions" },
  { match: /^\/submissions/, label: "Submissions" },
  { match: /^\/review-queue\/\d+/, label: "Review interface", root: "/review-queue", parent: "Review Queue" },
  { match: /^\/review-queue/, label: "Review Queue" },
  { match: /^\/quality\/adjudication/, label: "Adjudication" },
  { match: /^\/quality\/reviewers/, label: "Reviewer Performance" },
  { match: /^\/quality\/testers/, label: "Tester Performance" },
  { match: /^\/quality\/agreement/, label: "Agreement Analysis" },
  { match: /^\/datasets\/\d+/, label: "Dataset detail", root: "/data-collection", parent: "Data Collection" },
  { match: /^\/datasets/, label: "Datasets" },
  { match: /^\/evaluations\/\d+/, label: "Evaluation detail", root: "/evaluations", parent: "Evaluations" },
  { match: /^\/evaluations/, label: "Evaluations" },
  { match: /^\/reviews\/\d+/, label: "Automated review", root: "/reviews", parent: "Automated Reviews" },
  { match: /^\/reviews/, label: "Automated Reviews" },
  { match: /^\/analytics/, label: "Analytics" },
  { match: /^\/audit-logs/, label: "Audit Logs" },
  { match: /^\/settings/, label: "Settings" },
  { match: /^\/notifications/, label: "Notifications" },
  { match: /^\/profile/, label: "Profile" },
];

function Breadcrumbs() {
  const location = useLocation();
  const crumb = CRUMBS.find((c) => c.match.test(location.pathname));
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm">
      {crumb?.root && crumb.parent && (
        <>
          <NavLink to={crumb.root} className="text-fg-muted hover:text-fg transition-colors">
            {crumb.parent}
          </NavLink>
          <span className="text-fg-muted/50">/</span>
        </>
      )}
      <span className="font-medium text-fg">{crumb?.label ?? "EvalForge"}</span>
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const role = user?.role ?? "tester";

  const nav = navForRole(role);
  const { data: unread } = useQuery({
    queryKey: ["notifications-unread"],
    queryFn: () => api.get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: 30000,
  });
  const pendingCount = unread?.unread ?? 0;

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-base-sidebar transition-[width] duration-200",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-teal">
            <Shield className="h-4.5 w-4.5 text-[#0B1518]" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-sm font-bold text-fg">EvalForge AI</div>
              <div className="truncate text-[10px] uppercase tracking-wider text-fg-muted">
                {ROLE_LABELS[role as Role] ?? role} workspace
              </div>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto scroll-thin p-2" aria-label="Main navigation">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/dashboard"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive ? "bg-teal-soft text-teal" : "text-fg-muted hover:bg-base-panel hover:text-fg",
                )
              }
              title={item.label}
            >
              {(() => {
                const Icon = NAV_ICONS[item.to] ?? ListChecks;
                return <Icon className="h-4.5 w-4.5 shrink-0" />;
              })()}
              {!collapsed && <span>{item.label}</span>}
              {!collapsed && item.to === "/notifications" && pendingCount > 0 && (
                <span className="ml-auto rounded-full bg-warn/15 px-1.5 py-0.5 text-[10px] font-bold text-warn">
                  {pendingCount}
                </span>
              )}
              {collapsed && pendingCount > 0 && item.to === "/notifications" && (
                <span className="absolute left-9 top-1.5 h-2 w-2 rounded-full bg-warn" />
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-border p-2">
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-fg-muted hover:bg-base-panel hover:text-fg"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>

      <div className={cn("flex min-h-screen flex-1 flex-col transition-[padding] duration-200", collapsed ? "pl-16" : "pl-60")}>
        <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-border bg-base-bg/95 px-5 backdrop-blur">
          <Breadcrumbs />
          <div className="ml-auto flex items-center gap-3">
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button className="hidden items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs text-fg-muted hover:bg-base-panel md:flex" type="button">
                  <Sparkles className="h-3.5 w-3.5 text-teal" />
                  <span>Default workspace</span>
                  <ChevronDown className="h-3.5 w-3.5" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content align="end" className="z-50 min-w-[180px] rounded-md border border-border bg-base-card p-1 shadow-xl">
                  <DropdownMenu.Item className="flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm text-fg outline-none hover:bg-base-panel">
                    <Sparkles className="h-3.5 w-3.5 text-teal" /> Default workspace
                    <span className="ml-auto text-[10px] uppercase text-fg-muted">active</span>
                  </DropdownMenu.Item>
                  <DropdownMenu.Item disabled className="rounded px-3 py-2 text-sm text-fg-muted/50 outline-none">
                    + New workspace (coming soon)
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>

            <button
              type="button"
              onClick={() => navigate("/notifications")}
              className="relative rounded-md border border-border p-2 text-fg-muted hover:bg-base-panel hover:text-fg"
              aria-label={`Notifications: ${pendingCount} unread`}
              title="Notifications"
            >
              <Bell className="h-4 w-4" />
              {pendingCount > 0 && (
                <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-warn px-1 text-[10px] font-bold text-[#0B1518]">
                  {pendingCount > 99 ? "99+" : pendingCount}
                </span>
              )}
            </button>

            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button className="flex items-center gap-2.5 rounded-md border border-border py-1 pl-1 pr-3 hover:bg-base-panel" type="button">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-base-panel text-xs font-bold text-teal">
                    {user?.name?.slice(0, 2).toUpperCase() ?? "??"}
                  </span>
                  <span className="hidden text-left sm:block">
                    <span className="block max-w-[140px] truncate text-xs font-semibold text-fg">{user?.name}</span>
                    <span className="block text-[10px] text-fg-muted">{ROLE_LABELS[role as Role] ?? role}</span>
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 text-fg-muted" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content align="end" className="z-50 min-w-[200px] rounded-md border border-border bg-base-card p-1 shadow-xl">
                  <div className="border-b border-border px-3 py-2">
                    <div className="text-sm font-semibold text-fg">{user?.name}</div>
                    <div className="text-xs text-fg-muted">{user?.email}</div>
                  </div>
                  <DropdownMenu.Item className="flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm text-fg outline-none hover:bg-base-panel"
                    onSelect={() => navigate("/profile")}>
                    Profile
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className="flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm text-danger outline-none hover:bg-base-panel"
                    onSelect={() => { logout(); navigate("/login"); }}
                  >
                    <LogOut className="h-3.5 w-3.5" /> Sign out
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
        </header>

        <main className="flex-1 px-5 py-6">
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
