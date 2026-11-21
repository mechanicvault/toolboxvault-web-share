import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

/**
 * Scroll management (owner directive 2026-10-22 — the named defect:
 * "click a menu button halfway down a page and the new page opens
 * halfway down it"). The router keeps the window's scroll position
 * across route changes by default; this component owns it instead:
 *
 *  - PUSH / REPLACE navigations land at the TOP of the new page,
 *    set in a layout effect so the position is right before the
 *    new page paints.
 *  - POP (browser back / forward) restores the position the user
 *    left that history entry at — positions are recorded per
 *    location key as the user scrolls. An entry with no recorded
 *    position (or recorded 0) lands at the top: mid-page is never
 *    a surprise landing.
 *  - A hash that names a real element scrolls to that element.
 *    The legacy /settings#anchor links name no element — the
 *    settings shell's own redirect turns them into section routes
 *    (a pathname change), which lands at the top like any other
 *    navigation, and then the user is on their section.
 *
 * Mounted once inside the router (App.tsx Shell), so it covers
 * the signed-in shell, the signed-out shell, settings-tree
 * navigation, and every module route uniformly.
 */
const positions = new Map<string, number>();

export default function ScrollManager() {
  const location = useLocation();
  const navType = useNavigationType();
  const keyRef = useRef(location.key);
  keyRef.current = location.key;

  // Take manual ownership of scroll restoration, and record the
  // position of the current history entry as the user scrolls
  // (rAF-throttled; the map is tiny — one entry per visited page).
  useEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        positions.set(keyRef.current, window.scrollY);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  useLayoutEffect(() => {
    if (navType === "POP") {
      const y = positions.get(location.key);
      if (y != null && y > 0) {
        window.scrollTo(0, y);
        // Lazy route content can grow the page after this paint;
        // re-assert the position as the frame settles so a
        // late-loading page doesn't strand the user at the top.
        // F2-13: the old window (rAF + 250ms) fired while async
        // lists were still a ~1,000px loading shell, so y=1,400
        // clamped to ~37 and was never retried once the real
        // 6,000px list loaded. Now: keep re-asserting — on a
        // timer AND whenever the document grows (ResizeObserver
        // on body) — until the target is actually reachable and
        // reached, or ~5s pass. A wheel / touch / key gesture
        // cancels — the user grabbing the page always wins.
        let cancelled = false;
        const cancel = () => {
          cancelled = true;
        };
        window.addEventListener("wheel", cancel, { passive: true });
        window.addEventListener("touchstart", cancel, { passive: true });
        window.addEventListener("keydown", cancel);
        const deadline = Date.now() + 5000;
        let timer = 0;
        let observer: ResizeObserver | null = null;
        const tryRestore = () => {
          if (cancelled) return;
          window.scrollTo(0, y);
          const maxY = Math.max(
            0,
            document.documentElement.scrollHeight - window.innerHeight,
          );
          if (window.scrollY >= Math.min(y, maxY) && maxY >= y) {
            stop();
          }
        };
        const stop = () => {
          cancelled = true;
          if (timer) window.clearInterval(timer);
          observer?.disconnect();
          window.removeEventListener("wheel", cancel);
          window.removeEventListener("touchstart", cancel);
          window.removeEventListener("keydown", cancel);
        };
        const raf = requestAnimationFrame(tryRestore);
        timer = window.setInterval(() => {
          if (Date.now() > deadline) { stop(); return; }
          tryRestore();
        }, 200);
        if (typeof ResizeObserver !== "undefined" && document.body) {
          observer = new ResizeObserver(() => tryRestore());
          observer.observe(document.body);
        }
        return () => {
          cancelAnimationFrame(raf);
          stop();
        };
      }
    }
    if (location.hash) {
      const el = document.getElementById(
        decodeURIComponent(location.hash.slice(1)),
      );
      if (el) {
        el.scrollIntoView();
        return;
      }
    }
    window.scrollTo(0, 0);
    return undefined;
  }, [location.key, location.pathname, location.hash, navType]);

  return null;
}
