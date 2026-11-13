import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  DataTable,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { ApiError } from "../../../lib/api";
import { formatDateTime } from "../../../lib/format";
import {
  adminCreateVideo,
  adminDeleteVideo,
  adminGetTicket,
  adminListTickets,
  adminListVideos,
  adminReply,
  adminSetStatus,
  adminUpdateVideo,
  type AdminHelpVideo,
  type AdminTicketDetail,
  type AdminTicketSummary,
  type HelpVideoWrite,
  type TicketStatus,
} from "../../support/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Support tickets (Home + Header program, 2026-10-24):
 * the operator side of the ticket desk. Every user ticket lands
 * here; a reply moves it to "under review" and notifies the
 * owner through the inbox; a status change notifies too. New
 * tickets and member follow-ups notify every operator through
 * the same inbox (Phase 2). The API is require_operator — this
 * page is only the visible half.
 */
const STATUSES: TicketStatus[] = ["open", "under_review", "closed"];

function Desk() {
  const t = useT();
  const [filter, setFilter] = useState<"" | TicketStatus>("");
  const [tickets, setTickets] = useState<AdminTicketSummary[] | null>(null);
  const [selected, setSelected] = useState<AdminTicketDetail | null>(null);
  const [reply, setReply] = useState("");
  const [status, setStatus] = useState<TicketStatus>("open");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");

  const load = useCallback(() => {
    adminListTickets(filter || undefined)
      .then((rows) => {
        setTickets(rows);
        setListError("");
      })
      .catch(() => {
        // A failed load is NOT an empty desk (Phase 2
        // hardening): say so, with a way back — never pretend
        // there are no tickets.
        setTickets([]);
        setListError(t("admin.support.loadError"));
      });
  }, [filter, t]);

  useEffect(() => {
    load();
  }, [load]);

  const open = (id: string) => {
    adminGetTicket(id)
      .then((d) => {
        setSelected(d);
        setStatus(d.status);
        setError("");
      })
      .catch(() => undefined);
  };

  // Notification click-through landing (owner spec 2026-10-25):
  // ?ticket=<id> opens that ticket on arrival. A ticket that no
  // longer exists fails the open silently and the desk list
  // stands — no error, no dead end.
  const [searchParams] = useSearchParams();
  const landedTicket = useRef<string | null>(null);
  useEffect(() => {
    const ticketId = searchParams.get("ticket");
    if (ticketId && landedTicket.current !== ticketId) {
      landedTicket.current = ticketId;
      open(ticketId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const sendReply = async (e: FormEvent) => {
    e.preventDefault();
    if (!selected || reply.trim() === "" || busy) return;
    setBusy(true);
    setError("");
    try {
      const updated = await adminReply(selected.id, reply.trim());
      setSelected(updated);
      setStatus(updated.status);
      setReply("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send that reply.");
    } finally {
      setBusy(false);
    }
  };

  const saveStatus = async () => {
    if (!selected || busy || status === selected.status) return;
    setBusy(true);
    setError("");
    try {
      const updated = await adminSetStatus(selected.id, status);
      setSelected(updated);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save that status.");
    } finally {
      setBusy(false);
    }
  };

  const statusLabel = (s: TicketStatus) =>
    t(s === "open" ? "help.statusOpen" : s === "under_review" ? "help.statusUnderReview" : "help.statusClosed");

  return (
    <div className="tv-stack">
      {/* 09b-F3: the section wears the same Panel + title treatment
          as every sibling Admin section — the giant bare H1 and the
          floating filter are gone; the filter rides the panel's
          header actions like the Users/Audit panels. */}
      <Panel
        title={t("admin.support.title")}
        actions={
          <FormField label={t("admin.support.status")} htmlFor="support-filter">
            <Select
              id="support-filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value as "" | TicketStatus)}
            >
              <option value="">{t("admin.support.filterAll")}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </Select>
          </FormField>
        }
      >
        <p className="tv-muted" style={{ margin: 0 }}>
          {t("admin.support.intro")}
        </p>
      </Panel>
      {error && <Alert tone="danger">{error}</Alert>}
      {selected ? (
        <Panel>
          <div className="tv-stack">
            <div className="tv-title-row">
              <div>
                <h3>{selected.subject}</h3>
                <p className="tv-muted">
                  {selected.user_name} · {selected.user_email} ·{" "}
                  {selected.user_account_number}
                </p>
                <p className="tv-muted">{statusLabel(selected.status)}</p>
              </div>
              <Button variant="ghost" onClick={() => setSelected(null)}>
                ← {t("admin.support.backToAll")}
              </Button>
            </div>
            <div className="tv-ticket-thread">
              {selected.messages.length === 0 && (
                <p className="tv-muted">{t("admin.support.emptyThread")}</p>
              )}
              {selected.messages.map((m) => (
                <div key={m.id} className="tv-ticket-msg" data-kind={m.author_kind}>
                  <p className="tv-ticket-msg-head">
                    <strong>
                      {m.author_kind === "operator" ? t("help.team") : selected.user_name}
                    </strong>
                    <span className="tv-muted">{formatDateTime(m.created_at)}</span>
                  </p>
                  <p className="tv-ticket-msg-body">{m.body}</p>
                </div>
              ))}
            </div>
            <form onSubmit={(e) => void sendReply(e)} noValidate className="tv-stack">
              <FormField label={t("admin.support.reply")} htmlFor="admin-ticket-reply">
                <TextArea
                  id="admin-ticket-reply"
                  rows={3}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder={t("help.replyPlaceholder")}
                />
              </FormField>
              <div className="tv-row-actions">
                <Button type="submit" disabled={busy || reply.trim() === ""}>
                  {t("help.sendReply")}
                </Button>
              </div>
            </form>
            <div className="tv-row-actions">
              <FormField label={t("admin.support.status")} htmlFor="admin-ticket-status">
                <Select
                  id="admin-ticket-status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as TicketStatus)}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {statusLabel(s)}
                    </option>
                  ))}
                </Select>
              </FormField>
              <Button
                variant="secondary"
                disabled={busy || status === selected.status}
                onClick={() => void saveStatus()}
              >
                {t("admin.support.saveStatus")}
              </Button>
            </div>
          </div>
        </Panel>
      ) : listError ? (
        <Alert tone="danger">
          {listError}{" "}
          <Button size="sm" variant="secondary" onClick={load}>
            {t("admin.support.retry")}
          </Button>
        </Alert>
      ) : tickets === null ? (
        <Spinner />
      ) : tickets.length === 0 ? (
        <EmptyState title={t("admin.support.empty")} />
      ) : (
        /* True list (list standard, Wave 3): one ticket per row,
         * facts in columns — subject · requester · status ·
         * updated · message count — with the Open action kept as
         * its own column; clicking the row opens the same thread.
         * The last-message preview is no longer a row fact: it is
         * the thread's own last message, one click away. */
        <div className="tv-table-min">
          <DataTable<AdminTicketSummary>
            columns={[
              {
                key: "subject",
                header: t("help.subject"),
                sortable: true,
                sortValue: (tk) => tk.subject,
                render: (tk) => <strong>{tk.subject}</strong>,
              },
              {
                key: "requester",
                header: t("admin.support.requester"),
                sortable: true,
                sortValue: (tk) => tk.user_name,
                render: (tk) => tk.user_name,
              },
              {
                key: "status",
                header: t("admin.support.status"),
                sortable: true,
                sortValue: (tk) => tk.status,
                render: (tk) => statusLabel(tk.status),
              },
              {
                key: "updated",
                header: t("help.col.updated"),
                sortable: true,
                sortValue: (tk) => tk.updated_at,
                render: (tk) => formatDateTime(tk.updated_at),
              },
              {
                key: "messages",
                header: t("admin.support.messages"),
                sortable: true,
                sortValue: (tk) => tk.message_count,
                render: (tk) => tk.message_count,
              },
              {
                key: "open",
                header: "",
                render: (tk) => (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={(e) => {
                      e.stopPropagation();
                      open(tk.id);
                    }}
                  >
                    {t("home.open")}
                  </Button>
                ),
              },
            ]}
            rows={tickets}
            rowKey={(tk) => tk.id}
            onRowClick={(tk) => open(tk.id)}
          />
        </div>
      )}
    </div>
  );
}

/**
 * The how-to videos manager (owner-approved design, 2026-11-02):
 * the operator-managed published list behind the Help & Support
 * page's How-to videos tab. A title, a one-line summary, a
 * YouTube link, a section, an order, and a published flag —
 * nothing else; the videos themselves live on YouTube and no
 * video file is hosted on this server. Drafts never reach the
 * member-facing tab.
 */
function VideoManager() {
  const t = useT();
  const [rows, setRows] = useState<AdminHelpVideo[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [youtube, setYoutube] = useState("");
  const [section, setSection] = useState<"website" | "app">("website");
  const [order, setOrder] = useState("0");
  const [published, setPublished] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    adminListVideos()
      .then((list) => {
        setRows(list);
        setLoadFailed(false);
      })
      .catch(() => {
        setRows([]);
        setLoadFailed(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function startNew() {
    setEditingId("new");
    setTitle("");
    setSummary("");
    setYoutube("");
    setSection("website");
    setOrder(String(rows?.length ?? 0));
    setPublished(false);
    setError("");
  }

  function startEdit(row: AdminHelpVideo) {
    setEditingId(row.id);
    setTitle(row.title);
    setSummary(row.summary);
    setYoutube(`https://www.youtube.com/watch?v=${row.youtube_id}`);
    setSection(row.section);
    setOrder(String(row.sort_order));
    setPublished(row.is_published);
    setError("");
  }

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || title.trim() === "" || youtube.trim() === "") return;
    setBusy(true);
    setError("");
    const body: HelpVideoWrite = {
      title: title.trim(),
      summary: summary.trim(),
      youtube: youtube.trim(),
      section,
      sort_order: Number.parseInt(order, 10) || 0,
      is_published: published,
    };
    try {
      if (editingId === "new") {
        await adminCreateVideo(body);
      } else if (editingId) {
        await adminUpdateVideo(editingId, body);
      }
      setEditingId(null);
      load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save that video.",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: AdminHelpVideo) => {
    if (!window.confirm(t("admin.videos.confirmDelete"))) return;
    setError("");
    try {
      await adminDeleteVideo(row.id);
      if (editingId === row.id) setEditingId(null);
      load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't delete that video.",
      );
    }
  };

  return (
    <Panel
      title={t("admin.videos.title")}
      actions={
        editingId === null ? (
          <Button size="sm" onClick={startNew}>
            {t("admin.videos.add")}
          </Button>
        ) : undefined
      }
    >
      <div className="tv-stack">
        <p className="tv-muted">{t("admin.videos.body")}</p>
        {error && <Alert tone="danger">{error}</Alert>}
        {loadFailed && <Alert tone="danger">{t("admin.videos.loadError")}</Alert>}
        {rows === null ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <p className="tv-muted">{t("admin.videos.empty")}</p>
        ) : (
          rows.map((row) => (
            <div key={row.id} className="tv-title-row">
              <div>
                <strong>{row.title}</strong>{" "}
                <Badge tone={row.is_published ? "success" : "neutral"}>
                  {row.is_published
                    ? t("admin.videos.publishedField")
                    : t("admin.videos.draft")}
                </Badge>
                <p className="tv-muted">
                  {row.section === "website"
                    ? t("help.videos.website")
                    : t("help.videos.app")}{" "}
                  · {t("admin.videos.orderField")} {row.sort_order} ·{" "}
                  {row.youtube_id}
                </p>
              </div>
              <div className="tv-row-actions">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => startEdit(row)}
                >
                  {t("admin.videos.edit")}
                </Button>
                <button
                  type="button"
                  className="tv-list-remove-btn"
                  aria-label={`${t("admin.videos.delete")}: ${row.title}`}
                  title={t("admin.videos.delete")}
                  onClick={() => void remove(row)}
                >
                  {"−"}
                </button>
              </div>
            </div>
          ))
        )}
        {editingId !== null && (
          <form onSubmit={(e) => void save(e)} noValidate className="tv-stack">
            <FormField label={t("admin.videos.titleField")} htmlFor="video-title" required>
              <TextInput
                id="video-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
              />
            </FormField>
            <FormField label={t("admin.videos.summaryField")} htmlFor="video-summary">
              <TextInput
                id="video-summary"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
              />
            </FormField>
            <FormField label={t("admin.videos.youtubeField")} htmlFor="video-youtube" required>
              <TextInput
                id="video-youtube"
                value={youtube}
                onChange={(e) => setYoutube(e.target.value)}
              />
            </FormField>
            <FormField label={t("admin.videos.sectionField")} htmlFor="video-section">
              <Select
                id="video-section"
                value={section}
                onChange={(e) => setSection(e.target.value as "website" | "app")}
              >
                <option value="website">{t("help.videos.website")}</option>
                <option value="app">{t("help.videos.app")}</option>
              </Select>
            </FormField>
            <FormField label={t("admin.videos.orderField")} htmlFor="video-order">
              <TextInput
                id="video-order"
                type="number"
                value={order}
                onChange={(e) => setOrder(e.target.value)}
              />
            </FormField>
            <Checkbox
              label={t("admin.videos.publishedField")}
              checked={published}
              onChange={(e) => setPublished(e.target.checked)}
            />
            <div className="tv-row-actions">
              <Button
                type="submit"
                disabled={busy || title.trim() === "" || youtube.trim() === ""}
              >
                {t("admin.videos.save")}
              </Button>
              <Button
                variant="ghost"
                onClick={() => setEditingId(null)}
                disabled={busy}
              >
                {t("common.cancel")}
              </Button>
            </div>
          </form>
        )}
      </div>
    </Panel>
  );
}

export default function AdminSupportPage() {
  return (
    <RequireAuth>
      <AdminShell>
        <div className="tv-stack">
          <Desk />
          <VideoManager />
        </div>
      </AdminShell>
    </RequireAuth>
  );
}
