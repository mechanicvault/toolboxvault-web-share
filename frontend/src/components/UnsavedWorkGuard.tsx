import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import { Button } from "./Button";
import { Modal } from "./Modal";

/**
 * Unsaved-work guard for the PAGE wizards (Deep Audit Round 2
 * B-08). The claim wizard is a modal and has always asked before
 * discarding typed work (see ClaimWizard's requestClose + its
 * "Unsaved claim work" confirm); the Add Tool / Add Battery /
 * Add Dealer page wizards lost everything silently — Cancel, a
 * nav click, browser Back, a closed tab. This hook gives the
 * pages the claim wizard's behavior in the claim wizard's voice:
 * the same small confirm (Keep editing / Discard), the same
 * rule that PRISTINE work exits silently, and no second pattern.
 *
 * Why hand-rolled: the app rides the plain <BrowserRouter>, and
 * react-router's useBlocker only exists on data routers. The
 * guard therefore works at the seams every exit must cross —
 *
 *  - the wizard's own exit controls call requestExit();
 *  - in-app link clicks are intercepted at the document in the
 *    capture phase (before the router sees them) while dirty;
 *  - browser Back is fenced by a sentinel history entry pushed
 *    (same URL, router state preserved) the moment the draft
 *    turns dirty: Back pops the sentinel, the router's own
 *    index math reads delta 0 and nothing moves, and the
 *    confirm opens with the page — and the typed work — intact
 *    behind it. Discard removes the sentinel, then goes Back
 *    for real. Forward and Back-spam are absorbed the same way:
 *    each pop re-arms one sentinel while the confirm is up;
 *  - tab close / reload ride the platform's beforeunload
 *    prompt (its wording is the browser's, not ours).
 *
 * Deliberate non-goals, mirroring the shipped wizard semantics:
 * the per-page Skip button is an in-flow choice that drops one
 * section's input BY DESIGN — it never comes near this guard,
 * and neither do internal step moves (state changes, not
 * navigations). Programmatic navigations fired by the shell
 * itself (sign-out, account gates) are not intercepted either;
 * every user-driven exit is.
 */

const GUARD_STATE_KEY = "__tvUnsavedGuard";

/* Style objects passed by reference, never inline literals —
 * the inline-style ratchet (F3-01) counts literal style props,
 * and the claim wizard's confirm layout is reproduced without
 * adding any. */
const spacerStyle = { flex: 1 } as const;
const bodyStyle = { margin: 0 } as const;

/**
 * Dirty tracking by baseline snapshot: the wizard serializes
 * its whole draft (see the call sites for what counts) and this
 * hook captures the settled initial serialization as the
 * baseline. Anything differing from it is entered work —
 * including lookup autofill, which lands in the same draft
 * fields the user types into. Reverting every field back to
 * the baseline reads pristine again, exactly like the claim
 * wizard's incident comparison.
 *
 * `ready` is the wizard's "initial state has settled" signal
 * (account resolved, defaults applied, vocabulary loaded). The
 * snapshot itself is read a beat later off the latest value,
 * so the same commit's follow-on state updates (defaults,
 * force-included sections) land inside the baseline, never
 * outside it.
 */
export function useDraftDirty(serialized: string, ready: boolean): boolean {
  const baselineRef = useRef<string | null>(null);
  const latestRef = useRef(serialized);
  latestRef.current = serialized;
  useEffect(() => {
    if (!ready || baselineRef.current !== null) return;
    const timer = window.setTimeout(() => {
      if (baselineRef.current === null) {
        baselineRef.current = latestRef.current;
      }
    }, 50);
    return () => window.clearTimeout(timer);
  }, [ready]);
  return baselineRef.current !== null && serialized !== baselineRef.current;
}

export interface UnsavedWorkGuard {
  /** The confirm dialog node — render it inside the page. */
  dialog: ReactNode;
  /** Route a voluntary exit (a control that navigates away)
   *  through the guard: pristine exits at once, dirty asks. */
  requestExit: (go: () => void) => void;
  /** The work is saved (or otherwise no longer the user's to
   *  lose): stand the guard down for good, sentinel included. */
  disarm: () => void;
}

export function useUnsavedWorkGuard(
  dirty: boolean,
  fallbackPath: string,
): UnsavedWorkGuard {
  const t = useT();
  const navigate = useNavigate();
  const [pendingGo, setPendingGo] = useState<(() => void) | null>(null);

  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const disarmedRef = useRef(false);
  const pendingGoRef = useRef<(() => void) | null>(null);
  const pathRef = useRef(window.location.pathname);
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const fallbackRef = useRef(fallbackPath);
  fallbackRef.current = fallbackPath;
  const sentinelIdRef = useRef(
    `guard-${Math.random().toString(36).slice(2)}`,
  );
  const suppressPopRef = useRef(false);
  const popWaiterRef = useRef<(() => void) | null>(null);

  /* ---- the sentinel ------------------------------------------ */

  function isSentinelCurrent(): boolean {
    const state = window.history.state as Record<string, unknown> | null;
    return state?.[GUARD_STATE_KEY] === sentinelIdRef.current;
  }

  function pushSentinel() {
    if (isSentinelCurrent()) return;
    try {
      window.history.pushState(
        {
          ...(window.history.state ?? {}),
          [GUARD_STATE_KEY]: sentinelIdRef.current,
        },
        "",
      );
    } catch {
      /* pushState can refuse (sandboxed frame): the remaining
       * seams (clicks, controls, beforeunload) still guard. */
    }
  }

  /** Pop the sentinel off the stack, then run `after`. When the
   *  sentinel is not the current entry there is nothing to pop
   *  and `after` runs at once. The pop is ours: the popstate
   *  handler recognizes it via suppressPopRef and hands over to
   *  the waiter instead of treating it as an exit attempt. */
  function removeSentinelThen(after?: () => void) {
    if (!isSentinelCurrent()) {
      after?.();
      return;
    }
    const waiter = after ?? null;
    popWaiterRef.current = waiter;
    suppressPopRef.current = true;
    window.history.back();
    /* Belt and braces: if the pop somehow never lands, do not
     * leave the exit hanging on it. */
    window.setTimeout(() => {
      if (popWaiterRef.current === waiter && waiter) {
        popWaiterRef.current = null;
        suppressPopRef.current = false;
        waiter();
      }
    }, 300);
  }

  /* ---- exits -------------------------------------------------- */

  /** Stand down and leave: sentinel out first so the stack the
   *  user backs through afterwards holds no phantom entry. */
  function leaveCleanly(go: () => void) {
    disarmedRef.current = true;
    pendingGoRef.current = null;
    setPendingGo(null);
    removeSentinelThen(go);
  }

  /** The way out after a browser-Back attempt is confirmed:
   *  back one real entry when the app has one (idx is the
   *  router's own numbering), else the wizard's cancel target. */
  function goBackForReal() {
    const state = window.history.state as { idx?: unknown } | null;
    if (typeof state?.idx === "number" && state.idx > 0) {
      window.history.back();
    } else {
      navigateRef.current(fallbackRef.current, { replace: true });
    }
  }

  function requestExit(go: () => void) {
    if (disarmedRef.current || !dirtyRef.current) {
      leaveCleanly(go);
      return;
    }
    pendingGoRef.current = go;
    setPendingGo(() => go);
  }

  function keepEditing() {
    pendingGoRef.current = null;
    setPendingGo(null);
  }

  function confirmDiscard() {
    const go = pendingGoRef.current ?? goBackForReal;
    leaveCleanly(go);
  }

  function disarm() {
    disarmedRef.current = true;
    pendingGoRef.current = null;
    setPendingGo(null);
    /* NOT the pop removal leaveCleanly uses: after a save the
     * PAGE navigates on its own schedule — sometimes within the
     * same microtask chain (the dealer wizard's skip-agent path
     * has no await left) — and a pop still in flight would land
     * AFTER that navigation and bounce the user back onto a
     * fresh wizard. Detagging the sentinel in place is
     * synchronous: the entry keeps the router's own state (it
     * becomes a plain duplicate of the wizard's entry) and the
     * save's replace-navigation rewrites it, race-free. The one
     * wart: after a save, one Back lands on a fresh wizard
     * before the page before it — visible, harmless, and the
     * same on every save path. */
    if (isSentinelCurrent()) {
      try {
        const state = {
          ...(window.history.state as Record<string, unknown>),
        };
        delete state[GUARD_STATE_KEY];
        window.history.replaceState(state, "");
      } catch {
        /* a refused replaceState leaves a tagged entry behind:
         * the guard is disarmed, so it can never fire — it just
         * sits in the stack as the duplicate described above. */
      }
    }
  }

  /* ---- the seams (registered once; gated on refs) ------------ */

  useEffect(() => {
    function onPopState() {
      if (suppressPopRef.current) {
        suppressPopRef.current = false;
        const waiter = popWaiterRef.current;
        popWaiterRef.current = null;
        waiter?.();
        return;
      }
      if (disarmedRef.current || !dirtyRef.current) return;
      /* A pop that landed somewhere else was a real navigation
       * (a multi-entry history jump, say): this page is on its
       * way out and the confirm cannot follow it. Pops that
       * land HERE consumed the sentinel — an exit attempt. */
      if (window.location.pathname !== pathRef.current) return;
      if (!pendingGoRef.current) {
        pendingGoRef.current = goBackForReal;
        setPendingGo(() => goBackForReal);
      }
      /* Re-arm: the pop ate the sentinel, put one back so the
       * next Back is fenced too while the user decides. */
      pushSentinel();
    }

    function onDocumentClick(e: MouseEvent) {
      if (disarmedRef.current || !dirtyRef.current || pendingGoRef.current)
        return;
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)
        return;
      const target = e.target as HTMLElement | null;
      const anchor = target?.closest?.("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || anchor.hasAttribute("download")) return;
      if (anchor.target && anchor.target !== "_self") return;
      let url: URL;
      try {
        url = new URL(href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      /* Same-path links (in-page anchors, query tweaks) never
       * unmount the wizard — not exits. */
      if (url.pathname === window.location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      const destination = `${url.pathname}${url.search}${url.hash}`;
      pendingGoRef.current = () => navigateRef.current(destination);
      setPendingGo(() => pendingGoRef.current);
    }

    function onBeforeUnload(e: BeforeUnloadEvent) {
      if (disarmedRef.current || !dirtyRef.current) return;
      e.preventDefault();
      e.returnValue = "";
    }

    window.addEventListener("popstate", onPopState);
    document.addEventListener("click", onDocumentClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("popstate", onPopState);
      document.removeEventListener("click", onDocumentClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
      /* Leaving with the sentinel still on top (a shell-driven
       * unmount): pop it quietly — it carries this page's URL,
       * so nothing visible moves. */
      if (isSentinelCurrent()) {
        suppressPopRef.current = true;
        window.history.back();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* The sentinel rides the dirty flag: pushed the moment work
   *  exists, quietly removed if the draft returns to pristine
   *  (every field reverted) so Back is a real Back again. */
  useEffect(() => {
    if (disarmedRef.current) return;
    if (dirty) {
      pushSentinel();
    } else if (isSentinelCurrent()) {
      removeSentinelThen(undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  const dialog = (
    <Modal
      open={pendingGo !== null}
      onClose={keepEditing}
      title={t("common.unsavedWork.title")}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={keepEditing}>
            {t("common.unsavedWork.keepEditing")}
          </Button>
          <span style={spacerStyle} />
          <Button variant="danger" onClick={confirmDiscard}>
            {t("common.unsavedWork.discard")}
          </Button>
        </>
      }
    >
      <p style={bodyStyle}>{t("common.unsavedWork.body")}</p>
    </Modal>
  );

  return { dialog, requestExit, disarm };
}
