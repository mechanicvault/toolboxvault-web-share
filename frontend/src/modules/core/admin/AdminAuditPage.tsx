import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Button,
  DataTable,
  DatePicker,
  EmptyState,
  FormField,
  Pagination,
  Panel,
  Spinner,
  TextInput,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Audit (Phase A2): the operator trail, read-only. Every
 * mutating admin action — module toggles, code creates, grants,
 * bans, role changes, deactivations, setting changes — lands here
 * with the actor, the target, and the detail. Filter by actor
 * (email or account id), action, and date window.
 */

interface AuditEntry {
  id: string;
  actor_user_id: string | null;
  actor_email: string;
  action: string;
  target: string;
  detail: Record<string, unknown>;
  created_at: string;
}

interface AuditPageData {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 50;

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function detailSummary(detail: Record<string, unknown>): string {
  const parts = Object.entries(detail)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  return parts.join(" · ") || "—";
}

function AuditSection() {
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [applied, setApplied] = useState({ actor: "", action: "", since: "", until: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AuditPageData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      if (applied.actor.trim()) params.set("actor", applied.actor.trim());
      if (applied.action.trim()) params.set("action", applied.action.trim());
      if (applied.since) params.set("since", new Date(`${applied.since}T00:00:00`).toISOString());
      if (applied.until) params.set("until", new Date(`${applied.until}T23:59:59`).toISOString());
      setData(await api<AuditPageData>(`/admin/audit?${params.toString()}`));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load the audit log.",
      );
    }
  }, [applied, page]);

  useEffect(() => {
    void load();
  }, [load]);

  function applyFilters() {
    setApplied({ actor, action, since, until });
    setPage(1);
  }

  const columns: Column<AuditEntry>[] = [
    { key: "when", header: "When", sortable: true, sortValue: (row) => row.created_at, render: (row) => formatDateTime(row.created_at) },
    { key: "actor", header: "Actor", sortable: true, sortValue: (row) => row.actor_email || "", render: (row) => row.actor_email || "—" },
    { key: "action", header: "Action", render: (row) => <strong>{row.action}</strong> },
    { key: "target", header: "Target", render: (row) => row.target || "—" },
    { key: "detail", header: "Detail", render: (row) => detailSummary(row.detail) },
  ];

  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <AdminShell>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <Panel title="Audit log">
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "end" }}>
              <FormField label="Actor (email or id)">
                <TextInput value={actor} onChange={(e) => setActor(e.target.value)} />
              </FormField>
              <FormField label="Action" hint="The exact action code — e.g. ban.create, ban.remove, user.operator_grant, announcement.create, setting.update.">
                <TextInput
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                  placeholder="e.g. ban.create"
                />
              </FormField>
              <FormField label="Since">
                <DatePicker value={since} onChange={setSince} clearable />
              </FormField>
              <FormField label="Until">
                <DatePicker value={until} onChange={setUntil} clearable />
              </FormField>
              <Button size="sm" onClick={applyFilters}>
                Filter
              </Button>
            </div>
            {loadError && <Alert tone="danger">{loadError}</Alert>}
            {!data && !loadError && (
              <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
                <Spinner size="sm" /> Loading audit log…
              </p>
            )}
            {data && (
              <>
                <DataTable
                  columns={columns}
                  rows={data.items}
                  rowKey={(row) => row.id}
                  emptyState={
                    <EmptyState
                      title="No audit entries match"
                      description="Operator actions show up here the moment they happen. Widen the filters, or go make some history."
                    />
                  }
                />
                <Pagination
                  page={page}
                  pageCount={pageCount}
                  onChange={setPage}
                  summary={`${data.total} entr${data.total === 1 ? "y" : "ies"}`}
                />
              </>
            )}
          </div>
        </Panel>
      </div>
    </AdminShell>
  );
}

export default function AdminAuditPage() {
  return (
    <RequireAuth>
      <AuditSection />
    </RequireAuth>
  );
}
