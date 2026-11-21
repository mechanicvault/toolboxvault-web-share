/**
 * Viewport-safe placement for portaled dropdown menus (FIX 3,
 * main-fixes program, 2026-11-11).
 *
 * The defect family: menus positioned `top: trigger.bottom + 8`
 * with `maxHeight: max(160, vh - top - 8)` — when the trigger
 * sits low in the viewport the forced 160px floor (or the
 * menu's full height) ran past the bottom edge, fixed-position
 * and unreachable; one hand-rolled menu was anchored to a
 * container whose right edge sat mid-screen, so it opened off
 * the LEFT edge. The kit menus that fit were the ones that
 * already flipped/clamped.
 *
 * This is the ONE placement rule every portaled menu now runs:
 *  - Horizontally the menu's right edge aligns to the trigger's
 *    right edge, clamped so the whole box sits inside the
 *    viewport with an 8px margin on both sides.
 *  - Vertically it opens downward when the estimated height
 *    fits below the trigger; otherwise it flips upward when
 *    there is more room above; otherwise it opens toward the
 *    roomier side capped to that side's space, and the menu's
 *    own internal scroll (`.tv-menu--portal` already scrolls)
 *    reaches the last item.
 *  - `maxHeight` NEVER exceeds the space on the chosen side, so
 *    the rendered box is always fully inside the viewport.
 *  - When there is room, placement is exactly what it was
 *    before (below the trigger, right-aligned, 8px gap) —
 *    desktop rendering is unchanged.
 *
 * Callers pass an estimated content height (item count × row
 * height is enough — the estimate only picks the side; the
 * cap keeps the box in-viewport either way) and may re-run
 * placement once the menu is mounted with its real
 * `scrollHeight` for an exact decision.
 */
export interface MenuPlacement {
  /** Set when the menu opens downward: distance from the
   *  viewport top to the menu's top edge. */
  top?: number;
  /** Set when the menu flips upward: distance from the
   *  viewport bottom to the menu's bottom edge (the CSS
   *  `bottom` value). Anchor with `bottom` (not a computed
   *  `top`) so the menu hugs the trigger whatever its true
   *  height — and say `top: "auto"` in the style, because the
   *  `.tv-menu` base class carries a `top` of its own. */
  bottom?: number;
  /** Distance from the viewport left edge to the menu's left
   *  edge, already clamped inside the viewport margins. */
  left: number;
  /** Height cap for the chosen side; the menu scrolls inside
   *  it when its content is taller. */
  maxHeight: number;
}

const GAP = 8;
const MARGIN = 8;

export function placeMenuInViewport(
  trigger: { top: number; bottom: number; right: number },
  opts: { width: number; estimatedHeight: number },
): MenuPlacement {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(opts.width, Math.max(0, vw - MARGIN * 2));
  const left = Math.max(
    MARGIN,
    Math.min(trigger.right - width, vw - width - MARGIN),
  );
  const spaceBelow = Math.max(0, vh - trigger.bottom - GAP - MARGIN);
  const spaceAbove = Math.max(0, trigger.top - GAP - MARGIN);
  if (opts.estimatedHeight <= spaceBelow) {
    return { top: trigger.bottom + GAP, left, maxHeight: spaceBelow };
  }
  if (spaceAbove >= spaceBelow) {
    return {
      bottom: vh - trigger.top + GAP,
      left,
      maxHeight: spaceAbove,
    };
  }
  return { top: trigger.bottom + GAP, left, maxHeight: spaceBelow };
}

/** Rough content height for a `.tv-menu` list: rows are ~38px,
 *  separators ~9px, plus the panel's own padding. Only used to
 *  pick a side — the cap does the guaranteeing. */
export function estimateMenuHeight(rows: number, separators = 0): number {
  return rows * 38 + separators * 9 + 16;
}
