import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  FormField,
  Panel,
  Spinner,
  TextInput,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { useT } from "../../../i18n/LocaleContext";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Bans (Phase A2): blocked email addresses. A ban refuses
 * signup, password sign-in, and social sign-in from the next
 * request, and ends the live sessions of any account holding the
 * address. It deletes nothing — removing the ban restores access
 * exactly as it was.
 */

interface BanView {
  id: string;
  email: string;
  reason: string;
  banned_by: string | null;
  banned_by_email: string | null;
  created_at: string;
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

function BansSection() {
  const { toast } = useToast();
  const tt = useT();
  const [bans, setBans] = useState<BanView[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [reason, setReason] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBans(await api<BanView[]>("/admin/bans"));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load the ban list.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function addBan(e: FormEvent) {
    e.preventDefault();
    /* F2-15: a ban signs accounts out everywhere on submit — it
     * confirms first, like the lesser directory removes do. */
    if (!window.confirm(tt("admin.confirm.ban").replace("{email}", email.trim().toLowerCase()))) return;
    setAdding(true);
    try {
      await api<BanView>("/admin/bans", {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), reason: reason.trim() }),
      });
      toast(`${email.trim().toLowerCase()} is banned.`, {
        tone: "success",
        duration: 8000,
      });
      setEmail("");
      setReason("");
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't add that ban.",
        { tone: "danger" },
      );
    } finally {
      setAdding(false);
    }
  }

  async function removeBan(row: BanView) {
    if (!window.confirm(tt("admin.confirm.unban").replace("{email}", row.email))) return;
    setBusyId(row.id);
    try {
      await api<void>(`/admin/bans/${row.id}`, { method: "DELETE" });
      toast(`Ban on ${row.email} removed.`, { tone: "success", duration: 8000 });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't remove that ban.",
        { tone: "danger" },
      );
    } finally {
      setBusyId(null);
    }
  }

  const columns: Column<BanView>[] = [
    { key: "email", header: "Email", sortable: true, sortValue: (row) => row.email, render: (row) => <strong>{row.email}</strong> },
    { key: "reason", header: "Reason", render: (row) => row.reason || "—" },
    {
      key: "by",
      header: "Banned by",
      render: (row) => row.banned_by_email ?? "—",
    },
    { key: "when", header: "When", sortable: true, sortValue: (row) => row.created_at, render: (row) => formatDateTime(row.created_at) },
    {
      key: "actions",
      header: "",
      render: (row) => (
        <Button
          size="sm"
          variant="secondary"
          loading={busyId === row.id}
          onClick={() => void removeBan(row)}
        >
          Remove ban
        </Button>
      ),
    },
  ];

  return (
    <AdminShell>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        <Panel title="Ban an email address">
          <form onSubmit={addBan} style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
              <FormField label="Email">
                <TextInput
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="abuser@example.com"
                  required
                />
              </FormField>
              <FormField label="Reason (shown to admins, not the user)">
                <TextInput
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. spam signups"
                />
              </FormField>
            </div>
            <div>
              <Button type="submit" variant="danger" loading={adding}>
                Ban this email
              </Button>
            </div>
            <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
              Takes effect immediately: signup, password sign-in, and Google/Facebook
              sign-in all refuse the address, and any signed-in account using it is
              signed out everywhere. Nothing is deleted.
            </p>
          </form>
        </Panel>

        <Panel title="Banned addresses">
          <div style={{ display: "grid", gap: "var(--space-3)" }}>
            {loadError && <Alert tone="danger">{loadError}</Alert>}
            {!bans && !loadError && (
              <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
                <Spinner size="sm" /> Loading bans…
              </p>
            )}
            {bans && (
              <DataTable
                columns={columns}
                rows={bans}
                rowKey={(row) => row.id}
                emptyState={
                  <EmptyState
                    title="No banned addresses"
                    description="When an address is banned, it shows up here until the ban is removed."
                  />
                }
              />
            )}
          </div>
        </Panel>
      </div>
    </AdminShell>
  );
}

export default function AdminBansPage() {
  return (
    <RequireAuth>
      <BansSection />
    </RequireAuth>
  );
}
