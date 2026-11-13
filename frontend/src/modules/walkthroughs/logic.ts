import type { BorrowingOverview } from "../borrowing/types";

/**
 * "Do it with me" walkthroughs (sweep D3) — the offer/completion
 * logic, kept pure so it can be unit-tested without a DOM.
 *
 * Completion comes from REAL DATA only (the brief's standing
 * rule): a user has finished their first checkout when the
 * borrowing ledger itself carries a lend of theirs, and their
 * first claim when the claims list itself is non-empty. There
 * is no dismiss flag — a flag could say "done" when nothing
 * ever happened, and could hide the door from someone who
 * exited half-way and still needs it.
 *
 * An unknown read (null — still loading, or the read failed)
 * never offers and never claims completion: the door appears
 * only on a settled read that proves the user is new to the
 * flow.
 */

/** True when the ledger proves this user has lent before:
 *  something is out with a borrower now, a borrow request is
 *  waiting on them, or a finished lend of theirs sits in
 *  history. (History also carries lends where the user was the
 *  BORROWER — those rows name someone else as owner, so they
 *  are filtered on owner_id.) */
export function hasLentBefore(
  overview: BorrowingOverview | null,
  userId: string | null,
): boolean {
  if (!overview) return false;
  if (overview.lent_out.length > 0) return true;
  if (overview.requests_for_me.length > 0) return true;
  return overview.history.some((row) => row.owner_id === userId);
}

/** Offer the first-checkout walkthrough only on a settled read
 *  that proves the user has never lent. */
export function shouldOfferCheckout(
  overview: BorrowingOverview | null,
  userId: string | null,
): boolean {
  return overview !== null && !hasLentBefore(overview, userId);
}

/** True when the claims list itself proves a claim exists.
 *  Callers pass the warranty section's own list (archived
 *  included) — disaster claims never count here, and a repair
 *  claim never counts there: the two sections stay separate. */
export function hasFiledClaimBefore(
  claims: readonly unknown[] | null,
): boolean {
  return claims !== null && claims.length > 0;
}

/** Offer the first-claim walkthrough only on a settled read
 *  that proves the user has never filed. */
export function shouldOfferClaim(
  claims: readonly unknown[] | null,
): boolean {
  return claims !== null && claims.length === 0;
}
