/**
 * The Quick Add seed (widget wave 2 build 3, 2026-11-10): the
 * typed handoff the Home Quick Add widget passes to the add
 * wizard. The widget is a DOOR — it collects one seed (a typed
 * tool name, or one photo File) and navigates to /inventory/new
 * with the seed riding React Router location state; the wizard
 * consumes it on entry and clears it from history, so a refresh
 * or a Back trip never re-seeds and every other entry into the
 * wizard (Inventory's Add buttons, item pages) is untouched.
 *
 * A File cannot ride a URL, and location state is in-memory
 * only — which is exactly the wizard's own posture for a picked
 * photo: the wizard holds Files locally (StagedFile) and
 * uploads them only at Save. The seed photo therefore hands
 * the wizard the File itself, and the wizard stages it through
 * its own applyLookupPhoto path — the same mechanism its
 * lookup step uses for a photo it accepts — while the lookup
 * step runs its photo-identification flow on it, exactly as if
 * the user had picked it there.
 */
export interface QuickAddSeed {
  /** A typed tool name from the widget's box. */
  name?: string;
  /** One photo File dropped or picked in the widget's box. */
  photo?: File;
}

/** The location-state key the seed rides under. */
export const QUICK_ADD_SEED_KEY = "quickAddSeed";

/** Wrap a seed for `navigate(path, { state })`. */
export function quickAddSeedState(seed: QuickAddSeed): Record<string, unknown> {
  return { [QUICK_ADD_SEED_KEY]: seed };
}

/**
 * Read and validate a seed out of unknown location state.
 * Anything malformed reads as NO seed — a bad handoff can
 * never break the wizard's normal entry.
 */
export function readQuickAddSeed(state: unknown): QuickAddSeed | null {
  if (!state || typeof state !== "object") return null;
  const raw = (state as Record<string, unknown>)[QUICK_ADD_SEED_KEY];
  if (!raw || typeof raw !== "object") return null;
  const seed = raw as Record<string, unknown>;
  const out: QuickAddSeed = {};
  if (typeof seed.name === "string" && seed.name.trim()) {
    out.name = seed.name.trim();
  }
  if (typeof File !== "undefined" && seed.photo instanceof File) {
    out.photo = seed.photo;
  }
  return out.name || out.photo ? out : null;
}
