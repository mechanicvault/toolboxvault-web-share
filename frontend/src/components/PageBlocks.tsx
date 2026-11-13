import { useEffect, useRef, useState, type ReactNode } from "react";

import { useT } from "../i18n/LocaleContext";
import type { BlockSize, ResolvedBlock } from "../lib/usePageLayout";
import { AddBlockMenu } from "./AddBlockMenu";
import { SlidersIcon } from "./icons";

export interface PageBlocksProps {
  /** Ordered, group-filtered blocks from usePageLayout. */
  blocks: ResolvedBlock[];
  /**
   * Customize mode (Home + Header program, owner 2026-10-24;
   * Phase C, 2026-10-24): every SHOWN block wears a chrome bar
   * with a red X that removes it and a drag grip; removed blocks
   * leave the page entirely and wait in the ADD dropdown, which
   * lists exactly the boxes NOT currently shown. Dragging is the
   * ONLY reorder path — the old up/down arrow buttons are gone
   * (owner: "the arrows are not needed — drag and drop does the
   * job"). The ADD dropdown lives at the TOP: in the first shown
   * block's chrome bar, immediately right of the drag grip (and
   * in the page's tools row — CorePage renders the same shared
   * AddBlockMenu there). There is no bottom Add.
   */
  editing?: boolean;
  /** Remove a block from the page (the red X). */
  onRemove?: (key: string) => void;
  /** Put a removed block back (an ADD dropdown pick). */
  onAdd?: (key: string) => void;
  /** Drag reorder: the full new key order. */
  onReorder?: (keys: string[]) => void;
  /**
   * Set a block's grid width (widget options Wave 1): the
   * options popover's Half | Full choice, live-editing the
   * caller's draft. When omitted, the popover offers no size
   * section (a page without resizable blocks).
   */
  onSetSize?: (key: string, size: BlockSize) => void;
  /**
   * The block's registered per-widget option sections (widget
   * options registry — modules/core/widgetOptions), rendered
   * inside the options popover under the size choice. Null =
   * the block has no options of its own (Wave 1: every block).
   */
  renderOptions?: (block: ResolvedBlock) => ReactNode;
}

/**
 * One block's options popover (widget options Wave 1, owner
 * design 2026-11-02): anchored to the block's own chrome bar —
 * it floats over the page right where the box is (the Add
 * menu's family: outside click or Escape closes it), never a
 * separate settings page, never a swapped-in manager. The
 * universal section is the Half | Full width choice every block
 * carries; the block's registered option sections render under
 * it. Every control live-edits the Edit-view draft — Save keeps
 * the changes, Cancel throws them away, like moving and
 * removing boxes.
 */
function BlockOptions({
  block,
  onSetSize,
  extra,
}: {
  block: ResolvedBlock;
  onSetSize?: (size: BlockSize) => void;
  extra?: ReactNode;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open ]);

  if (!onSetSize && !extra) return null;
  const label = `${t("home.options")}: ${block.title}`;
  return (
    <div className="tv-block-opts" ref={ref}>
      <button
        type="button"
        className="tv-block-opts-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        title={t("home.options")}
        onClick={() => setOpen((o) => !o)}
      >
        <SlidersIcon size={15} />
      </button>
      {open && (
        <div className="tv-block-opts-pop" role="dialog" aria-label={label}>
          {onSetSize && (
            <div className="tv-block-opts-group">
              <span className="tv-block-opts-label">{t("home.boxWidth")}</span>
              <div
                className="tv-opts-size"
                role="group"
                aria-label={t("home.boxWidth")}
              >
                <button
                  type="button"
                  aria-pressed={block.size === "half"}
                  onClick={() => onSetSize("half")}
                >
                  {t("home.widthHalf")}
                </button>
                <button
                  type="button"
                  aria-pressed={block.size === "full"}
                  onClick={() => onSetSize("full")}
                >
                  {t("home.widthFull")}
                </button>
              </div>
            </div>
          )}
          {extra}
        </div>
      )}
    </div>
  );
}

/**
 * Renders a page's blocks (see lib/usePageLayout for the system).
 * Outside customize mode this is near-invisible plumbing: visible
 * blocks render in order, each inside a slot that carries the
 * block's resolved width to the grid (widget options Wave 1 —
 * the slot is layout-only flex, so the block's own box keeps
 * today's exact rendering). In customize mode each shown block
 * wears its chrome bar inside the same slot, and the ADD
 * dropdown (first bar + the page's tools row) closes the loop.
 */
export function PageBlocks({
  blocks,
  editing = false,
  onRemove,
  onAdd,
  onReorder,
  onSetSize,
  renderOptions,
}: PageBlocksProps) {
  const t = useT();
  const [dragKey, setDragKey] = useState<string | null>(null);

  if (!editing) {
    return (
      <>
        {blocks
          .filter((b) => b.visible)
          .map((b) => (
            <div key={b.key} className="tv-block-slot" data-size={b.size}>
              {b.render()}
            </div>
          ))}
      </>
    );
  }

  const shown = blocks.filter((b) => b.visible);
  const hidden = blocks.filter((b) => !b.visible);

  const dropOn = (targetKey: string) => {
    if (!dragKey || dragKey === targetKey) return;
    const keys = blocks.map((b) => b.key);
    const from = keys.indexOf(dragKey);
    const to = keys.indexOf(targetKey);
    if (from < 0 || to < 0) return;
    keys.splice(from, 1);
    keys.splice(to, 0, dragKey);
    onReorder?.(keys);
    setDragKey(null);
  };

  return (
    <>
      {shown.map((b, i) => (
        <div key={b.key} className="tv-block-slot" data-size={b.size}>
          <div
            className="tv-block-frame"
            data-block-key={b.key}
            data-dragging={dragKey === b.key || undefined}
            draggable
            onDragStart={(e) => {
              // Interactive children keep their own gestures —
              // a drag only starts from the frame's dead ground or
              // its chrome bar.
              if (
                (e.target as HTMLElement).closest(
                  "a, button, input, select, textarea, [contenteditable]",
                ) &&
                !(e.target as HTMLElement).closest(".tv-block-bar")
              ) {
                e.preventDefault();
                return;
              }
              setDragKey(b.key);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              dropOn(b.key);
            }}
            onDragEnd={() => setDragKey(null)}
          >
            <div className="tv-block-bar">
              <span className="tv-block-grip" aria-hidden="true" title={t("home.dragToMove")}>
                ⠿
              </span>
              {i === 0 && (
                <AddBlockMenu
                  items={hidden.map((h) => ({ key: h.key, title: h.title }))}
                  onAdd={(key) => onAdd?.(key)}
                />
              )}
              <strong>{b.title}</strong>
              <span className="tv-block-spacer" />
              <BlockOptions
                block={b}
                onSetSize={
                  onSetSize ? (size) => onSetSize(b.key, size) : undefined
                }
                extra={renderOptions?.(b)}
              />
              <button
                type="button"
                className="tv-box-x"
                aria-label={`${t("home.remove")}: ${b.title}`}
                title={t("home.remove")}
                onClick={() => onRemove?.(b.key)}
              >
                −
              </button>
            </div>
            <div>{b.render()}</div>
          </div>
        </div>
      ))}
    </>
  );
}
