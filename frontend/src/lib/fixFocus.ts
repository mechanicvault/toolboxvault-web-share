import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * The Fix-it landing (owner ruling 2026-11-05): a deep link that
 * names a problem must ARRIVE at the exact spot that fixes it —
 * "not just the edit tool screen where the user has to navigate
 * to find the problem." The health check's gap pills link to
 * hashes like `#fix-model`, `#fix-purchase-date`,
 * `#fix-piece-<id>` on the item's edit form (and `#photos` on the
 * item page); the destination page resolves its hash to an
 * element id through this hook, and the element is scrolled into
 * view, FOCUSED, and given a restrained accent highlight
 * (.tv-fix-highlight in components.css) that clears on the
 * user's first input or click — or after a few seconds, so it
 * never lingers.
 *
 * Pages load their record before the field exists, so the hook
 * polls briefly instead of assuming the element is mounted.
 */
export const FIX_HIGHLIGHT_CLASS = "tv-fix-highlight";

const FOCUSABLE =
  "input, textarea, select, button, [href], [tabindex]:not([tabindex='-1'])";

export function highlightFixTarget(el: HTMLElement): void {
  const focusEl =
    el.matches(FOCUSABLE) && !el.hasAttribute("disabled")
      ? el
      : (el.querySelector<HTMLElement>(FOCUSABLE) ?? el);
  const reduceMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({
    block: "center",
    behavior: reduceMotion ? "auto" : "smooth",
  });
  focusEl.focus({ preventScroll: true });
  el.classList.add(FIX_HIGHLIGHT_CLASS);
  const clear = () => {
    el.classList.remove(FIX_HIGHLIGHT_CLASS);
    el.removeEventListener("input", clear);
    el.removeEventListener("click", clear);
    el.removeEventListener("keydown", clear);
    window.clearTimeout(timer);
  };
  const timer = window.setTimeout(clear, 7000);
  el.addEventListener("input", clear);
  el.addEventListener("click", clear);
  el.addEventListener("keydown", clear);
}

/**
 * Resolve the current location hash to an element id and land
 * the fix highlight on it, once. `resolve` receives the hash
 * WITHOUT the leading "#"; return null for hashes the page
 * doesn't own. Polls until the element exists (forms render
 * after their record loads) or ~6 seconds pass.
 */
export function useFixFocus(
  resolve: (hash: string) => string | null,
): void {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const targetId = resolve(hash.replace(/^#/, ""));
    if (!targetId) return;
    let cancelled = false;
    let interval = 0;
    const tryOnce = () => {
      if (cancelled) return true;
      const el = document.getElementById(targetId);
      if (!el) return false;
      highlightFixTarget(el);
      return true;
    };
    if (tryOnce()) return;
    const deadline = Date.now() + 6000;
    interval = window.setInterval(() => {
      if (tryOnce() || Date.now() > deadline) {
        window.clearInterval(interval);
      }
    }, 150);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
    // `resolve` is a page-local literal; the hash is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hash]);
}
