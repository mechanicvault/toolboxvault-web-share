import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import { formatDateTime } from "../lib/format";
import {
  AccentGearChooser,
  type GearSiteSettingsLink,
} from "../theme/AccentDots";
import { BellIcon, HelpIcon, SearchIcon } from "./icons";
import { useNotificationInbox } from "./NotificationTicker";

/* The Edit view channel lives in lib/editView (AuthContext
 * clears the flag at session boundaries, so it can't sit in
 * this component module); re-exported here for the existing
 * import sites. */
export { EDIT_VIEW_EVENT, EDIT_VIEW_FLAG, takeEditViewRequest } from "../lib/editView";

/**
 * The header cluster (Home + Header program, owner 2026-10-24):
 * the top-right corner of EVERY signed-in page, in the owner's
 * exact order — color gear · HOW TO (text link to the how-to
 * videos page, owner 2026-11-06) · notifications bell · ? help ·
 * person (the user menu's door, owner 2026-11-03) · search bar.
 *
 * Edit view LEFT this cluster (owner order 2026-11-09,
 * dashboard-flare lane): Home's customize entry now lives on
 * the Home page itself, at the far right of its own title row
 * (CorePage), and the window-event channel that carried the
 * click is retired with it — the re-export above stays only
 * so AuthContext's session-boundary flag clearing keeps its
 * import; nothing raises or consumes the request anymore.
 */
function NotificationsBell() {
  const t = useT();
  const location = useLocation();
  const navigate = useNavigate();
  const inbox = useNotificationInbox(true, 100);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  /* Scroll cue (sweep 10-F13): true while the list holds more
   * below its fold — drives the bottom fade + "More below" line
   * so the panel never silently cuts an item at its edge. */
  const [moreBelow, setMoreBelow] = useState(false);
  const measureMore = () => {
    const el = listRef.current;
    if (!el) {
      setMoreBelow(false);
      return;
    }
    setMoreBelow(el.scrollHeight - el.scrollTop - el.clientHeight > 8);
  };
  const { unreadCount } = inbox;
  const active = unreadCount > 0;

  // Route changes close the popup (the page it described is gone).
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return;
    void inbox.refresh();
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    // Focus the popup's first control on open (dialog pattern).
    const tId = window.setTimeout(() => {
      wrapRef.current
        ?.querySelector<HTMLElement>(".tv-bell-pop button, .tv-bell-pop a")
        ?.focus();
    }, 0);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(tId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open ]);

  const shown = inbox.items.slice(0, 8);

  // Re-measure the scroll cue whenever the panel opens or the
  // list's contents settle (the inbox refresh lands a tick
  // after the panel opens).
  useEffect(() => {
    if (!open) return;
    const raf = window.requestAnimationFrame(measureMore);
    return () => window.cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, shown.length]);

  return (
    <div className="tv-bell-wrap" ref={wrapRef}>
      <button
        ref={btnRef}
        type="button"
        className="tv-hbtn tv-bell-btn"
        data-active={active || undefined}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t("shell.notifications")}
        onClick={() => setOpen((o) => !o)}
      >
        <BellIcon size={19} />
        {active && (
          <span className="tv-bell-badge" aria-hidden="true">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>
      {open && (
        <div className="tv-bell-pop" role="dialog" aria-label={t("shell.notifications")}>
          <div className="tv-bell-pop-head">
            <span className="tv-bell-pop-title">{t("shell.notifications")}</span>
            <button
              type="button"
              className="tv-bell-pop-action"
              disabled={unreadCount === 0}
              onClick={() => void inbox.markAllRead()}
            >
              {t("shell.markAllRead")}
            </button>
          </div>
          {shown.length === 0 ? (
            <p className="tv-bell-pop-empty">{t("shell.allCaughtUp")}</p>
          ) : (
            <div className="tv-bell-listwrap" data-more={moreBelow || undefined}>
              <ul className="tv-bell-list" ref={listRef} onScroll={measureMore}>
              {shown.map((n) => (
                <li key={n.id} className="tv-bell-item" data-read={n.read || undefined}>
                  <span className="tv-bell-dot" data-tone={n.tone} aria-hidden="true" />
                  <button
                    type="button"
                    className="tv-bell-item-main"
                    onClick={() => {
                      // Owner spec 2026-10-25: a click marks the
                      // notification read AND goes to its source
                      // (the server-resolved `link`). The mark is
                      // fire-and-forget — the header stays mounted
                      // across the navigation, so the badge count
                      // still settles from the same local update.
                      if (!n.read) void inbox.markRead(n.id);
                      if (n.link) {
                        setOpen(false);
                        navigate(n.link);
                      }
                    }}
                  >
                    <span className="tv-bell-item-title">{n.title}</span>
                    <span className="tv-bell-item-text">{n.text}</span>
                    <span className="tv-bell-item-time">
                      {formatDateTime(n.created_at)}
                      {!n.read && <> · {t("notifications.unread")}</>}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="tv-bell-item-x"
                    aria-label={t("shell.deleteNotification")}
                    title={t("shell.deleteNotification")}
                    onClick={() => void inbox.remove(n.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
              </ul>
              {moreBelow && (
                <p className="tv-bell-more" aria-hidden="true">
                  {t("shell.notificationsMore")} ↓
                </p>
              )}
            </div>
          )}
          <div className="tv-bell-pop-foot">
            <Link
              className="tv-bell-pop-action"
              to="/notifications"
              onClick={() => setOpen(false)}
            >
              {t("shell.seeAllNotifications")} →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

export function HeaderCluster({
  siteSettingsLinks = [],
  railPinned,
  onToggleRailPin,
  userMenu,
  preSetup = false,
}: {
  /** The gear popup's Site settings tree leaves, built by the
   * app from the settings registry (owner, 2026-11-01); empty
   * signed out, where the tree row never renders. */
  siteSettingsLinks?: GearSiteSettingsLink[];
  /** The gear popup's rail pin row state + toggle (owner,
   * 2026-11-05), forwarded to the chooser; the row renders
   * only when a toggle is supplied (a signed-in session). */
  railPinned?: boolean;
  onToggleRailPin?: () => void;
  /** The user menu element (app constructs it from auth state):
   * its person-icon trigger renders immediately beside the Help
   * ? (owner, 2026-11-03). Undefined on the signed-out strip,
   * where the shell renders the menu element itself. */
  userMenu?: ReactNode;
  /** Pre-setup (sweep 10-F3): the account exists but has not
   * picked its type yet — the bell and header search are held
   * from the frame until a type exists (see the render note). */
  preSetup?: boolean;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  return (
    <div className="tv-hcluster">
      <AccentGearChooser
        siteSettingsLinks={siteSettingsLinks}
        railPinned={railPinned}
        onToggleRailPin={onToggleRailPin}
      />
      {/* HOW TO (owner, 2026-11-06): a plain text link in the
       * header's own link dress (.tv-hlink, the Edit view
       * button's style), immediately beside the gear, ALWAYS
       * visible — never in a menu or popup. Ungated, exactly
       * like the ? door below: the /how-to-videos route is
       * never route-gated either, and the page itself says so
       * plainly when the support module is off for the user,
       * so the link always lands somewhere honest. */}
      <Link className="tv-hlink" to="/how-to-videos">
        {t("shell.howTo")}
      </Link>
      {/* Pre-setup gating (sweep 10-F3): until the account has
       * picked its type, the bell and the header search can do
       * nothing — the inbox is empty by construction and there
       * are no records for search to find — so both are HELD
       * from the frame entirely (the rail's own pre-setup gate
       * applied to the header) instead of offering dead clicks.
       * They appear the moment a type exists. The gear, HOW TO,
       * help, and the person menu all genuinely work pre-setup
       * (appearance is part of setup; help is public guidance;
       * the menu carries sign-out and account facts), so they
       * stay. */}
      {!preSetup && <NotificationsBell />}
      <Link
        className="tv-hbtn"
        to="/help"
        aria-label={t("shell.help")}
        title={t("shell.help")}
      >
        <HelpIcon size={19} />
      </Link>
      {userMenu}
      {!preSetup && (
      <form
        role="search"
        className="tv-hsearch"
        onSubmit={(e) => {
          e.preventDefault();
          const q = query.trim();
          // Global search (owner spec, 2026-10-25): the header
          // bar searches the user's own records EVERYWHERE and
          // lands on the grouped results page — it no longer
          // routes into Inventory-only smart search. Inventory
          // keeps its own in-page search field, unchanged.
          navigate(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
        }}
      >
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("shell.searchPlaceholder")}
          aria-label={t("shell.searchPlaceholder")}
          className="tv-input"
        />
        <button
          type="submit"
          className="tv-hsearch-btn"
          aria-label={t("shell.searchPlaceholder")}
        >
          <SearchIcon size={16} />
        </button>
      </form>
      )}
    </div>
  );
}

