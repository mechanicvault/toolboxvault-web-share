import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../../lib/api";
import {
  Button,
  Panel,
  QuietSkeleton,
  useToast,
} from "../../../components";
import { ArtIcon, type ArtName } from "../../../components/ArtIcon";
import type { Battery, HistoryEvent, ItemHistory, Tool } from "../types";
import { displayDate } from "../format";
import "../itemPage.css";

/** Asset history (owner spec 2026-10-20): the item's life story as
 *  one timeline — every module's registered providers merged
 *  server-side. Icon per kind, relative + absolute dates.
 *
 *  READ-ONLY by owner directive (2026-10-31): the Audit tab shows
 *  the entries plus a sort-direction toggle — newest first by
 *  default (the site's standing convention), flippable to oldest
 *  first. The mark/clear-replaced control that used to live here
 *  moved to the item page's header action set
 *  (MarkReplacedControl); the replaced milestone itself still
 *  renders below as a timeline entry, like every other event. */
export function HistoryPanel({
  itemKind,
  item,
}: {
  itemKind: "tool" | "battery";
  item: Tool | Battery;
}) {
  const { toast } = useToast();
  const [history, setHistory] = useState<ItemHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [ascending, setAscending] = useState(false);
  const segment = itemKind === "tool" ? "tools" : "batteries";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<ItemHistory>(
        `/inventory/${segment}/${item.id}/history`
      );
      setHistory(data);
    } catch (err) {
      if (err instanceof ApiError) toast(err.message, { tone: "danger" });
      else toast("Couldn't load the history.", { tone: "danger" });
    } finally {
      setLoading(false);
    }
  }, [item.id, segment, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const events = history?.events ?? [];
  const ordered = ascending ? [...events].reverse() : events;

  return (
    <Panel
      title="History"
      actions={
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setAscending((a) => !a)}
          title="Flip the order of the history entries"
        >
          {ascending ? "Oldest first" : "Newest first"}
        </Button>
      }
    >
      {/* Sweep B2-F18: the loading skeleton carries its words —
          two anonymous bars told the user nothing about what was
          coming. */}
      {loading && (
        <div role="status">
          <p className="tv-history-loading-note">Loading history…</p>
          <QuietSkeleton lines={2} />
        </div>
      )}
      {!loading && events.length === 0 && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          No history yet beyond purchase.
        </p>
      )}
      {!loading && events.length > 0 && (
        <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {ordered.map((event, index) => (
            <HistoryRow key={`${event.ts}-${index}`} event={event} />
          ))}
        </ol>
      )}
    </Panel>
  );
}

/** One timeline row: icon per kind, title, relative + absolute
 *  dates, the detail line, and the deep link where one exists. */
function HistoryRow({ event }: { event: HistoryEvent }) {
  const art = kindIcon(event.kind);
  return (
    <li
      style={{
        display: "flex",
        gap: "0.7rem",
        padding: "0.5rem 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span
        style={{
          color: "var(--accent)",
          marginTop: "0.1rem",
          flexShrink: 0,
        }}
        aria-hidden="true"
      >
        <ArtIcon name={art} size={20} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>
          {event.link ? (
            <Link
              to={event.link}
              style={{ color: "var(--accent)", textDecoration: "none" }}
            >
              {event.title}
            </Link>
          ) : (
            event.title
          )}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {timeAgo(event.ts)} · {displayDate(event.ts)}
        </div>
        {event.detail && (
          <div
            style={{
              color: "var(--text-muted)",
              fontSize: "0.9rem",
              marginTop: "0.1rem",
            }}
          >
            {event.detail}
          </div>
        )}
      </div>
    </li>
  );
}

/** Kind → glyph (decorative: the title always carries the
 *  meaning). Unknown future kinds (wave 2 sales) fall back to
 *  the box rather than breaking the render. */
function kindIcon(kind: string): ArtName {
  switch (kind) {
    case "created":
      return "inventory";
    case "purchased":
      return "money";
    case "edited":
      return "tag";
    case "standing":
    case "lost":
      return "warning";
    case "repair":
    case "service":
      return "repairs";
    case "lent":
      return "people";
    case "returned":
    case "replaced":
      return "borrowing";
    case "claim":
    case "warranty":
      return "claims";
    case "recovered":
      return "home";
    default:
      return "inventory";
  }
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} mo ago`;
  const years = Math.floor(months / 12);
  return `${years} yr${years === 1 ? "" : "s"} ago`;
}
