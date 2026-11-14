// Admin overview: platform stats, charts and performance tables (live data only).
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  FolderKanban, Database, ListChecks, Clock, CheckCircle2, XCircle,
  AlertTriangle, Users, Gauge, Loader2, Building2, Target, Bell, Inbox, Award,
} from "lucide-react";
import {
  BarChart, Bar, CartesianGrid, Cell, Legend, Line, LineChart,
  PieChart, Pie, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { v2queries } from "@/api/v2hooks";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { NativeSelect } from "@/components/ui/input";
import { TASK_STATUS_LABELS } from "@/lib/roles";
import { fmtPct } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  draft: "#64748B", available: "#60A5FA", assigned: "#818CF8", in_progress: "#A78BFA",
  submitted: "#F59E0B", under_review: "#FBBF24", revision_required: "#FB923C",
  approved: "#22C55E", rejected: "#EF4444", cancelled: "#475569",
};

function StatCard({ icon: Icon, label, value, sub, to, tone }: {
  icon: React.ComponentType<{ className?: string }>; label: string; value: string | number;
  sub?: string; to?: string; tone?: string;
}) {
  const inner = (
    <Card className="h-full transition-colors hover:border-teal/40">
      <CardContent className="flex items-start gap-3 p-4">
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${tone ?? "bg-teal-soft text-teal"}`}>
          <Icon className="h-4.5 w-4.5" />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-fg-muted">{label}</div>
          <div className="mt-0.5 text-xl font-bold text-fg">{value}</div>
          {sub && <div className="mt-0.5 truncate text-[11px] text-fg-muted">{sub}</div>}
        </div>
      </CardContent>
    </Card>
  );
  return to ? <Link to={to}>{inner}</Link> : inner;
}

export default function AdminOverview() {
  const { data, isLoading, isError, error, refetch } = useQuery(v2queries.adminOverview());
  const platform = useQuery({
    queryKey: ["platform-analytics"],
    queryFn: () => api.get<{
      organizations: number; people: { workers: number; reviewers: number; client_users: number };
      quality: { golden_attempts: number; golden_accuracy: number | null; open_alerts: number; qualifications_passed: number };
      client_requests: { pending: number };
    }>("/analytics/platform"),
  });
  const [days, setDays] = useState("14");

  if (isLoading) return <TableSkeleton rows={6} cols={4} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;

  const o = data!;
  const statusData = Object.entries(o.tasks_by_status)
    .filter(([, v]) => v > 0)
    .map(([name, count]) => ({ name: TASK_STATUS_LABELS[name] ?? name, count, key: name }));
  const progressData = o.project_progress.map((p) => ({
    name: p.name.length > 18 ? p.name.slice(0, 17) + "…" : p.name,
    total: p.total_tasks, approved: p.approved,
  }));
  const dailyData = o.daily_submissions.map((d) => ({
    day: d.day.slice(5), count: d.count,
  }));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Administration overview</h1>
          <p className="mt-1 text-sm text-fg-muted">
            All values are live backend measurements — nothing here is estimated or demo data.
          </p>
        </div>
        <NativeSelect aria-label="Chart window" className="w-40" value={days}
          onChange={(e) => { setDays(e.target.value); void 0; }}>
          <option value="14">Last 14 days</option>
          <option value="30">Last 30 days</option>
          <option value="7">Last 7 days</option>
        </NativeSelect>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        <StatCard icon={FolderKanban} label="Projects" value={o.total_projects}
          sub={`${o.active_projects} active`} to="/projects" />
        <StatCard icon={Database} label="Records collected" value={o.total_records}
          sub={`${o.total_datasets} datasets`} to="/data-collection"
          tone="bg-[rgba(96,165,250,0.12)] text-info" />
        <StatCard icon={ListChecks} label="Tasks created" value={o.task_total}
          sub={`${o.tasks_by_status.available} awaiting assignment`} to="/tasks"
          tone="bg-[rgba(167,139,250,0.12)] text-[#A78BFA]" />
        <StatCard icon={Clock} label="Avg completion" value={o.avg_completion_hours !== null ? `${o.avg_completion_hours}h` : "—"}
          sub={`${o.completion_samples} timed samples`} tone="bg-[rgba(96,165,250,0.12)] text-info" />
        <StatCard icon={CheckCircle2} label="Approved" value={o.tasks_by_status.approved}
          sub={`${fmtPct(o.overall_quality_score)} quality score`} to="/tasks"
          tone="bg-[rgba(34,197,94,0.12)] text-ok" />
        <StatCard icon={XCircle} label="Rejected" value={o.tasks_by_status.rejected}
          sub={`${o.tasks_by_status.revision_required} awaiting revision`} to="/tasks"
          tone="bg-[rgba(239,68,68,0.12)] text-danger" />
      </div>

      {platform.data && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
          <StatCard icon={Building2} label="Organizations" value={platform.data.organizations}
            sub={`${platform.data.people.client_users} client users`} to="/organizations" />
          <StatCard icon={Users} label="Workers" value={platform.data.people.workers}
            sub={`${platform.data.people.reviewers} reviewers`} to="/workers" />
          <StatCard icon={Target} label="Golden accuracy"
            value={platform.data.quality.golden_accuracy !== null ? `${Math.round(platform.data.quality.golden_accuracy * 100)}%` : "—"}
            sub={`${platform.data.quality.golden_attempts} attempts`} to="/quality/golden" />
          <StatCard icon={Bell} label="Open quality alerts" value={platform.data.quality.open_alerts}
            sub="indicators for review" to="/quality/golden" tone="bg-[rgba(245,158,11,0.12)] text-warn" />
          <StatCard icon={Inbox} label="Pending client requests" value={platform.data.client_requests.pending}
            sub="awaiting review" to="/client-requests" />
          <StatCard icon={Award} label="Qualifications passed" value={platform.data.quality.qualifications_passed}
            sub="all assessments" to="/qualifications" />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Daily task submissions</CardTitle>
            <CardDescription>Completed submissions per day (UTC).</CardDescription>
          </CardHeader>
          <CardContent className="h-[240px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyData} margin={{ top: 6, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#34414C" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: "#94A3B8", fontSize: 10 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                <Tooltip contentStyle={{ background: "#18232D", border: "1px solid #34414C", borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="count" name="Submissions" stroke="#16B8A6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Task status distribution</CardTitle>
            <CardDescription>Current lifecycle state of every task.</CardDescription>
          </CardHeader>
          <CardContent className="h-[240px]">
            {statusData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-fg-muted">No tasks yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={statusData} dataKey="count" nameKey="name" innerRadius={45} outerRadius={75} paddingAngle={2}>
                    {statusData.map((s) => <Cell key={s.key} fill={STATUS_COLORS[s.key] ?? "#60A5FA"} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#18232D", border: "1px solid #34414C", borderRadius: 8, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Project completion progress</CardTitle>
            <CardDescription>Total vs approved tasks per project.</CardDescription>
          </CardHeader>
          <CardContent className="h-[240px]">
            {progressData.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-fg-muted">No projects yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={progressData} margin={{ top: 6, right: 8, left: -22, bottom: 14 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#34414C" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: "#94A3B8", fontSize: 9 }} angle={-20} textAnchor="end" height={44} interval={0} />
                  <YAxis allowDecimals={false} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#18232D", border: "1px solid #34414C", borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="total" name="Total tasks" fill="#60A5FA" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="approved" name="Approved" fill="#22C55E" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Users className="h-4 w-4 text-teal" /> Tester performance</CardTitle>
            <CardDescription>Submissions, decisions and approval rate per tester.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {o.tester_performance.length === 0 ? (
              <EmptyState icon={Loader2} title="No tester activity yet"
                description="Once testers submit work their performance appears here." />
            ) : (
              <Table>
                <THead>
                  <TR><TH>Tester</TH><TH>Submitted</TH><TH>Approved</TH><TH>Rejected</TH><TH>Approval rate</TH></TR>
                </THead>
                <TBody>
                  {o.tester_performance.map((t) => (
                    <TR key={t.tester_id}>
                      <TD className="font-medium text-fg">{t.name}</TD>
                      <TD>{t.submitted}</TD>
                      <TD className="text-ok">{t.approved}</TD>
                      <TD className="text-danger">{t.rejected}</TD>
                      <TD>{fmtPct(t.approval_rate)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Gauge className="h-4 w-4 text-teal" /> Reviewer performance</CardTitle>
            <CardDescription>Decision distribution per reviewer.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {o.reviewer_performance.length === 0 ? (
              <EmptyState icon={Loader2} title="No reviews recorded yet" />
            ) : (
              <Table>
                <THead>
                  <TR><TH>Reviewer</TH><TH>Reviews</TH><TH>Approved</TH><TH>Rejected</TH><TH>Revisions</TH></TR>
                </THead>
                <TBody>
                  {o.reviewer_performance.map((r) => (
                    <TR key={r.reviewer_id}>
                      <TD className="font-medium text-fg">{r.name}</TD>
                      <TD>{r.reviews}</TD>
                      <TD className="text-ok">{r.approved}</TD>
                      <TD className="text-danger">{r.rejected}</TD>
                      <TD className="text-warn">{r.revision_requested}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-warn" /> Attention needed</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-fg-muted">Tasks awaiting assignment</div>
            <div className="mt-1 text-2xl font-bold text-warn">{o.tasks_by_status.available}</div>
          </div>
          <div>
            <div className="text-xs text-fg-muted">In progress</div>
            <div className="mt-1 text-2xl font-bold text-info">{o.tasks_by_status.in_progress + o.tasks_by_status.assigned}</div>
          </div>
          <div>
            <div className="text-xs text-fg-muted">Awaiting review</div>
            <div className="mt-1 text-2xl font-bold text-warn">{o.tasks_by_status.submitted + o.tasks_by_status.under_review}</div>
          </div>
          <div>
            <div className="text-xs text-fg-muted">Revision required</div>
            <div className="mt-1 text-2xl font-bold text-danger">{o.tasks_by_status.revision_required}</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
