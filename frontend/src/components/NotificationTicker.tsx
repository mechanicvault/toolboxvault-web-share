import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

export interface NotificationItem {
  id: string;
  text: string;
  tone?: "accent" | "success" | "warning" | "danger";
}

/** The full inbox row (Home + Header program, 2026-10-24): the
 *  bell popup and the notifications page need the title, the read
 *  state and the timestamp the ticker never carried. `text` is the
 *  server one-liner (== body today) — the popup shows it in full. */
export interface InboxItem {
  id: string;
  kind: string;
  title: string;
  body: string;
  text: string;
  tone: "accent" | "success" | "warning" | "danger";
  data: Record<string, unknown>;
  /** Click-through destination (owner spec 2026-10-25),
   *  resolved server-side per kind + payload: clicking the
   *  notification marks it read AND goes here. Null only for
   *  a kind with no destination — the click then keeps the
   *  old mark-read-only behavior. */
  link: string | null;
  created_at: string;
  read_at: string | null;
  read: boolean;
}

export interface NotificationInbox {
  items: InboxItem[];
  unreadCount: number;
  loading: boolean;
  refresh: () => Promise<void>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/**
 * The inbox with its verbs (Home + Header program): one fetch of
 * the full notification rows plus read / read-all / delete actions
 * that mutate local state only AFTER the server answers (a failed
 * call leaves the list untouched — the surface never claims a
 * state the server doesn't hold). `enabled` gates the fetch for
 * signed-out renders, same as useNotifications.
 */
export function useNotificationInbox(
  enabled: boolean,
  limit = 100,
): NotificationInbox {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const rows = await api<InboxItem[]>(
        `/core/notifications?limit=${limit}`,
      );
      setItems(rows);
    } catch {
      /* best-effort chrome: a failed inbox fetch renders empty */
    } finally {
      setLoading(false);
    }
  }, [enabled, limit]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const markRead = useCallback(async (id: string) => {
    await api(`/core/notifications/${id}/read`, { method: "POST" });
    setItems((prev) =>
      prev.map((n) =>
        n.id === id
          ? { ...n, read: true, read_at: n.read_at ?? new Date().toISOString() }
          : n,
      ),
    );
  }, []);

  const markAllRead = useCallback(async () => {
    await api(`/core/notifications/read-all`, { method: "POST" });
    setItems((prev) =>
      prev.map((n) =>
        n.read ? n : { ...n, read: true, read_at: new Date().toISOString() },
      ),
    );
  }, []);

  const remove = useCallback(async (id: string) => {
    await api(`/core/notifications/${id}`, { method: "DELETE" });
    setItems((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const unreadCount = items.filter((n) => !n.read).length;
  return { items, unreadCount, loading, refresh, markRead, markAllRead, remove };
}

/**
 * Data seam for the header ticker: GET /api/core/notifications
 * (served by the core inbox service — peer-sharing lifecycle
 * events today).
 *
 * Failure handling is by design: any failure (network, bad shape,
 * empty list) resolves to an empty list, and the ticker renders
 * nothing at all (no reserved space, no layout shift).
 */
export function useNotifications(
  enabled = true,
  limit?: number,
): NotificationItem[] {
  const [items, setItems] = useState<NotificationItem[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    // The endpoint serves the past-30-days window (gap wave 1);
    // callers that only ever show the newest slice — the header
    // ticker — ask for just that slice.
    const path = limit
      ? `/core/notifications?limit=${limit}`
      : "/core/notifications";
    api<unknown>(path)
      .then((data) => {
        if (!live || !Array.isArray(data)) return;
        const clean: NotificationItem[] = [];
        for (const d of data) {
          if (
            typeof d === "object" &&
            d !== null &&
            typeof (d as NotificationItem).text === "string" &&
            (d as NotificationItem).id !== undefined
          ) {
            const item = d as NotificationItem;
            clean.push({ id: String(item.id), text: item.text, tone: item.tone });
          }
        }
        setItems(clean);
      })
      .catch(() => {
        /* No notifications endpoint yet — silence is the design. */
      });
    return () => {
      live = false;
    };
  }, [enabled, limit]);
  return items;
}

const DWELL_MS = 3000;
const ROLL_MS = 520; // just past the track's 480ms CSS transition

/**
 * Header notifications ticker: one notification at a time, ~3s dwell,
 * VERTICAL roll (the track slides up through a one-line viewport,
 * wrapping through a clone of the first item). Pauses on hover/focus;
 * prefers-reduced-motion swaps instantly (the track transition is
 * disabled in CSS). Renders NOTHING when there are no notifications.
 *
 * Pass `items` to render supplied data (style-guide demo); omit it to
 * use the live useNotifications seam.
 */
export function NotificationTicker({ items: itemsProp }: { items?: NotificationItem[] }) {
  // The ticker rolls the newest slice only (20, its historical
  // window) — the full 30-day list lives in the home block.
  const fetched = useNotifications(itemsProp === undefined, 20);
  const items = itemsProp ?? fetched;
  const count = items.length;
  const [pos, setPos] = useState(0);
  const [snap, setSnap] = useState(false);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    setPos(0);
  }, [count]);

  useEffect(() => {
    if (count < 2 || paused) return;
    const t = setInterval(() => setPos((p) => p + 1), DWELL_MS);
    return () => clearInterval(t);
  }, [count, paused]);

  // Showing the clone of item 0 (pos === count): once the roll lands,
  // snap back to the real item 0 without a transition.
  useEffect(() => {
    if (count > 1 && pos === count) {
      const t = setTimeout(() => {
        setSnap(true);
        setPos(0);
      }, ROLL_MS);
      return () => clearTimeout(t);
    }
    if (snap) {
      const r = requestAnimationFrame(() => setSnap(false));
      return () => cancelAnimationFrame(r);
    }
  }, [pos, count, snap]);

  if (count === 0) return null;
  const active = items[pos % count];
  const trackItems = count > 1 ? [...items, items[0]] : items;
  return (
    <div
      className="tv-ticker"
      role="status"
      aria-label={`Notification: ${active.text}`}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="tv-ticker-dot" data-tone={active.tone ?? "accent"} aria-hidden="true" />
      <div className="tv-ticker-viewport" aria-hidden="true">
        <div
          className="tv-ticker-track"
          style={{
            transform: `translateY(calc(var(--ticker-h) * ${-pos}))`,
            transition: snap ? "none" : undefined,
          }}
        >
          {trackItems.map((item, i) => (
            <div className="tv-ticker-item" key={`${item.id}-${i}`} title={item.text}>
              {item.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
