import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  Panel,
  Spinner,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useAuth } from "../AuthContext";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Conversion requests (tier conversion, 2026-11-10):
 * the god queue for the request door out of the downloads
 * level. A limited account without the gate code may ask ONCE
 * for full access; the god account alone decides (the API
 * enforces god-only — this page's guard is the same rule worn
 * on the surface, so a lesser seat never even sees the queue).
 * Approve runs the same conversion as the code door; Deny is
 * final for the request door and leaves the code door open.
 */

interface ConversionRequestView {
  id: string;
  user_id: string;
  account_number: string;
  name: string;
  email: string;
  status: string;
  created_at: string;
  decided_by_email: string;
  decided_at: string | null;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function RequestsSection() {
  const { user } = useAuth();
  const { toast } = useToast();
  const [rows, setRows] = useState<ConversionRequestView[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api<ConversionRequestView[]>("/admin/conversion-requests"));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load the requests.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(row: ConversionRequestView, approve: boolean) {
    setBusyId(row.id);
    try {
      await api<ConversionRequestView>(
        `/admin/conversion-requests/${row.id}/${approve ? "approve" : "deny"}`,
        { method: "POST" },
      );
      toast(
        approve
          ? `${row.name} now has full access.`
          : `Request from ${row.name} denied.`,
        { tone: "success", duration: 8000 },
      );
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't record that decision.",
        { tone: "danger" },
      );
    } finally {
      setBusyId(null);
    }
  }

  if (user && user.tier !== "god") {
    return (
      <AdminShell>
        <Panel>
          <EmptyState
            title="God account only"
            description="Conversion requests are decided by the god account alone. Moderator and moderator-admin accounts don't see this queue."
          />
        </Panel>
      </AdminShell>
    );
  }

  const columns: Column<ConversionRequestView>[] = [
    {
      key: "account",
      header: "Account",
      sortable: true,
      sortValue: (row) => row.name,
      render: (row) => (
        <>
          <strong>{row.name}</strong>
          <br />
          <span className="tv-admin-muted">{row.account_number}</span>
        </>
      ),
    },
    { key: "email", header: "Email", render: (row) => row.email },
    {
      key: "requested",
      header: "Requested",
      sortable: true,
      sortValue: (row) => row.created_at,
      render: (row) => formatDateTime(row.created_at),
    },
    {
      key: "status",
      header: "Status",
      render: (row) =>
        row.status === "pending"
          ? "Pending"
          : row.status === "approved"
            ? "Approved"
            : "Denied",
    },
    {
      key: "decision",
      header: "Decision",
      render: (row) =>
        row.decided_at
          ? `${row.decided_by_email} · ${formatDateTime(row.decided_at)}`
          : "—",
    },
    {
      key: "actions",
      header: "",
      render: (row) =>
        row.status === "pending" ? (
          <span className="tv-admin-actions">
            <Button
              size="sm"
              variant="primary"
              loading={busyId === row.id}
              onClick={() => void decide(row, true)}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="secondary"
              loading={busyId === row.id}
              onClick={() => void decide(row, false)}
            >
              Deny
            </Button>
          </span>
        ) : null,
    },
  ];

  return (
    <AdminShell>
      <Panel title="Conversion requests">
        <div className="tv-admin-stack">
          <p className="tv-admin-muted">
            Downloads-level accounts that don't have the full-access code can
            ask once for full access. Approving converts the account exactly
            like the code does. Denying is final for the request — the account
            keeps the code door.
          </p>
          {loadError && <Alert tone="danger">{loadError}</Alert>}
          {!rows && !loadError && (
            <p className="tv-admin-loading">
              <Spinner size="sm" /> Loading requests…
            </p>
          )}
          {rows && (
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(row) => row.id}
              emptyState={
                <EmptyState
                  title="No conversion requests"
                  description="When a Downloads-level account asks for full access, the request shows up here for a decision."
                />
              }
            />
          )}
        </div>
      </Panel>
    </AdminShell>
  );
}

export default function AdminConversionRequestsPage() {
  return (
    <RequireAuth>
      <RequestsSection />
    </RequireAuth>
  );
}
