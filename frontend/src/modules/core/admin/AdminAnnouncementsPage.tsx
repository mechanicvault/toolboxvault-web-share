import { useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  FormField,
  Panel,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { formatDateTime } from "../../../lib/format";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Announcements (release machinery, owner rule
 * 2026-11-08): the composer + history for feature announcements
 * — the "notification to ALL current users" every new feature
 * ships with.
 *
 * Composing queues the announcement; the announcements job
 * fans it out to every active account's inbox within a minute
 * or so. A queued/sent announcement can never be edited or
 * re-sent from here — a correction is a new announcement — so
 * this page has no edit or delete verbs, exactly like the API.
 * The composer carries English + Spanish fields (single-
 * language rule, 2026-11-10): the fan-out renders each user's
 * copy in that user's own set language, never both.
 * The gate is god + moderator admin (the API enforces it; the
 * Admin area's seat rules show the tab to the same rungs).
 */

interface Announcement {
  id: string;
  title: string;
  body: string;
  title_es?: string | null;
  body_en?: string | null;
  body_es?: string | null;
  link: string | null;
  status: string;
  recipient_count: number | null;
  created_by_name: string;
  created_at: string;
  sent_at: string | null;
}

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  sent: "Sent",
  failed: "Failed — will retry",
};

function AnnouncementsEditor() {
  const { toast } = useToast();
  const [history, setHistory] = useState<Announcement[] | null>(null);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [titleEs, setTitleEs] = useState("");
  const [bodyEs, setBodyEs] = useState("");
  const [link, setLink] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setHistory(await api<Announcement[]>("/admin/announcements"));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't load the announcement history.",
      );
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    try {
      await api<Announcement>("/admin/announcements", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          body: body.trim(),
          // Per-language parts (single-language rule, 2026-11-10):
          // each user reads the announcement in their own set
          // language — inbox and email alike. The English fields
          // double as body_en; the Spanish fields are optional
          // (no Spanish composed = Spanish-set users fall back
          // to the English text, one language either way).
          body_en: body.trim(),
          title_es: titleEs.trim() ? titleEs.trim() : null,
          body_es: bodyEs.trim() ? bodyEs.trim() : null,
          link: link.trim() ? link.trim() : null,
        }),
      });
      toast("Announcement queued — it goes to every user's inbox within a minute or so.");
      setTitle("");
      setBody("");
      setTitleEs("");
      setBodyEs("");
      setLink("");
      setConfirming(false);
      await load();
      // The job's cadence is a minute; one quiet refresh a few
      // seconds later usually catches the flip to Sent.
      window.setTimeout(() => void load(), 5000);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't queue the announcement.",
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Announcement>[] = [
    {
      key: "when",
      header: "Composed",
      sortable: true,
      sortValue: (row) => row.created_at,
      render: (row) => formatDateTime(row.created_at),
    },
    {
      key: "title",
      header: "Announcement",
      render: (row) => (
        <span className="tv-cell-stack">
          <strong>{row.title}</strong>
          <span className="tv-muted">{row.body}</span>
        </span>
      ),
    },
    {
      key: "by",
      header: "By",
      render: (row) => row.created_by_name || "—",
    },
    {
      key: "status",
      header: "Status",
      render: (row) => STATUS_LABEL[row.status] ?? row.status,
    },
    {
      key: "recipients",
      header: "Recipients",
      render: (row) =>
        row.status === "sent" && row.recipient_count !== null
          ? String(row.recipient_count)
          : "—",
    },
    {
      key: "sent",
      header: "Sent at",
      render: (row) => (row.sent_at ? formatDateTime(row.sent_at) : "—"),
    },
  ];

  return (
    <div className="tv-stack">
      <Panel title="Announce a new feature">
        <form className="tv-announce-form" onSubmit={send}>
          <p className="tv-muted tv-announce-intro">
            This sends an inbox notification to <strong>every current
            user</strong> — the announcement every new feature ships with.
            It goes out within a minute or so of sending, and it cannot be
            edited or re-sent afterwards: a correction is a new
            announcement. Each user reads it in their own set language:
            write the Spanish version too, or Spanish-set users see the
            English text.
          </p>
          <FormField label="Title (English)" hint={`${title.length} / 200`}>
            <TextInput
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                setConfirming(false);
              }}
              maxLength={200}
              placeholder="e.g. New: Build & save reports"
              required
            />
          </FormField>
          <FormField label="What changed (English)" hint={`${body.length} / 1000`}>
            <TextArea
              value={body}
              onChange={(e) => {
                setBody(e.target.value);
                setConfirming(false);
              }}
              maxLength={1000}
              rows={4}
              placeholder="A few lines on what the feature does and where to find it."
              required
            />
          </FormField>
          <FormField label="Title (Spanish, optional)" hint={`${titleEs.length} / 200`}>
            <TextInput
              value={titleEs}
              onChange={(e) => {
                setTitleEs(e.target.value);
                setConfirming(false);
              }}
              maxLength={200}
              placeholder="p. ej. Nuevo: Crea y guarda informes"
            />
          </FormField>
          <FormField label="What changed (Spanish, optional)" hint={`${bodyEs.length} / 1000`}>
            <TextArea
              value={bodyEs}
              onChange={(e) => {
                setBodyEs(e.target.value);
                setConfirming(false);
              }}
              maxLength={1000}
              rows={4}
              placeholder="La misma novedad, en español."
            />
          </FormField>
          <FormField label="Link (optional)" hint={`${link.length} / 300`}>
            <TextInput
              value={link}
              onChange={(e) => {
                setLink(e.target.value);
                setConfirming(false);
              }}
              maxLength={300}
              placeholder="/reports — an in-app page the notification opens"
            />
          </FormField>
          <div className="tv-announce-actions">
            <Button type="submit" disabled={busy || !title.trim() || !body.trim()}>
              {confirming ? "Confirm — send to all users" : "Send to all users"}
            </Button>
            {confirming && (
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </Panel>
      <Panel
        title="History"
        actions={
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            Refresh
          </Button>
        }
      >
        {error && <Alert tone="danger">{error}</Alert>}
        {!history && !error && (
          <p className="tv-announce-loading">
            <Spinner size="sm" /> Loading…
          </p>
        )}
        {history && history.length === 0 && (
          <EmptyState
            title="No announcements yet"
            description="Announcements you send appear here — what was sent, when, by whom, and to how many users."
          />
        )}
        {history && history.length > 0 && (
          <DataTable columns={columns} rows={history} rowKey={(row) => row.id} />
        )}
      </Panel>
    </div>
  );
}

export default function AdminAnnouncementsPage() {
  return (
    <RequireAuth>
      <AdminShell>
        <AnnouncementsEditor />
      </AdminShell>
    </RequireAuth>
  );
}
