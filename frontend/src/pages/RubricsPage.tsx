import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, ArrowRight } from "lucide-react";
import { queries } from "@/api/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { fmtDateTime } from "@/lib/utils";
import type { Rubric } from "@/lib/types";

export default function RubricsPage() {
  const { data, isLoading, isError, error, refetch } = useQuery(queries.rubrics());

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-fg">Rubrics</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Structured evaluation criteria with weights, scoring scales and deterministic checks. Historical
          versions are immutable so past evaluations stay reproducible.
        </p>
      </div>

      {isLoading ? (
        <TableSkeleton rows={4} cols={3} />
      ) : isError ? (
        <ErrorState message={(error as Error)?.message} retry={refetch} />
      ) : (data as Rubric[]).length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="No rubrics yet"
          description="A rubric defines the criteria, automatic checks and passing thresholds used to evaluate responses."
          action={
            <Link
              to="/rubrics/new"
              className="rounded-md bg-teal px-4 py-2 text-sm font-semibold text-[#0B1518] hover:bg-teal/90"
            >
              Create your first rubric
            </Link>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(data as Rubric[]).map((r) => (
            <Link key={r.id} to={`/rubrics/${r.id}`} className="group">
              <Card className="h-full transition-colors group-hover:border-teal/50">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <ClipboardList className="h-4 w-4 text-teal" /> {r.name}
                    </span>
                    <Badge variant="neutral">v{r.current_version}</Badge>
                  </CardTitle>
                  <CardDescription className="line-clamp-2">{r.description ?? "No description"}</CardDescription>
                </CardHeader>
                <CardContent className="flex items-center justify-between">
                  <span className="text-xs text-fg-muted">Created {fmtDateTime(r.created_at)}</span>
                  <span className="flex items-center gap-1 text-xs text-teal opacity-0 transition-opacity group-hover:opacity-100">
                    Open <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
