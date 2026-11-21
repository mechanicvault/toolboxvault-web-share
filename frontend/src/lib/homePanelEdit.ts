import { useSyncExternalStore } from "react";

/**
 * HOME PANEL EDIT BRIDGE (Phase C, 2026-10-24).
 *
 * The Home side panel renders in the app shell (AppShell's aside),
 * OUTSIDE CorePage — but its customization session is CorePage's
 * home layout session (same Edit view, same Cancel/Save). This
 * tiny module-level store is the bridge: CorePage publishes the
 * panel draft (hidden keys + order) and the edit callbacks while
 * its layout session is live; HomePanel subscribes and renders
 * either the saved panel layout (not editing) or the draft with
 * its mini chrome (editing). When CorePage unmounts, it clears the
 * bridge and the panel falls back to its own saved-layout read.
 *
 * Panel sections are stable keys, all-groups eligible: every
 * section serves every account group (the stats SECTION's rows
 * already self-gate per module inside HomePanel). NOTE for future
 * gated entries: a section that only some groups/modules may use
 * must filter by the user's effective modules/groups before it is
 * offered here — never offer an ineligible section in the Add menu.
 */
export const PANEL_SECTIONS: { key: string; title: string }[] = [
  { key: "account", title: "Account" },
  { key: "stats", title: "Overview stats" },
  { key: "utility", title: "Search & latest" },
];

export const PANEL_DEFAULT_ORDER: string[] = PANEL_SECTIONS.map((s) => s.key);

export interface HomePanelEditState {
  editing: boolean;
  /** Section keys hidden in the current draft. */
  hidden: string[];
  /** Section keys in draft display order (may be partial). */
  order: string[];
  hide: (key: string) => void;
  show: (key: string) => void;
  reorder: (keys: string[]) => void;
  /** Phase 3: the panel stat PICKS in draft display order, or
   *  null when the user has never customized their stat rows
   *  (the panel then renders its default rows, and the first
   *  stat gesture materializes a concrete list through
   *  setStatOrder). Independent of the Overview block's picks —
   *  the panel's list is its own. */
  statOrder: string[] | null;
  setStatOrder: (keys: string[]) => void;
}

const IDLE: HomePanelEditState = {
  editing: false,
  hidden: [],
  order: [],
  hide: () => undefined,
  show: () => undefined,
  reorder: () => undefined,
  statOrder: null,
  setStatOrder: () => undefined,
};

let current: HomePanelEditState = IDLE;
const listeners = new Set<() => void>();

export function publishHomePanelEdit(state: HomePanelEditState | null): void {
  const next = state ?? IDLE;
  if (
    current.editing === next.editing &&
    current.hidden === next.hidden &&
    current.order === next.order &&
    current.hide === next.hide &&
    current.show === next.show &&
    current.reorder === next.reorder &&
    current.statOrder === next.statOrder &&
    current.setStatOrder === next.setStatOrder
  ) {
    return;
  }
  current = next;
  for (const fn of listeners) fn();
}

export function useHomePanelEdit(): HomePanelEditState {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    () => current,
    () => current,
  );
}

/** Resolve section keys into render order: saved/draft order
 *  leads, anything unlisted follows in registry order; unknown
 *  keys drop out. */
export function resolvePanelOrder(order: readonly string[]): string[] {
  const known = new Set(PANEL_DEFAULT_ORDER);
  const out: string[] = [];
  for (const k of order) {
    if (known.has(k) && !out.includes(k)) out.push(k);
  }
  for (const k of PANEL_DEFAULT_ORDER) {
    if (!out.includes(k)) out.push(k);
  }
  return out;
}
