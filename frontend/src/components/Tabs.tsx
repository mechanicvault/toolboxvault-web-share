import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
  disabled?: boolean;
}

interface TabsProps {
  tabs: TabItem[];
  /** Controlled active tab id; omit for internal state. */
  activeId?: string;
  onChange?: (id: string) => void;
  defaultActiveId?: string;
  /** Optional extra content rendered in the SAME row as the
   *  tab strip, after the tabs — a sibling of the tablist, never
   *  inside it (ARIA: a tablist holds tabs only). Inventory uses
   *  it for the starred-category shortcut links. Absent = the
   *  strip renders exactly as it always has. */
  stripExtra?: ReactNode;
  /** With `stripExtra`: render the extra BETWEEN the tabs —
   *  right after the tab with this id — instead of after all of
   *  them. The strip splits into two tablists around the extra
   *  (each still holds tabs only). Inventory's row is All ·
   *  starred categories (owner spec 2026-10-25). Absent
   *  = the extra rides after the tabs, as before. */
  stripExtraAfterId?: string;
}

/** Tab strip + panel. Accent underlines the active tab (and glows in steel).
 *
 * ARIA tab pattern (F2-10): only the active tab is in the Tab order
 * (roving tabindex); ArrowLeft/ArrowRight move focus AND selection
 * between enabled tabs, wrapping at the ends; Home/End jump. */
export function Tabs({ tabs, activeId, onChange, defaultActiveId, stripExtra, stripExtraAfterId }: TabsProps) {
  const [local, setLocal] = useState(defaultActiveId ?? tabs[0]?.id);
  const active = activeId ?? local;
  // `selected` is the tab that wears the active state; it can be
  // NONE when a controlled caller passes an activeId that matches
  // no tab (Inventory's shelf: a starred-category filter is the
  // active thing, not the "All" tab). `current` still falls back
  // to the first tab so the panel always has content to show.
  const selected = tabs.find((t) => t.id === active);
  const current = selected ?? tabs[0];
  const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function select(id: string) {
    if (activeId === undefined) setLocal(id);
    onChange?.(id);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    const enabled = tabs.filter((t) => !t.disabled);
    if (enabled.length === 0) return;
    const currentIdx = Math.max(0, enabled.findIndex((t) => t.id === current?.id));
    let nextIdx = currentIdx;
    if (e.key === "Home") nextIdx = 0;
    else if (e.key === "End") nextIdx = enabled.length - 1;
    else if (e.key === "ArrowRight") nextIdx = (currentIdx + 1) % enabled.length;
    else if (e.key === "ArrowLeft") nextIdx = (currentIdx - 1 + enabled.length) % enabled.length;
    const next = enabled[nextIdx];
    if (!next) return;
    e.preventDefault();
    select(next.id);
    btnRefs.current[next.id]?.focus();
  }

  function renderTab(tab: TabItem) {
    return (
      <button
        key={tab.id}
        ref={(el) => { btnRefs.current[tab.id] = el; }}
        role="tab"
        id={`tab-${tab.id}`}
        aria-selected={selected?.id === tab.id}
        aria-controls={`tabpanel-${tab.id}`}
        tabIndex={selected?.id === tab.id ? 0 : -1}
        disabled={tab.disabled}
        className="tv-tab"
        onClick={() => select(tab.id)}
      >
        {tab.label}
      </button>
    );
  }

  // The split strip (stripExtraAfterId): two tablists around the
  // extra, so the visual order is tabs-head · extra · tabs-tail
  // while each tablist still holds tabs only. Keyboard nav is
  // unchanged — the handler works off the full tab list and is
  // attached to both tablists.
  const splitAt =
    stripExtra && stripExtraAfterId
      ? tabs.findIndex((t) => t.id === stripExtraAfterId)
      : -1;
  const headTabs = splitAt >= 0 ? tabs.slice(0, splitAt + 1) : tabs;
  const tailTabs = splitAt >= 0 ? tabs.slice(splitAt + 1) : [];

  return (
    <div>
      <div className={stripExtra ? "tv-tabs-row tv-tabs-row--extra" : "tv-tabs-row"}>
        <div className="tv-tabs" role="tablist" aria-label="Sections" onKeyDown={onKeyDown}>
          {headTabs.map(renderTab)}
        </div>
        {stripExtra}
        {tailTabs.length > 0 && (
          <div className="tv-tabs" role="tablist" aria-label="Sections" onKeyDown={onKeyDown}>
            {tailTabs.map(renderTab)}
          </div>
        )}
      </div>
      {current && (
        <div
          className="tv-tabpanel"
          role="tabpanel"
          id={`tabpanel-${current.id}`}
          aria-labelledby={`tab-${current.id}`}
        >
          {current.content}
        </div>
      )}
    </div>
  );
}
