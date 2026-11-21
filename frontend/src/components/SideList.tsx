import type { KeyboardEvent, MouseEvent, ReactNode } from "react";

/**
 * SIDE LIST (owner's name for the pattern, 2026-11-13 — from
 * design D3): a scrolling list on the LEFT, and the clicked
 * item's full information on the RIGHT, in place — no page hop,
 * never losing your place in the list. A named, reusable site
 * pattern like Main tab layout / Main list layout: ONE shared
 * frame (this component + the .tv-sidelist-* block in
 * theme/components.css) consumed by every surface the owner
 * points it at. First uses: the Dealers page's Dealers tab and
 * Agents tab (2026-11-13).
 *
 * Anatomy: the list column is a framed, internally scrolling
 * listbox of rows (SideListRow), optionally grouped under
 * SideListGroup labels and split by a labeled SideListDivider;
 * the panel column renders whatever detail the consumer builds
 * for the selected row. Rows carry the main highlight on hover;
 * the selected row keeps a persistent version of it (accent
 * wash + inset outline + accent bar at its left edge).
 */
export function SideList({
  listLabel,
  list,
  panel,
}: {
  /** Accessible name for the listbox. */
  listLabel: string;
  /** The rows (SideListRow / SideListGroup / SideListDivider). */
  list: ReactNode;
  /** The selected item's detail, rendered in the right column. */
  panel: ReactNode;
}) {
  return (
    <div className="tv-sidelist">
      <div className="tv-sidelist-list" role="listbox" aria-label={listLabel}>
        {list}
      </div>
      <div className="tv-sidelist-panel">{panel}</div>
    </div>
  );
}

/** A labeled group of rows inside the list (e.g. "Directory"
 *  above "My companies"). The label is a quiet heading — the
 *  rows under it are the loud part. */
export function SideListGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="tv-sidelist-group">
      <p className="tv-sidelist-group-label">{label}</p>
      {children}
    </div>
  );
}

/** A labeled rule splitting the list into two populations
 *  (e.g. current agents above, former agents below). */
export function SideListDivider({ label }: { label: string }) {
  return (
    <div className="tv-sidelist-divider" role="separator" aria-label={label}>
      <span className="tv-sidelist-divider-label">{label}</span>
      <span className="tv-sidelist-divider-rule" aria-hidden="true" />
    </div>
  );
}

/** One row of the list: a leading slot (logo / avatar), the
 *  title + sub-line stack, and a trailing slot (a date, a star,
 *  a remove ×). The whole row selects; nested controls (the ×)
 *  keep their own clicks. `muted` quiets the row (the former /
 *  history population). */
export function SideListRow({
  selected,
  muted = false,
  onSelect,
  leading,
  title,
  sub,
  trailing,
}: {
  selected: boolean;
  muted?: boolean;
  onSelect: () => void;
  leading?: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  trailing?: ReactNode;
}) {
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    // Only the row itself answers Enter/Space — a nested
    // control (the remove ×) keeps its own keyboard life.
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect();
    }
  }
  function onClick(e: MouseEvent<HTMLDivElement>) {
    // A nested control (the remove ×, a link) is its own
    // target — it never also selects the row.
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea")) {
      return;
    }
    onSelect();
  }
  return (
    <div
      role="option"
      aria-selected={selected}
      tabIndex={0}
      className={`tv-sidelist-row${selected ? " tv-sidelist-row--selected" : ""}${muted ? " tv-sidelist-row--muted" : ""}`}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      {leading}
      <span className="tv-sidelist-row-main">
        <span className="tv-sidelist-row-title">{title}</span>
        {sub !== undefined && sub !== null && sub !== "" && (
          <span className="tv-sidelist-row-sub">{sub}</span>
        )}
      </span>
      {trailing !== undefined && trailing !== null && (
        <span className="tv-sidelist-row-trail">{trailing}</span>
      )}
    </div>
  );
}
