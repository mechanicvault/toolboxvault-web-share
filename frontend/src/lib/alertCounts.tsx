import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import { api } from "./api";

/**
 * Alert counts (sheet row 62, owner 2026-11-17): the unread
 * numbers behind the left menu's red count badges and the Home
 * widgets' urgency flags. One summary — GET
 * /core/notifications/summary — feeds both surfaces; the counts
 * are derived server-side from the inbox (plus the live overdue
 * borrow count), so nothing here stores state of its own:
 * marking a notification read is what clears a badge.
 *
 * Refresh posture: on mount, on every route change, when the
 * window regains focus, once a minute, and immediately when an
 * inbox action announces itself through ALERTS_CHANGED_EVENT
 * (the inbox hook's mark-read / mark-all-read / delete raise
 * it). A failed fetch badges nothing — a missing badge is a
 * quieter failure than a wrong one.
 */
export const ALERTS_CHANGED_EVENT = "tv-alerts-changed";

export function notifyAlertsChanged(): void {
  window.dispatchEvent(new Event(ALERTS_CHANGED_EVENT));
}

export type AlertCounts = Record<string, number>;

const AlertCountsContext = createContext<AlertCounts>({});

export function useAlertCounts(): AlertCounts {
  return useContext(AlertCountsContext);
}

export function AlertCountsProvider({
  value,
  children,
}: {
  value: AlertCounts;
  children: ReactNode;
}) {
  return (
    <AlertCountsContext.Provider value={value}>
      {children}
    </AlertCountsContext.Provider>
  );
}

export function useAlertSummary(enabled: boolean): AlertCounts {
  const [counts, setCounts] = useState<AlertCounts>({});
  const { pathname } = useLocation();
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const refresh = useCallback(() => {
    if (!enabledRef.current) {
      setCounts({});
      return;
    }
    api<{ counts?: Record<string, number> }>("/core/notifications/summary")
      .then((data) => {
        const clean: AlertCounts = {};
        for (const [key, value] of Object.entries(data?.counts ?? {})) {
          if (typeof value === "number" && value > 0) clean[key] = value;
        }
        setCounts(clean);
      })
      .catch(() => {
        /* best-effort chrome: a failed summary read badges nothing */
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, pathname, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const onSignal = () => refresh();
    window.addEventListener(ALERTS_CHANGED_EVENT, onSignal);
    window.addEventListener("focus", onSignal);
    const timer = window.setInterval(refresh, 60_000);
    return () => {
      window.removeEventListener(ALERTS_CHANGED_EVENT, onSignal);
      window.removeEventListener("focus", onSignal);
      window.clearInterval(timer);
    };
  }, [enabled, refresh]);

  return counts;
}

/**
 * Tab badges (sheet row 190, owner 2026-11-19): the counts
 * behind the tab bubbles — GET /core/notifications/tab-badges.
 * Same refresh posture as the alert summary above. The counts
 * are per TAB, a finer split than the summary's surfaces:
 * claims / maintenance / disaster count their own unread kinds;
 * borrowing arrives in two parts (unread notes, which clear by
 * being marked read, and the live overdue checkout ids, which
 * clear by the tool coming back — the page holds the ids it has
 * already shown so a clicked tab stays clear until a NEW tool
 * goes overdue); health is the live scan count and never clears
 * on click — it stays until the flagged items are fixed.
 */
export interface TabBadges {
  claims: number;
  maintenance: number;
  disaster: number;
  borrowing: number;
  borrowingOverdueIds: string[];
  health: number;
}

export const EMPTY_TAB_BADGES: TabBadges = {
  claims: 0,
  maintenance: 0,
  disaster: 0,
  borrowing: 0,
  borrowingOverdueIds: [],
  health: 0,
};

const TabBadgesContext = createContext<TabBadges>(EMPTY_TAB_BADGES);

export function useTabBadges(): TabBadges {
  return useContext(TabBadgesContext);
}

export function TabBadgesProvider({
  value,
  children,
}: {
  value: TabBadges;
  children: ReactNode;
}) {
  return (
    <TabBadgesContext.Provider value={value}>
      {children}
    </TabBadgesContext.Provider>
  );
}

interface TabBadgesWire {
  claims?: number;
  maintenance?: number;
  disaster?: number;
  borrowing?: number;
  borrowing_overdue_ids?: string[];
  health?: number;
}

export function useTabBadgeData(enabled: boolean): TabBadges {
  const [badges, setBadges] = useState<TabBadges>(EMPTY_TAB_BADGES);
  const { pathname } = useLocation();
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const refresh = useCallback(() => {
    if (!enabledRef.current) {
      setBadges(EMPTY_TAB_BADGES);
      return;
    }
    api<TabBadgesWire>("/core/notifications/tab-badges")
      .then((data) => {
        const num = (v: number | undefined) =>
          typeof v === "number" && v > 0 ? v : 0;
        setBadges({
          claims: num(data?.claims),
          maintenance: num(data?.maintenance),
          disaster: num(data?.disaster),
          borrowing: num(data?.borrowing),
          borrowingOverdueIds: Array.isArray(data?.borrowing_overdue_ids)
            ? data.borrowing_overdue_ids
            : [],
          health: num(data?.health),
        });
      })
      .catch(() => {
        /* best-effort chrome: a failed read badges nothing */
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, pathname, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const onSignal = () => refresh();
    window.addEventListener(ALERTS_CHANGED_EVENT, onSignal);
    window.addEventListener("focus", onSignal);
    const timer = window.setInterval(refresh, 60_000);
    return () => {
      window.removeEventListener(ALERTS_CHANGED_EVENT, onSignal);
      window.removeEventListener("focus", onSignal);
      window.clearInterval(timer);
    };
  }, [enabled, refresh]);

  return badges;
}

/** Mark one tab's notifications read (clicking the tab clears
 *  its bubble), then tell every badge surface to refresh. */
export async function markTabRead(
  tab: "claims" | "maintenance" | "disaster" | "borrowing",
): Promise<void> {
  try {
    await api("/core/notifications/read-tab", {
      method: "POST",
      body: JSON.stringify({ tab }),
    });
  } catch {
    /* the bubble simply stays — the next refresh tells truth */
  }
  notifyAlertsChanged();
}

const OVERDUE_SEEN_PREFIX = "tv-borrow-overdue-seen:";

/** The overdue checkout ids this browser has already shown this
 *  user on the Borrowing tab — what keeps a clicked tab clear
 *  until a NEW tool goes overdue. Per user, per device. */
export function seenOverdueIds(userId: string): string[] {
  try {
    const raw = localStorage.getItem(OVERDUE_SEEN_PREFIX + userId);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === "string")
      : [];
  } catch {
    return [];
  }
}

export function storeSeenOverdueIds(userId: string, ids: string[]): void {
  try {
    localStorage.setItem(OVERDUE_SEEN_PREFIX + userId, JSON.stringify(ids));
  } catch {
    /* private mode etc. — the bubble just re-shows next visit */
  }
}

/**
 * The red count pill itself — one rendering for every surface
 * that carries it (widget heads today; the rail carries its own
 * seat-shaped variant in AppShell). A bare number, phone-badge
 * style; the aria label carries the words.
 */
export function AlertPill({ count }: { count: number }) {
  const t = useT();
  if (count <= 0) return null;
  return (
    <span
      className="tv-alert-pill"
      role="status"
      aria-label={`${count} ${t("shell.unreadAlerts")}`}
    >
      {count}
    </span>
  );
}
