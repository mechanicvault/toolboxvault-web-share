import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Button, Modal, useToast } from "../../../components";
import {
  estimateMenuHeight,
  placeMenuInViewport,
  type MenuPlacement,
} from "../../../lib/menuPlacement";
import { api, ApiError } from "../../../lib/api";
import type { Battery, Standing, Tool } from "../types";
import type { ItemStatusData } from "./ItemStatusStrip";
import { ReplacedForm } from "./ReplacedForm";
import "../itemPage.css";

type MenuEntry =
  | { key: string; kind: "link"; label: string; to: string }
  | { key: string; kind: "action"; label: string; danger?: boolean; run: () => void }
  | { key: string; kind: "separator" };

/**
 * The item page's control panel (owner amendment #4,
 * 2026-10-31): ONE "Actions" button at the top-right of the
 * header zone; its dropdown carries every action a user can
 * take on the item — nothing that existed as a loose header
 * button or a panel-level flow is lost:
 *
 *   Edit · Print label · List for sale (marketplace module
 *   only) · Lend / check out — or, state-aware, Lending request
 *   / Mark returned while a loan is open · Mark broken / Back
 *   in service (the list page's bulk set_standing flow, one
 *   item; a successful Mark broken then jumps to the Claims /
 *   Replace tab — owner order 2026-11-04) · Mark lost / stolen
 *   — or Loss report while a report is open (both open the
 *   report's own modal window — owner correction, 2026-10-31:
 *   the report and the sale record no longer live in the
 *   Details tab) · Mark sold / Sale details
 *   (the sale window) · Start a claim (claims module only; opens the
 *   Claims tab's form) · Mark replaced / Clear replaced (the
 *   history marker, modal form) · Delete.
 *
 * State rules mirror the flows themselves: an item retired by
 * a claim (standing "replaced") or sold offers no lend /
 * standing / sale actions; an already-broken item offers Back
 * in service instead of Mark broken; an open loss report owns
 * recovery, so the standing shortcuts step aside for it.
 *
 * The menu rides the site's dropdown pattern (the UserMenu /
 * AddBlockMenu behavior): the trigger only discloses — it
 * never navigates; items act and close; outside click or
 * Escape closes; arrows/Home/End walk the items; the panel is
 * portaled and viewport-clamped so no ancestor can clip it.
 */
export function ItemActionsMenu({
  itemKind,
  item,
  status,
  hasModule,
  onJump,
  onChanged,
  onDelete,
  onStartClaim,
  onOpenLoss,
  onOpenSale,
  size,
}: {
  itemKind: "tool" | "battery";
  item: Tool | Battery;
  /** Trigger size: the item page uses the default; compact
   *  hosts (inventory tiles + list rows, 2026-11-05) pass "sm"
   *  so the button matches the quick action it replaced. The
   *  menu itself — entries, order, state rules — is identical
   *  wherever it rides. */
  size?: "sm";
  status: ItemStatusData | null;
  hasModule: (key: string) => boolean;
  onJump: (tab: string, anchorId?: string) => void;
  onChanged: () => void;
  onDelete: () => void;
  onStartClaim: () => void;
  /** Open the lost/stolen report's modal window (create or the
   *  open report, as the item's state dictates). */
  onOpenLoss: () => void;
  /** Open the sale modal window; "mark" starts with the
   *  record-a-sale form open, "details" with the record. */
  onOpenSale: (intent: "mark" | "details") => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<MenuPlacement | null>(null);
  const [replacedOpen, setReplacedOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const segment = itemKind === "tool" ? "tools" : "batteries";
  const standing: Standing = item.standing;

  function placeMenu() {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const r = wrap.getBoundingClientRect();
    // Placement is the shared viewport rule (lib/menuPlacement,
    // FIX 3, 2026-11-11), which generalizes this menu's own
    // 2026-11-05 flip: downward when the height fits below,
    // flipped up (bottom-anchored, so it hugs the trigger
    // whatever its true height) when the room above is
    // roomier, otherwise capped to the roomier side with
    // internal scroll — the box always lands fully inside the
    // viewport. `entries` is built below — placement runs from
    // events/effects, after it exists; once the menu is
    // mounted its real scrollHeight replaces the estimate.
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

  /** The list page's bulk standing flow, one item: POST
   *  /inventory/bulk set_standing. Its server rules (and its
   *  friendly 422 copy) apply exactly as they do in bulk.
   *
   *  Owner order 2026-11-04 22:27: marking an item broken
   *  takes the user straight to the Claims / Replace tab, so
   *  they land facing the start-a-claim panel — navigation
   *  only; the claim form is NOT auto-opened and no claim is
   *  created. When the claims module isn't effective for this
   *  user there is no tab to land on, so the user simply
   *  stays where they are. */
  async function setStanding(next: Standing, okMessage: string) {
    try {
      await api("/inventory/bulk", {
        method: "POST",
        body: JSON.stringify({
          items: [{ kind: itemKind, id: item.id }],
          action: "set_standing",
          params: { standing: next },
        }),
      });
      toast(okMessage, { tone: "success" });
      onChanged();
      if (next === "broken" && hasModule("claims")) {
        onJump("claims");
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't work.", {
        tone: "danger",
      });
    }
  }

  async function clearReplaced() {
    try {
      await api(`/inventory/${segment}/${item.id}/replaced`, {
        method: "DELETE",
      });
      toast("Replacement cleared.", { tone: "success" });
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't clear it.", {
        tone: "danger",
      });
    }
  }

  const retired = standing === "replaced";
  const sold = standing === "sold";
  const entries: MenuEntry[] = [
    {
      key: "edit",
      kind: "link",
      label: "Edit",
      to:
        itemKind === "tool"
          ? `/inventory/${item.id}/edit`
          : `/inventory/batteries/${item.id}/edit`,
    },
    {
      key: "label",
      kind: "link",
      label: "Print label",
      to: `/inventory/labels?ids=${itemKind}:${item.id}`,
    },
    ...(hasModule("marketplace")
      ? [
          {
            key: "list",
            kind: "link",
            label: "List for sale",
            to: `/marketplace/new?source=${itemKind}:${item.id}`,
          } as MenuEntry,
        ]
      : []),
    { key: "sep-1", kind: "separator" },
  ];

  if (!retired && !sold && hasModule("borrowing")) {
    if (!status?.checkout) {
      entries.push({
        key: "lend",
        kind: "action",
        label: "Lend / check out",
        run: () => onJump("borrowing", "lending"),
      });
    } else if (status.checkout.state === "requested") {
      entries.push({
        key: "lend",
        kind: "action",
        label: "Lending request",
        run: () => onJump("borrowing", "lending"),
      });
    } else {
      entries.push({
        key: "lend",
        kind: "action",
        label: "Mark returned",
        run: () => onJump("borrowing", "lending"),
      });
    }
  }

  if (!retired && !sold) {
    if (status?.lossReport) {
      entries.push({
        key: "loss",
        kind: "action",
        label: "Loss report",
        run: onOpenLoss,
      });
    } else {
      if (standing === "in_service") {
        entries.push({
          key: "broken",
          kind: "action",
          label: "Mark broken",
          run: () => void setStanding("broken", "Marked broken."),
        });
      }
      if (
        standing === "broken" ||
        standing === "in_repair" ||
        standing === "lost" ||
        standing === "stolen"
      ) {
        entries.push({
          key: "inservice",
          kind: "action",
          label: "Back in service",
          run: () => void setStanding("in_service", "Back in service."),
        });
      }
      entries.push({
        key: "loss",
        kind: "action",
        label: "Mark lost / stolen",
        run: onOpenLoss,
      });
    }
    entries.push({
      key: "sold",
      kind: "action",
      label: "Mark sold",
      run: () => onOpenSale("mark"),
    });
  }
  if (sold) {
    entries.push({
      key: "sold",
      kind: "action",
      label: "Sale details",
      run: () => onOpenSale("details"),
    });
  }

  if (hasModule("claims")) {
    entries.push({
      key: "claim",
      kind: "action",
      label: "Start a claim",
      run: onStartClaim,
    });
  }

  if (item.replaced_on) {
    entries.push({
      key: "replaced",
      kind: "action",
      label: "Clear replaced",
      run: () => void clearReplaced(),
    });
  } else if (!retired) {
    entries.push({
      key: "replaced",
      kind: "action",
      label: "Mark replaced",
      run: () => setReplacedOpen(true),
    });
  }

  entries.push(
    { key: "sep-2", kind: "separator" },
    {
      key: "delete",
      kind: "action",
      label: "Delete",
      danger: true,
      run: onDelete,
    },
  );

  const menuStyle: CSSProperties | undefined = menuPos
    ? {
        // The flipped placement must say top:"auto" out loud:
        // the .tv-menu base class carries top:calc(100% + .5rem)
        // for its in-flow life, and a flipped menu that leaves
        // `top` to the class gets over-constrained (top AND
        // bottom set) and collapses below the viewport.
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
        size={size}
      >
        Actions{" "}
        <span className="tv-item-actions-caret" aria-hidden="true">
          ▾
        </span>
      </Button>
      {open &&
        createPortal(
          <div
            className="tv-menu tv-menu--portal"
            role="menu"
            aria-label={`Actions for ${item.name}`}
            ref={menuRef}
            onKeyDown={onMenuKey}
            style={menuStyle}
          >
            {entries.map((entry) => {
              if (entry.kind === "separator") {
                return (
                  <div
                    key={entry.key}
                    className="tv-item-menu-sep"
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
      <Modal
        open={replacedOpen}
        onClose={() => setReplacedOpen(false)}
        title={`Mark “${item.name}” replaced`}
        size="sm"
      >
        <ReplacedForm
          segment={segment}
          itemId={item.id}
          toast={toast}
          onCancel={() => setReplacedOpen(false)}
          onDone={() => {
            setReplacedOpen(false);
            onChanged();
          }}
        />
      </Modal>
    </div>
  );
}
