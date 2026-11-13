/** Stale-chunk recovery (the blank-page-after-deploy bug).
 *
 * Every page is a lazily loaded chunk with a content-hashed name.
 * After a deploy, an open tab (or a heuristically cached index)
 * can ask for a chunk file that no longer exists; the dynamic
 * import fails and — with nothing catching it — the whole app
 * unmounted to a bare white page until the user refreshed.
 *
 * The fix in two parts, both guarded so they can never loop:
 *  - Vite fires `vite:preloadError` when a chunk preload fails;
 *    we reload ONCE to pick up the fresh index + chunk names.
 *  - The top-level error boundary calls reloadOnceForChunkError()
 *    for errors that smell like a failed module load (a rejected
 *    React.lazy promise can surface as a plain render error
 *    instead of the preload event).
 * The guard is a timestamp in sessionStorage: at most one
 * automatic reload per 30 seconds, so a genuinely broken build
 * lands on the error boundary's recovery panel instead of
 * reload-looping forever.
 *
 * W-02 (deep audit): the reload is DEFERRED and CANCELLABLE.
 * `vite:preloadError` also fires when the browser cancels a
 * document's in-flight preloads because the document is navigating
 * AWAY — a full load to another URL (a deep link or bookmark hit
 * right after sign-in, a refresh during a slow boot). Answering
 * that with an immediate `location.reload()` reloaded the page
 * being left and hijacked the navigation (instrumented: a cold
 * load of /inventory right after sign-in lost to a reload of Home,
 * 3/3). So reloadOnce now schedules the reload 1.5s out and
 * cancels it on pagehide/beforeunload: a document that is actually
 * leaving never fires it, and a document that is staying (the
 * genuine stale-chunk case) still recovers on its own. */

const GUARD_KEY = "tv-chunk-reload-at";
const GUARD_WINDOW_MS = 30_000;
const RELOAD_DELAY_MS = 1500;

const CHUNK_ERROR_PATTERN =
  /chunkloaderror|loading chunk|dynamically imported module|failed to fetch|importing a module script failed|error loading dynamically imported/i;

/** True when an error looks like a failed lazy-chunk/module load. */
export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const text =
    error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  return CHUNK_ERROR_PATTERN.test(text);
}

let pendingTimer: number | null = null;
let pendingStamp = 0;

/** Schedule a reload to fetch the fresh build — at most once per
 *  guard window, deferred + cancellable (see the W-02 note above).
 *  Returns true when a reload is scheduled (or already pending). */
export function reloadOnce(): boolean {
  let withinGuard = false;
  try {
    const last = Number(sessionStorage.getItem(GUARD_KEY) ?? 0);
    withinGuard =
      Number.isFinite(last) && Date.now() - last < GUARD_WINDOW_MS;
    if (!withinGuard) {
      pendingStamp = Date.now();
      sessionStorage.setItem(GUARD_KEY, String(pendingStamp));
    }
  } catch {
    /* Storage unavailable (private mode quotas etc.) — schedule
     * anyway; the boundary still catches a repeat failure. */
  }
  if (withinGuard) return false;
  if (pendingTimer !== null) return true;
  const cancel = () => {
    if (pendingTimer !== null) {
      window.clearTimeout(pendingTimer);
      pendingTimer = null;
    }
    try {
      if (Number(sessionStorage.getItem(GUARD_KEY) ?? 0) === pendingStamp) {
        sessionStorage.removeItem(GUARD_KEY);
      }
    } catch {
      /* storage unavailable — the next document re-derives it */
    }
    window.removeEventListener("pagehide", cancel);
    window.removeEventListener("beforeunload", cancel);
  };
  window.addEventListener("pagehide", cancel);
  window.addEventListener("beforeunload", cancel);
  pendingTimer = window.setTimeout(() => {
    pendingTimer = null;
    window.removeEventListener("pagehide", cancel);
    window.removeEventListener("beforeunload", cancel);
    window.location.reload();
  }, RELOAD_DELAY_MS);
  return true;
}

/** Reload once if this error is a stale-chunk failure. */
export function reloadOnceForChunkError(error: unknown): boolean {
  return isChunkLoadError(error) ? reloadOnce() : false;
}

/** Wire Vite's preload-failure event to the guarded reload.
 *  Called once from main.tsx before the app renders. */
export function installChunkRecovery(): void {
  window.addEventListener("vite:preloadError", ((event: Event) => {
    event.preventDefault();
    reloadOnce();
    // Not a CustomEvent we own — the payload is unused.
  }) as EventListener);
}
