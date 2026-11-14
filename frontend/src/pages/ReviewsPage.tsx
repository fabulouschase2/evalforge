import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Inbox } from "lucide-react";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { BORDERLINE_CATEGORIES } from "@/lib/types";
import { fmtDateTime, truncate } from "@/lib/utils";

export default function ReviewsPage() {
  const { user } = useAuth();
  const queue = useQuery(queries.reviewQueue());
  const assignments = useQuery(queries.assignments());

  const mySubmitted = (assignments.data ?? []).filter((a) => a.status === "submitted");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Human review</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Independent, blind reviews of automated evaluation decisions. You will not see other reviewers'
          assessments until your own has been submitted.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your review queue ({queue.data?.total ?? 0} pending)</CardTitle>
          <CardDescription>
            Flagged results assigned to you. Borderline and uncertain automated decisions land here.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {queue.isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : queue.isError ? (
            <ErrorState message={(queue.error as Error)?.message} retry={queue.refetch} />
          ) : (queue.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              icon={Inbox}
              title="No pending reviews"
              description="Your queue is clear. New assignments appear when evaluations flag results for human review."
            />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Record</TH>
                  <TH>Run</TH>
                  <TH>Automated</TH>
                  <TH>Borderline category</TH>
                  <TH>Prompt</TH>
                  <TH>Assigned</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {queue.data!.items.map((item) => (
                  <TR key={item.assignment.id}>
                    <TD className="font-mono text-xs">{item.record_id}</TD>
                    <TD className="text-xs">
                      <Link to={`/evaluations/${item.run_id}`} className="text-teal hover:underline">
                        {item.run_name ?? `Run ${item.run_id}`}
                      </Link>
                    </TD>
                    <TD>
                      <StatusBadge status={item.automated_status} />
                    </TD>
                    <TD className="text-xs text-fg-muted">
                      {item.borderline_category
                        ? BORDERLINE_CATEGORIES[item.borderline_category] ?? item.borderline_category.replace(/_/g, " ")
                        : "—"}
                    </TD>
                    <TD className="max-w-[260px] text-xs text-fg-muted">{truncate(item.prompt_excerpt, 110)}</TD>
                    <TD className="text-fg-muted">{fmtDateTime(item.assignment.created_at)}</TD>
                    <TD>
                      <Link
                        to={`/reviews/${item.assignment.id}`}
                        className="rounded-md bg-teal px-3 py-1.5 text-xs font-semibold text-[#0B1518] hover:bg-teal/90"
                      >
                        Review
                      </Link>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your submitted reviews ({mySubmitted.length})</CardTitle>
          <CardDescription>
            Submitted assessments are immutable. Adjudications on disputed items are shown in the review workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {assignments.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : mySubmitted.length === 0 ? (
            <div className="py-4 text-center text-sm text-fg-muted">No submitted reviews yet.</div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Result</TH>
                  <TH>Status</TH>
                  <TH>Assigned</TH>
                  <TH>Submitted</TH>
                </TR>
              </THead>
              <TBody>
                {mySubmitted.map((a) => (
                  <TR key={a.id}>
                    <TD className="font-mono text-xs">result #{a.result_id}</TD>
                    <TD><Badge variant="success">submitted</Badge></TD>
                    <TD className="text-fg-muted">{fmtDateTime(a.created_at)}</TD>
                    <TD className="text-fg-muted">{fmtDateTime(a.submitted_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
