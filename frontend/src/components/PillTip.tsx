import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * The pill tooltip (owner rule, 2026-11-05): "In any area, if a
 * pill box content is cutoff because there isn't enough room,
 * hovering over that pill box with your mouse should show a
 * popup tooltip of the whole content."
 *
 * One host, mounted once at the app root, drives every pill on
 * the site by delegation — the shared Badge (.tv-badge), the tag
 * chip (.tv-tag-chip) and the parts bin chip (.tv-bin-chip),
 * including hand-rolled badge markup (the health check's gap
 * pills are bare anchors wearing the badge classes). A pill is
 * measured AT HOVER TIME: the tooltip appears only when the
 * pill's label is genuinely truncated (its scroll width exceeds
 * its visible width, or a clipping ancestor slices the pill
 * itself), and it carries the label's full text. A
 * pill that fits shows nothing. The host never intercepts
 * clicks, so pill links and buttons keep working exactly as
 * they did; while the tooltip is up, a pill's own native title
 * (e.g. the health pills' "Fix it" hint) is stashed so the two
 * never stack, and restored when the tooltip goes away.
 */

const PILL_SELECTOR = ".tv-badge, .tv-tag-chip, .tv-bin-chip";
const LABEL_SELECTOR = ".tv-badge-label, .tv-tag-chip-label";
const SHOW_DELAY_MS = 300;
const VIEWPORT_PAD = 8;

interface TipState {
  text: string;
  /** Pill centre x (viewport coords) the tip anchors to. */
  cx: number;
  /** Distance from the viewport top for a below-pill tip. */
  top: number;
  /** Distance from the viewport bottom for an above-pill tip. */
  bottom: number;
  above: boolean;
}

function pillOf(node: EventTarget | null): HTMLElement | null {
  if (!(node instanceof Element)) return null;
  const pill = node.closest(PILL_SELECTOR);
  return pill instanceof HTMLElement ? pill : null;
}

/** True when an ancestor with a clipping overflow hides part
 *  of the pill's own box — the chips-row pattern, where the row
 *  (overflow hidden, no wrap) slices a trailing pill rather
 *  than squeezing it. */
function clippedByAncestor(pill: HTMLElement): boolean {
  const rect = pill.getBoundingClientRect();
  let el = pill.parentElement;
  while (el && el !== document.body) {
    const overflowX = getComputedStyle(el).overflowX;
    if (
      overflowX === "hidden" ||
      overflowX === "clip" ||
      overflowX === "auto" ||
      overflowX === "scroll"
    ) {
      const parent = el.getBoundingClientRect();
      if (rect.right > parent.right + 1 || rect.left < parent.left - 1) {
        return true;
      }
    }
    el = el.parentElement;
  }
  return false;
}

/** The pill's full text when — and only when — it is cut off:
 *  the label span is what truncates (the F1-06 pattern); a pill
 *  with no label span is measured on its own box; and a pill
 *  whose label fits but whose box is sliced by a clipping
 *  ancestor counts too. A 1px tolerance keeps sub-pixel
 *  rounding from crying wolf. */
function truncatedText(pill: HTMLElement): string | null {
  const label = pill.querySelector(LABEL_SELECTOR);
  const box = label ?? pill;
  const selfTruncated = box.scrollWidth - box.clientWidth > 1;
  if (!selfTruncated && !clippedByAncestor(pill)) return null;
  const text = (box.textContent ?? "").replace(/\s+/g, " ").trim();
  return text === "" ? null : text;
}

export function PillTipHost() {
  const [tip, setTip] = useState<TipState | null>(null);
  const [shiftX, setShiftX] = useState(0);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const pillRef = useRef<HTMLElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef(false);
  const stashedTitleRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    // Keep the whole tip inside the viewport: measure the
    // rendered tip and shift it off its centre anchor as needed.
    const el = tipRef.current;
    if (!el || !tip) return;
    const rect = el.getBoundingClientRect();
    let shift = 0;
    if (rect.left < VIEWPORT_PAD) shift = VIEWPORT_PAD - rect.left;
    else if (rect.right > window.innerWidth - VIEWPORT_PAD) {
      shift = window.innerWidth - VIEWPORT_PAD - rect.right;
    }
    setShiftX((prev) => (prev === shift ? prev : shift));
  }, [tip]);

  useEffect(() => {
    function clearTimer() {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }

    function hide() {
      clearTimer();
      pendingRef.current = false;
      const pill = pillRef.current;
      if (pill && stashedTitleRef.current !== null) {
        if (pill.isConnected) pill.setAttribute("title", stashedTitleRef.current);
        stashedTitleRef.current = null;
      }
      pillRef.current = null;
      setShiftX(0);
      setTip(null);
    }

    function fire(pill: HTMLElement) {
      timerRef.current = null;
      pendingRef.current = false;
      if (pillRef.current !== pill || !pill.isConnected) return;
      const text = truncatedText(pill);
      if (text === null) {
        pillRef.current = null;
        return;
      }
      // Stash the pill's own native title while ours is up.
      if (pill.hasAttribute("title")) {
        stashedTitleRef.current = pill.getAttribute("title");
        pill.removeAttribute("title");
      }
      const rect = pill.getBoundingClientRect();
      const above = rect.top > 72;
      setTip({
        text,
        cx: rect.left + rect.width / 2,
        top: rect.bottom + 8,
        bottom: window.innerHeight - rect.top + 8,
        above,
      });
    }

    function schedule(pill: HTMLElement) {
      if (pillRef.current === pill) return;
      hide();
      pillRef.current = pill;
      pendingRef.current = true;
      timerRef.current = window.setTimeout(() => fire(pill), SHOW_DELAY_MS);
    }

    function onScroll() {
      // A scroll burst while a show is pending RESTARTS the
      // delay instead of cancelling it: a hover's own
      // scroll-into-view (or a focus scroll) must not kill the
      // very tooltip it is about to earn — if the pill is
      // still under the pointer when things settle, the tip
      // still comes, and a mouseout in between cancels as
      // usual. A tooltip already on screen still hides the
      // moment anything scrolls.
      if (pendingRef.current && pillRef.current) {
        const pill = pillRef.current;
        clearTimer();
        timerRef.current = window.setTimeout(() => fire(pill), SHOW_DELAY_MS);
      } else {
        hide();
      }
    }

    function onMouseOver(event: MouseEvent) {
      const pill = pillOf(event.target);
      if (pill) schedule(pill);
      else if (pillRef.current) hide();
    }

    function onMouseOut(event: MouseEvent) {
      const pill = pillRef.current;
      if (!pill) return;
      const next = event.relatedTarget;
      if (next instanceof Node && pill.contains(next)) return;
      hide();
    }

    function onFocusIn(event: FocusEvent) {
      const pill = pillOf(event.target);
      if (pill) schedule(pill);
    }

    function onFocusOut(event: FocusEvent) {
      const pill = pillRef.current;
      if (!pill) return;
      const next = event.relatedTarget;
      if (next instanceof Node && pill.contains(next)) return;
      hide();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") hide();
    }

    document.addEventListener("mouseover", onMouseOver);
    document.addEventListener("mouseout", onMouseOut);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("mouseover", onMouseOver);
      document.removeEventListener("mouseout", onMouseOut);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", hide);
      hide();
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div
      ref={tipRef}
      className="tv-pill-tip"
      role="tooltip"
      style={{
        left: tip.cx,
        top: tip.above ? undefined : tip.top,
        bottom: tip.above ? tip.bottom : undefined,
        transform: `translateX(calc(-50% + ${shiftX}px))`,
      }}
    >
      {tip.text}
    </div>,
    document.body,
  );
}
