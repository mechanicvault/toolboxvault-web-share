/**
 * The header Edit view request channel (Home + Header program).
 *
 * The header's Edit view button lives in the shell; Home's
 * customize session lives in CorePage. Two paths connect them:
 *  - Already ON Home: a window event (EDIT_VIEW_EVENT) — the
 *    page is mounted and listening. Nothing is stashed.
 *  - Anywhere else: a one-shot sessionStorage flag
 *    (EDIT_VIEW_FLAG) + navigation to Home; CorePage consumes
 *    the flag at mount via takeEditViewRequest.
 *
 * The flag is a PER-SESSION, PER-ACCOUNT intent — it must
 * never outlive the session that set it (owner bug report,
 * 2026-10-24: a flag left set by an on-Home click — where the
 * event, not the flag, did the work — survived an SPA logout
 * and fired Edit view on the NEXT account's first Home mount).
 * Three rules keep it scoped:
 *  1. It is only ever set on the navigate-to-Home path (the
 *     on-Home path uses the event alone).
 *  2. AuthContext clears it on login, signup and logout — a
 *     new session starts with no pending request.
 *  3. takeEditViewRequest consumes it (read + remove), so it
 *     can fire at most once.
 */
export const EDIT_VIEW_FLAG = "tv-edit-view-pending";
export const EDIT_VIEW_EVENT = "tv:edit-view";

/** Read + clear the pending request. True exactly once per set. */
export function takeEditViewRequest(): boolean {
  try {
    if (sessionStorage.getItem(EDIT_VIEW_FLAG) === "1") {
      sessionStorage.removeItem(EDIT_VIEW_FLAG);
      return true;
    }
  } catch {
    /* storage unavailable — the in-place event still works */
  }
  return false;
}

/** Drop any pending request (session boundaries call this). */
export function clearEditViewRequest(): void {
  try {
    sessionStorage.removeItem(EDIT_VIEW_FLAG);
  } catch {
    /* storage unavailable — nothing to clear */
  }
}
