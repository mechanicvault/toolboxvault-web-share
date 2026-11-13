import { useEffect, useState } from "react";
import { useT } from "../../i18n/LocaleContext";
import { Link, useNavigate } from "react-router-dom";

import { Panel } from "../../components";
import {
  useNotificationInbox,
  type InboxItem,
} from "../../components/NotificationTicker";
import { api } from "../../lib/api";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import { optBool } from "./widgetOptions";

/**
 * Home-page notifications block: the bell popup's inbox seam
 * (useNotificationInbox → GET /api/core/notifications, the core
 * inbox service), so the rows carry the read state and the
 * server-resolved click-through link the bell popup and the
 * notifications page already use — one seam, one link mapping
 * (inbox_links, resolved server-side), never a client fork.
 *
 * Owner 2026-11-02: NEW (unread) rows are marked by the lit dot
 * alone — the tone dot glows while unread and greys to the edge
 * color (no glow) once read, and the TEXT runs identical either
 * way: same weight, same ink (owner correction, later the same
 * day: "just have the light up buttons if they are new, not
 * bold text too"). The bell popup / notifications page keep
 * their own text emphasis; this is the Home widget's treatment.
 * A row whose kind resolved to a
 * destination is a button — the click marks it read AND goes to
 * that destination, the bell's exact handler. A row with no
 * destination stays plain text, never a fake link. In Edit view
 * the rows go inert like every other Home control (the drag/X
 * chrome owns the surface — Overview drops its stat hrefs the
 * same way), so a click while customizing never navigates.
 *
 * Widget options Wave 4 batch A: the block's options bundle
 * (registered in widgetOptions under "notifications") — how
 * many rows show before the list scrolls (3 / 5 / 8; 5 is the
 * original cap, parameterized here in place, never forked),
 * the overdue line's on/off, and unread-only. Absent settings
 * are today's block exactly.
 */
export function NotificationsBlock({
  editing = false,
  settings = {},
  bare = false,
}: {
  editing?: boolean;
  settings?: Record<string, BlockSettingValue>;
  /** Custom-widget composition (Lane 2): sections only —
   *  no Panel, no title; the composite box carries its own. */
  bare?: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  const inbox = useNotificationInbox(true, 100);
  const items = inbox.items;
  const rawCap = settings["rowsBeforeScroll"];
  const rowsCap = rawCap === 3 || rawCap === 8 ? rawCap : 5;
  const showOverdueLine = optBool(settings, "overdueLine", true);
  const unreadOnly = optBool(settings, "unreadOnly", false);
  // Custom-widget aspect gate (Lane 2): the rows themselves
  // carry a switch so a custom box may carry only the
  // overdue line. Absence = on — the predefined block is
  // byte-identical.
  const showRows = optBool(settings, "showRows", true);
  const shown = unreadOnly ? items.filter((item) => !item.read) : items;
  // F5-03: "all caught up" must account for overdue work. The
  // inbox seam only carries sharing events, so the block ALSO
  // reads the maintenance overview: an overdue schedule makes
  // the block say so (and link to it) instead of claiming calm.
  // The overdue-line option off = the line (and its read) rest.
  const [overdue, setOverdue] = useState(0);
  useEffect(() => {
    if (!showOverdueLine) {
      setOverdue(0);
      return;
    }
    let live = true;
    api<{ schedules: { due_status: string }[] }>("/maintenance/overview")
      .then((o) => {
        if (live) setOverdue(o.schedules.filter((s) => s.due_status === "overdue").length);
      })
      .catch(() => { /* module off or failed: the inbox copy stands alone */ });
    return () => { live = false; };
  }, [showOverdueLine]);

  const rowBody = (item: InboxItem) => (
    <>
      <span
        className="tv-home-activity-dot"
        data-tone={item.tone || undefined}
        aria-hidden="true"
      />
      <span className="tv-home-activity-text">{item.text}</span>
    </>
  );

  const inner = (
    <>
      {overdue > 0 && (
        <p className="tv-home-attn" style={{ margin: "0 0 0.5rem" }}>
          <Link to="/repairs#tool-maintenance" style={{ color: "var(--accent)", fontWeight: 600 }}>
            {overdue} {t("home.overdueBefore")}{overdue === 1 ? "" : "s"} {overdue === 1 ? t("home.overdueIs") : t("home.overdueAre")}
          </Link>
        </p>
      )}
      {showRows && (items.length === 0 ? (
        // F1-24: compact one-line empty treatment (was a ~200px
        // dashed slab). F5-03 copy: no global "all caught up"
        // claim the block can't back.
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("home.noNotifications")}
        </p>
      ) : shown.length === 0 ? (
        // Unread-only with everything read (Wave 4 batch A):
        // the quiet caught-up line the design promised, in the
        // same one-line empty treatment.
        <p className="tv-home-empty-note">
          {t("home.notifCaughtUp")}
        </p>
      ) : (
        <ul
          // Owner 2026-11-01: past five rows the list scrolls
          // inside the block (.tv-home-activity--capped carries
          // the height); at five or fewer it renders as before.
          // Wave 4 batch A: the cap is the block's rows option
          // (3 / 5 / 8) — data-rows carries it to the CSS, the
          // 5-row height stays the no-attribute default.
          className={
            shown.length > rowsCap
              ? "tv-home-activity tv-home-activity--capped"
              : "tv-home-activity"
          }
          data-rows={shown.length > rowsCap ? rowsCap : undefined}
        >
          {shown.map((item) => (
            <li
              key={item.id}
              className="tv-home-activity-item"
              data-read={item.read || undefined}
            >
              {item.link && !editing ? (
                <button
                  type="button"
                  className="tv-home-activity-main"
                  onClick={() => {
                    // The bell popup's handler, verbatim: mark
                    // read fire-and-forget, then go to the
                    // server-resolved destination (a deleted
                    // source already downgraded server-side to
                    // the module's main page).
                    if (!item.read) void inbox.markRead(item.id);
                    if (item.link) navigate(item.link);
                  }}
                >
                  {rowBody(item)}
                </button>
              ) : (
                <span className="tv-home-activity-main">
                  {rowBody(item)}
                </span>
              )}
            </li>
          ))}
        </ul>
      ))}
    </>
  );
  if (bare) return inner;
  return (
    <Panel
      title={t("home.notifications")}
      actions={
        items.length > 0 ? (
          <span className="tv-panel-count">
            {items.length} note{items.length === 1 ? "" : "s"}
          </span>
        ) : undefined
      }
    >
      {inner}
    </Panel>
  );
}
