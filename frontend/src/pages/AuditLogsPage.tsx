import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { queries } from "@/api/hooks";
import { useAuth } from "@/lib/auth";
import { isStaff, isPlatformAdmin } from "@/lib/roles";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Input, NativeSelect } from "@/components/ui/input";
import { fmtDateTime, truncate } from "@/lib/utils";

const ENTITY_TYPES = ["dataset", "rubric", "evaluation", "review", "result", "project", "settings", "user", "demo"];

function ACTION_VARIANT(action: string): "danger" | "success" | "warning" | "info" {
  if (action.includes("delete")) return "danger";
  if (action.includes("create") || action.includes("register")) return "success";
  if (action.includes("execute") || action.includes("submit") || action.includes("adjudicate")) return "warning";
  return "info";
}

export default function AuditLogsPage() {
  const { user } = useAuth();
  const isAdmin = isStaff(user?.role ?? "");
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery(queries.auditLogs(page, { action: action || undefined, entity_type: entityType || undefined }));

  if (!isAdmin) {
    return (
      <EmptyState
        icon={ScrollText}
        title="Audit logs are restricted"
        description="Only administrators and project managers can inspect the audit trail. Your access attempt has been logged."
      />
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-fg">Audit logs</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Traceable event records. Every evaluation result links to its dataset version, rubric version and
          evaluator version; destructive updates to historical records are blocked at the API level.
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Events</CardTitle>
            <CardDescription>{data?.total ?? 0} events on record</CardDescription>
          </div>
          <div className="flex gap-2">
            <Input
              aria-label="Filter by action"
              placeholder="Filter action (e.g. evaluation.)"
              className="h-8 w-56 text-xs"
              value={action}
              onChange={(e) => { setAction(e.target.value); setPage(1); }}
            />
            <NativeSelect
              aria-label="Filter by entity type"
              className="h-8 w-44 text-xs"
              value={entityType}
              onChange={(e) => { setEntityType(e.target.value); setPage(1); }}
            >
              <option value="">All entities</option>
              {ENTITY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </NativeSelect>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <TableSkeleton rows={8} cols={5} />
          ) : isError ? (
            <ErrorState message={(error as Error)?.message} retry={refetch} />
          ) : data!.items.length === 0 ? (
            <EmptyState icon={ScrollText} title="No audit events match" description="Adjust the filters above." />
          ) : (
            <>
              <Table>
                <THead>
                  <TR>
                    <TH>Time</TH>
                    <TH>Action</TH>
                    <TH>Entity</TH>
                    <TH>User</TH>
                    <TH>Details</TH>
                    <TH>IP</TH>
                  </TR>
                </THead>
                <TBody>
                  {data!.items.map((log) => (
                    <TR key={log.id}>
                      <TD className="whitespace-nowrap text-xs text-fg-muted">{fmtDateTime(log.created_at)}</TD>
                      <TD><Badge variant={ACTION_VARIANT(log.action)}>{log.action}</Badge></TD>
                      <TD className="text-xs">
                        {log.entity_type ? (
                          <span className="font-mono">{log.entity_type}#{log.entity_id ?? "—"}</span>
                        ) : "—"}
                      </TD>
                      <TD className="text-xs text-fg-muted">{log.user_id ?? "system"}</TD>
                      <TD className="max-w-[280px] font-mono text-[11px] text-fg-muted">
                        {log.details ? truncate(JSON.stringify(log.details), 90) : "—"}
                      </TD>
                      <TD className="font-mono text-xs text-fg-muted">{log.ip ?? "—"}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {data!.total > data!.page_size && (
                <div className="mt-3 flex items-center justify-between text-sm text-fg-muted">
                  <span>Page {data!.page} of {Math.ceil(data!.total / data!.page_size)}</span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                    <Button variant="outline" size="sm" disabled={page >= Math.ceil(data!.total / data!.page_size)} onClick={() => setPage((p) => p + 1)}>Next</Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
