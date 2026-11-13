import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Button } from "../../components";
import {
  estimateMenuHeight,
  placeMenuInViewport,
  type MenuPlacement,
} from "../../lib/menuPlacement";

export interface SettingsActionEntry {
  key: string;
  label: string;
  run: () => void;
}

/**
 * The Settings page's ONE Actions dropdown (main tab layout,
 * 2026-11-03): the page-level control panel at the header's
 * top-right, mirroring the dealer page's DealerActionsMenu
 * mechanics — the trigger only discloses; items act and close;
 * the panel is portaled and viewport-clamped; arrows/Home/End
 * walk it.
 *
 * The entries are tab jumps, computed by the parent under the
 * same registry gates as the tabs themselves (an entry exists
 * only while its tab does). Picking one switches the tab IN
 * PLACE — the tab jumps never navigate.
 *
 * The optional `settingsEntry` is the one deliberate exception
 * (Actions → Settings, owner order 2026-11-09): when a page
 * HAS settings of its own, the parent passes its settings
 * door — the label is the dictionary's "Settings"
 * (`shell.settings`, EN+ES) and `run` goes where that page's
 * settings are edited: it navigates to the page's settings
 * section (`/settings/<section>`) or switches the page's own
 * settings tab in place, whichever seat the settings live in.
 * It renders TRAILING, set apart by a divider, and renders
 * even when it is the menu's only entry. A page with no
 * settings passes nothing and its menu is unchanged.
 *
 * A page owning SEVERAL settings sections (Inventory owns
 * four) passes `settingsEntries` + `settingsLabel` instead:
 * the same trailing seat renders a small group — the divider,
 * a non-interactive caption carrying the dictionary's
 * "Settings", then one item per section, each labeled with
 * that section's own dictionary title and running to its
 * section. The caption is not a menuitem, so keyboard walking
 * skips it like the divider. When both forms are passed the
 * group wins; pages passing neither are unchanged.
 */
export function SettingsActionsMenu({
  ariaLabel,
  buttonLabel,
  entries,
  settingsEntry,
  settingsEntries,
  settingsLabel,
  currentKey,
}: {
  ariaLabel: string;
  buttonLabel: string;
  entries: SettingsActionEntry[];
  settingsEntry?: SettingsActionEntry;
  settingsEntries?: SettingsActionEntry[];
  settingsLabel?: string;
  /** Sweep B9 (09-F9 residual): the entry for the section the
   * user is already on, when the caller knows it — that entry
   * wears a current marker (bold + a check) and aria-current,
   * so the flat jumper list says where you are. Callers that
   * pass nothing render exactly as before. */
  currentKey?: string;
}) {
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<MenuPlacement | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  /* Placement runs the shared viewport rule (lib/menuPlacement,
   * FIX 3, 2026-11-11): right-aligned to the trigger, clamped
   * inside the viewport, flipping upward when the menu would
   * run off the bottom and capped to the roomier side with
   * internal scroll — the old `max(160, …)` floor pushed low
   * triggers' menus past the bottom edge, unreachable. Once
   * the menu is mounted its real scrollHeight replaces the
   * estimate, so the side picked is the side that truly fits. */
  function placeMenu() {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const r = wrap.getBoundingClientRect();
    const rows =
      entries.length +
      (settingsEntries && settingsEntries.length > 0
        ? settingsEntries.length + (settingsLabel ? 1 : 0)
        : settingsEntry
          ? 1
          : 0);
    const seps =
      entries.length > 0 && (settingsEntries?.length || settingsEntry)
        ? 1
        : 0;
    const measured = menuRef.current?.scrollHeight;
    const estimated =
      measured && measured > 0 ? measured : estimateMenuHeight(rows, seps);
    setMenuPos(
      placeMenuInViewport(r, { width: 300, estimatedHeight: estimated }),
    );
  }

  function toggle() {
    if (!open) placeMenu();
    setOpen((v) => !v);
  }

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (wrapRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        wrapRef.current?.querySelector("button")?.focus();
      }
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", placeMenu);
    document.addEventListener("scroll", placeMenu, true);
    // The menu is mounted now: re-place with its real height
    // so a long menu (Settings' 19 sections) flips or caps
    // exactly, not by estimate.
    placeMenu();
    const items = menuRef.current?.querySelectorAll<HTMLElement>(
      '[role="menuitem"]',
    );
    if (items && items.length > 0) items[0]?.focus();
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", placeMenu);
      document.removeEventListener("scroll", placeMenu, true);
    };
  }, [open ]);

  function onMenuKey(e: React.KeyboardEvent) {
    if (
      e.key !== "ArrowDown" &&
      e.key !== "ArrowUp" &&
      e.key !== "Home" &&
      e.key !== "End"
    ) {
      return;
    }
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ??
        [],
    );
    if (items.length === 0) return;
    e.preventDefault();
    const idx = items.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? items.length - 1
          : e.key === "ArrowDown"
            ? (idx + 1) % items.length
            : (idx - 1 + items.length) % items.length;
    items[next]?.focus();
  }

  const settingsGroup =
    settingsEntries && settingsEntries.length > 0 ? settingsEntries : null;

  if (entries.length === 0 && !settingsEntry && !settingsGroup) return null;

  const menuStyle: CSSProperties | undefined = menuPos
    ? {
        // A flipped menu must say top:"auto" out loud — the
        // .tv-menu base class carries its own `top`, and a menu
        // with both top and bottom set collapses (the item
        // menu's lesson, 2026-11-05).
        top: menuPos.bottom !== undefined ? "auto" : menuPos.top,
        bottom: menuPos.bottom,
        left: menuPos.left,
        maxHeight: menuPos.maxHeight,
      }
    : undefined;

  return (
    <div ref={wrapRef}>
      <Button
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        {buttonLabel}{" "}
        <span className="tv-settings-actions-caret" aria-hidden="true">
          ▾
        </span>
      </Button>
      {open &&
        createPortal(
          <div
            className="tv-menu tv-menu--portal"
            role="menu"
            aria-label={ariaLabel}
            ref={menuRef}
            onKeyDown={onMenuKey}
            style={menuStyle}
          >
            {entries.map((entry) => (
              <button
                key={entry.key}
                type="button"
                className={
                  entry.key === currentKey
                    ? "tv-menu-item tv-menu-item--current"
                    : "tv-menu-item"
                }
                role="menuitem"
                aria-current={entry.key === currentKey ? "true" : undefined}
                onClick={() => {
                  setOpen(false);
                  entry.run();
                }}
              >
                {entry.label}
              </button>
            ))}
            {settingsGroup ? (
              <>
                {entries.length > 0 ? (
                  <div className="tv-menu-sep" role="separator" />
                ) : null}
                {settingsLabel ? (
                  <div className="tv-menu-group-label" aria-hidden="true">
                    {settingsLabel}
                  </div>
                ) : null}
                {settingsGroup.map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    className="tv-menu-item"
                    role="menuitem"
                    onClick={() => {
                      setOpen(false);
                      entry.run();
                    }}
                  >
                    {entry.label}
                  </button>
                ))}
              </>
            ) : settingsEntry ? (
              <>
                {entries.length > 0 ? (
                  <div className="tv-menu-sep" role="separator" />
                ) : null}
                <button
                  type="button"
                  className="tv-menu-item"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    settingsEntry.run();
                  }}
                >
                  {settingsEntry.label}
                </button>
              </>
            ) : null}
          </div>,
          document.body,
        )}
    </div>
  );
}
