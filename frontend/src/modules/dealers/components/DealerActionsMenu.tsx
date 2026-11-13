import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Button } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import {
  estimateMenuHeight,
  placeMenuInViewport,
  type MenuPlacement,
} from "../../../lib/menuPlacement";

type MenuEntry =
  | { key: string; kind: "link"; label: string; to: string }
  | { key: string; kind: "action"; label: string; danger?: boolean; run: () => void }
  | { key: string; kind: "separator" };

/**
 * The dealer (company) page's control panel (owner amendment,
 * 2026-10-31): ONE "Actions" button at the top-right of the
 * header zone, mirroring the item pages' Actions menu — the
 * trigger only discloses; items act and close; the panel is
 * portaled and viewport-clamped; arrows/Home/End walk it.
 *
 * The entries are the company-level actions that exist for the
 * viewer of THIS company (the parent computes them):
 *   Edit company — for EVERY signed-in viewer (2026-11-05):
 *     on his OWN private company it edits the record itself
 *     (the backend's PUT is owner-only); on a directory company
 *     it edits HIS personal layer over the shared record — his
 *     values win everywhere he sees that dealer, the directory
 *     and everyone else stay untouched.
 *   Delete company — only for the viewer's OWN private
 *     companies (owner-only DELETE; directory companies are
 *     operator-curated). These controls used to live only on the
 *     Dealers page's "My companies" list; they are consolidated
 *     here WITHOUT removing them there.
 *   Open a truck account — only while the truck_accounts module
 *     is effective for the viewer AND the viewer is a verified
 *     representative of this company (the issuable-companies
 *     read); a link into the truck accounts page, where the
 *     create flow itself lives.
 *   View as visitor — only for the company's representatives
 *     on a directory company (Sweep D5): the preview of this
 *     page as a member with no relationship to it sees it.
 * Row-level actions are NOT in this menu by design: the agents'
 * Add-as-preferred / Remove buttons stay on their rows in the
 * Agents tab, and Print / Export / Email stay on the Tools tab —
 * the same exception the item pages make for list-level actions.
 * With Edit always available to a signed-in viewer, the menu
 * renders on every dealer page; the empty case below remains as
 * a guard for any future caller without an edit path.
 */
export function DealerActionsMenu({
  companyName,
  isMine,
  canIssueTruckAccount,
  onEdit,
  onDelete,
  onViewAsVisitor,
}: {
  companyName: string;
  isMine: boolean;
  canIssueTruckAccount: boolean;
  onEdit: () => void;
  onDelete: () => void;
  /** "View as visitor" (Sweep D5): present only for the
   *  company's representatives on a directory company — the
   *  door into the page's visitor preview. */
  onViewAsVisitor?: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<MenuPlacement | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  /* Shared viewport placement (lib/menuPlacement, FIX 3,
   * 2026-11-11): clamp inside the viewport, flip up when the
   * bottom runs out, cap + internal scroll — replacing the old
   * `max(160, …)` floor that could push the box off-screen.
   * `entries` is built below; placement runs after it exists,
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

  const entries: MenuEntry[] = [];
  // Edit company: every viewer (2026-11-05) — the record itself
  // on his own company, his personal layer on a directory one.
  entries.push({
    key: "edit",
    kind: "action",
    label: t("dealers.actions.edit"),
    run: onEdit,
  });
  if (onViewAsVisitor) {
    entries.push({
      key: "visitor",
      kind: "action",
      label: t("preview.viewAsVisitor"),
      run: onViewAsVisitor,
    });
  }
  if (canIssueTruckAccount) {
    entries.push({
      key: "truck",
      kind: "link",
      label: t("dealers.actions.openTruck"),
      to: "/truck-accounts",
    });
  }
  if (isMine) {
    entries.push(
      { key: "sep-delete", kind: "separator" },
      {
        key: "delete",
        kind: "action",
        label: t("dealers.actions.delete"),
        danger: true,
        run: onDelete,
      },
    );
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
        onClick={toggle}
      >
        {t("dealers.actions.title")}{" "}
        <span className="tv-dealer-actions-caret" aria-hidden="true">
          ▾
        </span>
      </Button>
      {open &&
        createPortal(
          <div
            className="tv-menu tv-menu--portal"
            role="menu"
            aria-label={t("dealers.actions.for").replace("{name}", companyName)}
            ref={menuRef}
            onKeyDown={onMenuKey}
            style={menuStyle}
          >
            {entries.map((entry) => {
              if (entry.kind === "separator") {
                return (
                  <div
                    key={entry.key}
                    className="tv-dealer-menu-sep"
                    role="separator"
                  />
                );
              }
              if (entry.kind === "link") {
                return (
                  <Link
                    key={entry.key}
                    to={entry.to}
                    className="tv-menu-item"
                    role="menuitem"
                    onClick={() => setOpen(false)}
                  >
                    {entry.label}
                  </Link>
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
