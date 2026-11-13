import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import "./help.css";

import {
  Alert,
  Button,
  DataTable,
  FormField,
  LinkButton,
  Modal,
  Panel,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
} from "../../components";
import type { TabItem } from "../../components/Tabs";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { usePageCrumbs } from "../../lib/navTrail";
import { RequireAuth } from "../core/auth/RequireAuth";
import { useMyModules } from "../core/MyModules";
import { BoardBody } from "../feedback/pages";
import { getCategories } from "../forum/api";
import { RoomBody } from "../forum/pages";
import {
  createTicket,
  getMyTicket,
  listMyTickets,
  replyToMyTicket,
  type TicketDetail,
  type TicketStatus,
  type TicketSummary,
} from "./api";

/**
 * Help & Support (owner-approved design, 2026-11-02): the ?
 * header door's page, rebuilt as a MAIN TAB LAYOUT page — a
 * header zone (the animated support thumbnail top-left, click
 * for the larger view; the title, the page's line, and the
 * live open-ticket count beside it), a status strip that
 * exists only while the member has unclosed tickets (each
 * entry opens that ticket), and real tabs below:
 *
 *   How we can help — the explainer + a door card per route.
 *   Support tickets — the ticket desk, moved in unchanged.
 *   Report a bug / Request a feature — the permanent forum
 *     boards' own bodies, embedded (the shared BoardBody).
 *   Ask the community — the Using Toolbox Vault room's body,
 *     embedded (the shared RoomBody).
 *   How-to videos — a DOOR, not a panel (owner, 2026-11-06):
 *     the tab keeps its place in the strip, and choosing it
 *     navigates to the How-to videos page; the embedded list
 *     that used to live here is retired.
 *
 * There is NO Actions dropdown on this page (owner,
 * 2026-11-06): every entry it held was a jump to one of the
 * tabs below it, so the tabs themselves are the whole menu.
 *
 * Tabs follow the modules exactly: feedback off → the board
 * tabs are gone; forum off → the community tab is gone;
 * support off → the desk hides with it (the videos door rides
 * the same gate as before). The main tab and the Terms link
 * are core and always show.
 * Deep links: /help?ticket=<id> lands on the tickets tab with
 * that ticket open (the standing notification door);
 * #tickets / #bugs / #features / #community name their tab on
 * arrival, and a landed #videos goes straight through to the
 * How-to videos page.
 */

type HelpTabId = "main" | "tickets" | "bugs" | "features" | "community" | "videos";

function statusKey(status: TicketStatus) {
  return status === "open"
    ? "help.statusOpen"
    : status === "under_review"
      ? "help.statusUnderReview"
      : "help.statusClosed";
}

function initialTab(): HelpTabId {
  if (typeof window === "undefined") return "main";
  switch (window.location.hash) {
    case "#tickets":
      return "tickets";
    case "#bugs":
      return "bugs";
    case "#features":
      return "features";
    case "#community":
      return "community";
    // "#videos" is NOT a tab landing any more — the page
    // redirects it to /how-to-videos on mount (below).
    default:
      return "main";
  }
}

/* -- the ticket thread (the desk's, unchanged) ------------------- */

function TicketThread({
  ticket,
  onReply,
}: {
  ticket: TicketDetail;
  onReply: (body: string) => Promise<void>;
}) {
  const t = useT();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = reply.trim();
    if (!body || busy) return;
    setBusy(true);
    setError("");
    try {
      await onReply(body);
      setReply("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send that reply.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tv-stack">
      <div className="tv-ticket-thread">
        {ticket.messages.map((m) => (
          <div key={m.id} className="tv-ticket-msg" data-kind={m.author_kind}>
            <p className="tv-ticket-msg-head">
              <strong>
                {m.author_kind === "operator" ? t("help.team") : t("help.you")}
              </strong>
              <span className="tv-muted">{formatDateTime(m.created_at)}</span>
            </p>
            <p className="tv-ticket-msg-body">{m.body}</p>
          </div>
        ))}
      </div>
      {ticket.status === "closed" ? (
        <p className="tv-muted">{t("help.closedNote")}</p>
      ) : (
        <form onSubmit={(e) => void submit(e)} noValidate className="tv-stack">
          {error && <Alert tone="danger">{error}</Alert>}
          <FormField label={t("help.sendReply")} htmlFor="ticket-reply">
            <TextArea
              id="ticket-reply"
              rows={3}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder={t("help.replyPlaceholder")}
            />
          </FormField>
          <div>
            <Button type="submit" disabled={busy || reply.trim() === ""}>
              {t("help.sendReply")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/* -- the ticket desk (moved into its tab unchanged) -------------- */

function TicketsDesk({
  tickets,
  selected,
  setSelected,
  load,
  open,
}: {
  tickets: TicketSummary[] | null;
  selected: TicketDetail | null;
  setSelected: (ticket: TicketDetail | null) => void;
  load: () => void;
  open: (id: string) => void;
}) {
  const t = useT();
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Prefill seam (Reports redesign, 2026-11-06): another page
  // (the Reports "Request a report type" tab) can hand the desk
  // a half-written ticket through sessionStorage. Read ONCE on
  // mount and consumed — a stale prefill never haunts a later
  // visit, and the ticket itself is still created only when
  // the user submits this form.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("tv.ticketPrefill");
      if (!raw) return;
      sessionStorage.removeItem("tv.ticketPrefill");
      const prefill = JSON.parse(raw) as { subject?: string; message?: string };
      if (prefill.subject) setSubject(prefill.subject);
      if (prefill.message) setMessage(prefill.message);
    } catch {
      // A malformed prefill is ignored — the blank form stands.
    }
  }, []);

  const subjectError = submitted && subject.trim() === "" ? t("help.subjectRequired") : "";
  const messageError = submitted && message.trim() === "" ? t("help.messageRequired") : "";

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (subject.trim() === "" || message.trim() === "" || busy) return;
    setBusy(true);
    setError("");
    try {
      const detail = await createTicket(subject.trim(), message.trim());
      setSubject("");
      setMessage("");
      setSubmitted(false);
      setSelected(detail);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't open that ticket.");
    } finally {
      setBusy(false);
    }
  };

  const reply = async (body: string) => {
    if (!selected) return;
    const updated = await replyToMyTicket(selected.id, body);
    setSelected(updated);
    load();
  };

  return (
    <div className="tv-stack">
      <p className="tv-muted">{t("help.ticketsBody")}</p>
      {selected ? (
        <div className="tv-stack">
          <div className="tv-title-row">
            <div>
              <h3>{selected.subject}</h3>
              <p className="tv-muted">{t(statusKey(selected.status))}</p>
            </div>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              ← {t("help.backToTickets")}
            </Button>
          </div>
          <TicketThread ticket={selected} onReply={reply} />
        </div>
      ) : (
        <>
          <form onSubmit={(e) => void create(e)} noValidate className="tv-stack">
            {error && <Alert tone="danger">{error}</Alert>}
            <FormField label={t("help.subject")} htmlFor="ticket-subject" error={subjectError || undefined} required>
              <TextInput
                id="ticket-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t("help.subjectPlaceholder")}
                invalid={!!subjectError}
                maxLength={200}
              />
            </FormField>
            <FormField label={t("help.message")} htmlFor="ticket-message" error={messageError || undefined} required>
              <TextArea
                id="ticket-message"
                rows={4}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={t("help.messagePlaceholder")}
                invalid={!!messageError}
              />
            </FormField>
            <div>
              <Button type="submit" disabled={busy}>
                {t("help.send")}
              </Button>
            </div>
          </form>
          <h3>{t("help.myTickets")}</h3>
          {tickets === null ? (
            <Spinner />
          ) : tickets.length === 0 ? (
            <p className="tv-muted">{t("help.noTickets")}</p>
          ) : (
            /* True list (list standard): one ticket per row,
             * facts in columns — subject · status · updated —
             * with the Open action as its own column; clicking
             * the row opens the same thread. */
            <div className="tv-table-min">
              <DataTable<TicketSummary>
                columns={[
                  {
                    key: "subject",
                    header: t("help.subject"),
                    sortable: true,
                    sortValue: (tk) => tk.subject,
                    render: (tk) => <strong>{tk.subject}</strong>,
                  },
                  {
                    key: "status",
                    header: t("admin.support.status"),
                    sortable: true,
                    sortValue: (tk) => tk.status,
                    render: (tk) => t(statusKey(tk.status)),
                  },
                  {
                    key: "updated",
                    header: t("help.col.updated"),
                    sortable: true,
                    sortValue: (tk) => tk.updated_at,
                    render: (tk) => formatDateTime(tk.updated_at),
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
        </>
      )}
    </div>
  );
}

/* -- the community tab -------------------------------------------- */

function CommunityTab() {
  const t = useT();
  const [roomId, setRoomId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCategories(true)
      .then((cats) => {
        if (cancelled) return;
        const room = cats.find((c) => c.system_key === "site_help");
        if (room) setRoomId(room.id);
        else setFailed(true);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="tv-stack">
      <p className="tv-muted">{t("help.community.intro")}</p>
      <Alert tone="info">{t("help.community.planNote")}</Alert>
      {failed ? (
        <Alert tone="danger">{t("help.community.loadError")}</Alert>
      ) : roomId === null ? (
        <Spinner />
      ) : (
        <>
          <RoomBody
            categoryId={roomId}
            emptyTitle={t("help.community.empty")}
            emptyDescription=""
          />
          <p className="tv-muted">
            <LinkButton to={`/forum/category/${roomId}`} variant="secondary">
              {t("help.community.openInForum")}
            </LinkButton>
          </p>
        </>
      )}
    </div>
  );
}

/* -- the page -------------------------------------------------------- */

export default function HelpSupportPage() {
  const t = useT();
  const navigate = useNavigate();
  const myModules = useMyModules();
  const supportOn = myModules.has("support");
  const feedbackOn = myModules.has("feedback");
  const forumOn = myModules.has("forum");

  const [activeTab, setActiveTab] = useState<HelpTabId>(initialTab);
  const [thumbOpen, setThumbOpen] = useState(false);

  // The member's tickets are read ONCE at page level: the
  // header's open-ticket count, the status strip, and the
  // tickets tab all read the same list (the design's rule —
  // no extra calls).
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);
  const [selected, setSelected] = useState<TicketDetail | null>(null);

  const loadTickets = useCallback(() => {
    if (!supportOn) {
      setTickets([]);
      return;
    }
    listMyTickets()
      .then(setTickets)
      .catch(() => setTickets([]));
  }, [supportOn]);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  const openTicket = useCallback((id: string) => {
    getMyTicket(id)
      .then(setSelected)
      .catch(() => undefined);
  }, []);

  // Notification click-through landing (owner spec 2026-10-25,
  // behavior preserved): ?ticket=<id> opens that ticket on
  // arrival — now on the Tickets tab. A ticket that is gone (or
  // not the member's) fails the open silently and the ticket
  // list stands — no error, no dead end.
  const [searchParams] = useSearchParams();
  const landedTicket = useRef<string | null>(null);
  useEffect(() => {
    const ticketId = searchParams.get("ticket");
    if (ticketId && supportOn && landedTicket.current !== ticketId) {
      landedTicket.current = ticketId;
      setActiveTab("tickets");
      openTicket(ticketId);
    }
  }, [searchParams, supportOn, openTicket]);

  // The videos "tab" is a door (owner, 2026-11-06): choosing
  // it — from the tab strip, the main tab's lead link, or its
  // door card, all of which funnel through here — navigates
  // to the How-to videos page instead of switching a panel in.
  const selectTab = useCallback(
    (id: string) => {
      if (id === "videos") {
        navigate("/how-to-videos");
        return;
      }
      setActiveTab(id as HelpTabId);
    },
    [navigate],
  );

  // A landed /help#videos link follows the same door (the
  // deep link predates the videos page; it lands there now).
  useEffect(() => {
    if (window.location.hash === "#videos") {
      navigate("/how-to-videos", { replace: true });
    }
  }, [navigate]);

  // Hash-follow while mounted (sweep B8, 2026-11-12): the
  // mount-time initialTab only covers fresh arrivals — an
  // in-app link to /help#tickets clicked while this page is
  // already open changes only the hash, and the reader stayed
  // on the main tab. Follow the named tab on hashchange, the
  // Lane 1 hash-follow discipline the Feedback page already
  // keeps. Unknown hashes never yank the reader off their tab,
  // and a tab whose module is off falls back via effectiveTab.
  useEffect(() => {
    const follow = () => {
      const hash = window.location.hash;
      if (hash === "#videos") {
        navigate("/how-to-videos");
        return;
      }
      if (["#tickets", "#bugs", "#features", "#community"].includes(hash)) {
        setActiveTab(initialTab());
      }
    };
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, [navigate]);

  const openTickets = (tickets ?? []).filter((tk) => tk.status !== "closed");

  const tabLabels: Record<HelpTabId, string> = {
    main: t("help.tab.main"),
    tickets: t("help.tab.tickets"),
    bugs: t("help.tab.bugs"),
    features: t("help.tab.features"),
    community: t("help.tab.community"),
    videos: t("help.tab.videos"),
  };

  // Link tree (owner directive 2026-11-02): Home › Help &
  // Support › the tab you're on — registered with the shell's
  // page navigation bar, replacing the route-derived trail.
  usePageCrumbs([
    { label: t("nav.core"), to: "/" },
    { label: t("help.title") },
    { label: tabLabels[activeTab] },
  ]);

  /* The main tab: the approved explainer + a door card per
   * route (each card exists only while its route does). */
  const copySections: {
    lead: DictKey;
    body: DictKey;
    tab: HelpTabId | null;
  }[] = [
    { lead: "help.copy.ticketsLead", body: "help.copy.tickets", tab: supportOn ? "tickets" : null },
    { lead: "help.copy.bugsLead", body: "help.copy.bugs", tab: feedbackOn ? "bugs" : null },
    { lead: "help.copy.featuresLead", body: "help.copy.features", tab: feedbackOn ? "features" : null },
    { lead: "help.copy.communityLead", body: "help.copy.community", tab: forumOn ? "community" : null },
    { lead: "help.copy.videosLead", body: "help.copy.videos", tab: supportOn ? "videos" : null },
  ];

  const doors: {
    key: string;
    title: string;
    body: string;
    tab: HelpTabId | null;
  }[] = [
    { key: "tickets", title: tabLabels.tickets, body: t("help.door.tickets"), tab: supportOn ? "tickets" : null },
    { key: "bugs", title: tabLabels.bugs, body: t("help.door.bugs"), tab: feedbackOn ? "bugs" : null },
    { key: "features", title: tabLabels.features, body: t("help.door.features"), tab: feedbackOn ? "features" : null },
    { key: "community", title: tabLabels.community, body: t("help.door.community"), tab: forumOn ? "community" : null },
    { key: "videos", title: tabLabels.videos, body: t("help.door.videos"), tab: supportOn ? "videos" : null },
  ];

  const mainContent = (
    <div>
      <div className="tv-help-copy">
        <p>{t("help.copy.intro")}</p>
        {copySections
          .filter((section) => section.tab !== null)
          .map((section) => (
            <p key={section.lead}>
              {/* The lead is a tab link (owner 2026-11-03): the
               * header text itself opens its tab, through the
               * same selectTab the tabs and the door cards'
               * Open buttons use. The words are the approved
               * copy, unchanged. */}
              <button
                type="button"
                className="tv-help-leadlink"
                onClick={() => selectTab(section.tab as HelpTabId)}
              >
                <strong>{t(section.lead)}</strong>
              </button>{" "}
              {t(section.body)}
            </p>
          ))}
        <p>
          <strong>{t("help.copy.termsLead")}</strong> — {t("help.copy.terms")}{" "}
          <Link to="/terms">{t("help.termsLink")}</Link>
        </p>
        <p>
          <Link to="/setup">{t("setup.helpLink" as never)}</Link>
        </p>
      </div>
      <h2>{t("help.doorsTitle")}</h2>
      <div className="tv-help-doors">
        {doors
          .filter((door) => door.tab !== null)
          .map((door) => (
            <div key={door.key} className="tv-help-door">
              <h3>
                {/* The door's header is a tab link too (owner
                 * 2026-11-03): same selectTab as the tabs and
                 * this card's Open button. */}
                <button
                  type="button"
                  className="tv-help-doorlink"
                  onClick={() => selectTab(door.tab as HelpTabId)}
                >
                  {door.title}
                </button>
              </h3>
              <p>{door.body}</p>
              <div className="tv-help-door-action">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => selectTab(door.tab as HelpTabId)}
                >
                  {t("help.openDoor")}
                </Button>
              </div>
            </div>
          ))}
        <div className="tv-help-door">
          <h3>{t("help.termsTitle")}</h3>
          <p>{t("help.door.terms")}</p>
          <div className="tv-help-door-action">
            <LinkButton to="/terms" variant="secondary" size="sm">
              {t("help.termsLink")}
            </LinkButton>
          </div>
        </div>
      </div>
    </div>
  );

  const tabs: TabItem[] = [{ id: "main", label: tabLabels.main, content: mainContent }];
  if (supportOn) {
    tabs.push({
      id: "tickets",
      label: tabLabels.tickets,
      content: (
        <TicketsDesk
          tickets={tickets}
          selected={selected}
          setSelected={setSelected}
          load={loadTickets}
          open={openTicket}
        />
      ),
    });
  }
  if (feedbackOn) {
    tabs.push({ id: "bugs", label: tabLabels.bugs, content: <BoardBody board="bug" /> });
    tabs.push({
      id: "features",
      label: tabLabels.features,
      content: <BoardBody board="feature" />,
    });
  }
  if (forumOn) {
    tabs.push({
      id: "community",
      label: tabLabels.community,
      content: <CommunityTab />,
    });
  }
  if (supportOn) {
    // The door tab: it renders in the strip in its old place
    // but never becomes the active tab — selectTab navigates
    // first — so its panel never shows; the content is a
    // placeholder that exists only to satisfy the tab shape.
    tabs.push({ id: "videos", label: tabLabels.videos, content: null });
  }

  // A deep link can name a tab the viewer's modules have since
  // switched off: the main tab is the honest landing then.
  const effectiveTab = tabs.some((tab) => tab.id === activeTab) ? activeTab : "main";

  return (
    <RequireAuth>
      <div className="tv-stack">
        <Panel>
          <div className="tv-help-head">
            <div className="tv-help-thumb">
              <button
                type="button"
                className="tv-help-thumb-btn"
                onClick={() => setThumbOpen(true)}
                aria-label={t("help.viewLarger")}
              >
                <picture>
                  <source
                    srcSet="/brand/help-support.webp"
                    media="(prefers-reduced-motion: no-preference)"
                    type="image/webp"
                  />
                  <img
                    src="/brand/help-support-still.webp"
                    alt={t("help.thumbAlt")}
                  />
                </picture>
              </button>
            </div>
            <div className="tv-help-head-main">
              <h1 className="tv-help-title">{t("help.title")}</h1>
              <p className="tv-help-subtitle">{t("help.subtitle")}</p>
              {supportOn && tickets !== null && (
                <dl className="tv-help-facts">
                  <div className="tv-help-fact">
                    <dt>{t("help.tab.tickets")}</dt>
                    <dd>
                      {openTickets.length === 0
                        ? t("help.noOpenTickets")
                        : openTickets.length === 1
                          ? t("help.openCountOne")
                          : t("help.openCount").replace(
                              "{count}",
                              String(openTickets.length),
                            )}
                    </dd>
                  </div>
                </dl>
              )}
            </div>
          </div>
        </Panel>

        {supportOn && openTickets.length > 0 && (
          <div className="tv-help-status">
            <span className="tv-help-status-label">{t("help.tab.tickets")}</span>
            {openTickets.map((tk) => (
              <button
                key={tk.id}
                type="button"
                className="tv-help-status-entry"
                onClick={() => {
                  setActiveTab("tickets");
                  openTicket(tk.id);
                }}
              >
                <span className="tv-help-status-subject">{tk.subject}</span>
                <span className="tv-help-status-state">
                  {t(statusKey(tk.status))}
                  {tk.last_message_author_kind === "operator"
                    ? ` · ${t("help.waitingOnYou")}`
                    : ""}
                </span>
              </button>
            ))}
          </div>
        )}

        <Tabs tabs={tabs} activeId={effectiveTab} onChange={selectTab} />

        <Modal
          open={thumbOpen}
          onClose={() => setThumbOpen(false)}
          title={t("help.title")}
          size="lg"
        >
          <div className="tv-help-thumb-large">
            <picture>
              <source
                srcSet="/brand/help-support.webp"
                media="(prefers-reduced-motion: no-preference)"
                type="image/webp"
              />
              <img
                src="/brand/help-support-still.webp"
                alt={t("help.thumbAlt")}
              />
            </picture>
          </div>
        </Modal>
      </div>
    </RequireAuth>
  );
}
