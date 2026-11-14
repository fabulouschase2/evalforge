// Quality lead overview: disagreement monitoring, pending adjudications, quick links.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Scale, Flag, EyeOff, GitBranch, Inbox } from "lucide-react";
import { v2queries } from "@/api/v2hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { fmtPct } from "@/lib/utils";

export default function QualityOverview() {
  const { data, isLoading, isError, error, refetch } = useQuery(v2queries.qualityOverview());

  if (isLoading) return <TableSkeleton rows={5} cols={4} />;
  if (isError) return <ErrorState message={(error as Error)?.message} retry={refetch} />;

  const o = data!;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-fg">Quality monitoring</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Disagreement tracking, adjudication backlog and quality signals across all projects.
          </p>
        </div>
        <Link to="/quality/adjudication"><Button><Scale className="h-4 w-4" /> Open adjudication queue</Button></Link>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {[
          { label: "Submissions total", value: o.total_submissions, tone: "" },
          { label: "Pending adjudications", value: o.pending_adjudications, tone: "bg-[rgba(245,158,11,0.12)] text-warn" },
          { label: "Escalated", value: o.escalated, tone: "bg-[rgba(239,68,68,0.12)] text-danger" },
          { label: "Flagged suspicious", value: o.flagged_suspicious, tone: "bg-[rgba(239,68,68,0.12)] text-danger" },
          { label: "Ambiguous reviews", value: o.ambiguous_reviews, tone: "bg-[rgba(96,165,250,0.12)] text-info" },
          { label: "Disagreement rate", value: o.disagreement_rate === null ? "—" : fmtPct(o.disagreement_rate), tone: "bg-[rgba(167,139,250,0.12)] text-[#A78BFA]" },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="p-4">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-fg-muted">{s.label}</div>
              <div className={`mt-1 text-2xl font-bold ${s.tone ? "" : "text-fg"}`}>{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><GitBranch className="h-4 w-4 text-teal" /> Disagreement monitoring</CardTitle>
            <CardDescription>
              {o.multi_review_items} items have two or more independent reviews; {o.disagreement_items} conflict and
              require an adjudication decision. Original decisions are always preserved.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/quality/adjudication" className="text-sm text-teal hover:underline">
              Review conflicting cases →
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Flag className="h-4 w-4 text-teal" /> Signals</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-fg-muted">
            <div className="flex items-center gap-2"><EyeOff className="h-3.5 w-3.5" /> {o.ambiguous_reviews} ambiguous review flags recorded</div>
            <div className="flex items-center gap-2"><Flag className="h-3.5 w-3.5" /> {o.flagged_suspicious} submissions flagged as suspicious</div>
            <div className="flex items-center gap-2"><Inbox className="h-3.5 w-3.5" /> {o.escalated} escalated submissions</div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
