import { api } from "../../lib/api";
import type { DictKey } from "../../i18n/dictionaries";

/** Username plumbing (sheet row 144, 2026-11-18): the live
 *  availability check behind the signup field, the forced pick
 *  screen and the Settings editor, plus the one place that turns
 *  the server's stable reason codes into words. The server
 *  decides — this module only asks and translates. */

export type UsernameReason =
  | "username_invalid"
  | "username_taken"
  | "username_reserved"
  | "username_cooldown";

export interface UsernameCheck {
  available: boolean;
  reason: UsernameReason | null;
}

export async function checkUsername(raw: string): Promise<UsernameCheck> {
  const q = encodeURIComponent(raw);
  return api<UsernameCheck>(`/core/username-check?u=${q}`);
}

/** The dictionary key carrying a reason code's words. */
export function usernameReasonKey(reason: string): DictKey {
  switch (reason) {
    case "username_taken":
      return "auth.username.taken";
    case "username_reserved":
      return "auth.username.reserved";
    case "username_cooldown":
      return "auth.username.cooldown";
    default:
      return "auth.username.invalid";
  }
}

/** A debounced availability probe for a form field: feed it the
 *  field's value on every keystroke; it reports the verdict for
 *  the LATEST value only (stale answers are dropped). Empty and
 *  unchanged values clear the verdict. */
export function probeUsername(
  raw: string,
  current: string | null,
  onVerdict: (verdict: UsernameCheck | "checking" | null) => void,
): (() => void) | undefined {
  const value = raw.trim();
  if (!value || value === (current ?? "")) {
    onVerdict(null);
    return undefined;
  }
  onVerdict("checking");
  let live = true;
  const timer = setTimeout(() => {
    void checkUsername(value)
      .then((verdict) => {
        if (live) onVerdict(verdict);
      })
      .catch(() => {
        if (live) onVerdict(null);
      });
  }, 350);
  return () => {
    live = false;
    clearTimeout(timer);
  };
}
