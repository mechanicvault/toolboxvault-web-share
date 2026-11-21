import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Button } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import {
  estimateMenuHeight,
  placeMenuInViewport,
  type MenuPlacement,
} from "../../lib/menuPlacement";
import "./claims.css";

export type ClaimMenuEntry =
  | { key: string; kind: "action"; label: string; danger?: boolean; run: () => void }
  | { key: string; kind: "separator" };

/**
 * A claim detail page's control panel (sweep C3, 2026-11-12):
 * ONE "Actions" button at the top-right of the record header —
 * the main-tab record layout's seat, mirroring the item and
 * dealer pages' Actions menus (ItemActionsMenu /
 * DealerActionsMenu mechanics): the trigger only discloses;
 * items act and close; the panel is portaled and
 * viewport-clamped; arrows/Home/End walk it.
 *
 * The parent computes the entries from the claim's own state
 * (its status ladder, its allowed transitions, the package
 * doors, archive, draft delete), so the menu is state-aware
 * exactly the way the scattered header buttons it replaces
 * were — nothing is offered that the old page didn't offer
 * this seat on this claim.
 */
export function ClaimActionsMenu({
  claimNumber,
  entries,
  disabled,
}: {
  claimNumber: string;
  entries: ClaimMenuEntry[];
  disabled?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<MenuPlacement | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  /* Shared viewport placement (lib/menuPlacement, FIX 3,
   * 2026-11-11): clamp inside the viewport, flip up when the
   * bottom runs out, cap + internal scroll. `entries` is built
   * below by the parent prop; placement runs after it exists,
   * and re-runs once mounted with the menu's real height. */
  function placeMenu() {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const r = wrap.getBoundingClientRect();
    const measured = menuRef.current?.scrollHeight;
    const estimated =
      measured && measured > 0
        ? measured
        : estimateMenuHeight(
            entries.length,
            entries.filter((e) => e.kind === "separator").length,
          );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (entries.length === 0) return null;

  const menuStyle: CSSProperties | undefined = menuPos
    ? {
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
        disabled={disabled}
        onClick={toggle}
      >
        {t("inventory.actions")}{" "}
        <span className="tv-claim-actions-caret" aria-hidden="true">
          ▾
        </span>
      </Button>
      {open &&
        createPortal(
          <div
            className="tv-menu tv-menu--portal"
            role="menu"
            aria-label={t("claims.detail.actionsFor").replace(
              "{number}",
              claimNumber,
            )}
            ref={menuRef}
            onKeyDown={onMenuKey}
            style={menuStyle}
          >
            {entries.map((entry) => {
              if (entry.kind === "separator") {
                return (
                  <div
                    key={entry.key}
                    className="tv-menu-sep"
                    role="separator"
                  />
                );
              }
              return (
                <button
                  key={entry.key}
                  type="button"
                  className={`tv-menu-item${entry.danger ? " tv-menu-item-danger" : ""}`}
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    entry.run();
                  }}
                >
                  {entry.label}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </div>
  );
}
