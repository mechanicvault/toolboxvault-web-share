#!/usr/bin/env node
/**
 * Offer/completion logic tests for the "Do it with me"
 * walkthroughs (sweep D3). The logic module is pure,
 * erasable-syntax TypeScript, so Node's type stripping runs
 * it directly — no build step, no DOM.
 *
 * Run: node scripts/walkthrough-logic.test.mjs
 */
import assert from "node:assert/strict";
import {
  hasFiledClaimBefore,
  hasLentBefore,
  shouldOfferCheckout,
  shouldOfferClaim,
} from "../src/modules/walkthroughs/logic.ts";

const ME = "user-me";
const OTHER = "user-other";
const empty = {
  requests_for_me: [],
  my_requests: [],
  lent_out: [],
  borrowed_by_me: [],
  history: [],
  counts: { pending_requests: 0, checked_out: 0, borrowed: 0, overdue: 0 },
};
const row = (patch) => ({
  id: "co-1",
  owner_id: ME,
  borrower_user_id: null,
  ...patch,
});

// Unknown reads never offer and never claim completion.
assert.equal(hasLentBefore(null, ME), false);
assert.equal(shouldOfferCheckout(null, ME), false);
assert.equal(hasFiledClaimBefore(null), false);
assert.equal(shouldOfferClaim(null), false);

// A genuinely new user is offered both passes.
assert.equal(hasLentBefore(empty, ME), false);
assert.equal(shouldOfferCheckout(empty, ME), true);
assert.equal(hasFiledClaimBefore([]), false);
assert.equal(shouldOfferClaim([]), true);

// A live lend retires the checkout offer.
assert.equal(
  hasLentBefore({ ...empty, lent_out: [row({})] }, ME),
  true,
);
// So does a borrow request waiting on the user.
assert.equal(
  hasLentBefore({ ...empty, requests_for_me: [row({})] }, ME),
  true,
);
// So does the user's own finished lend in history.
assert.equal(
  hasLentBefore(
    { ...empty, history: [row({ owner_id: ME })] },
    ME,
  ),
  true,
);
// But history where the user was only the BORROWER does not:
// someone else's lend is not the user's first checkout.
assert.equal(
  hasLentBefore(
    { ...empty, history: [row({ owner_id: OTHER })] },
    ME,
  ),
  false,
);
assert.equal(
  shouldOfferCheckout(
    { ...empty, borrowed_by_me: [row({ owner_id: OTHER })] },
    ME,
  ),
  true,
);

// Any claim on the list retires the claim offer.
assert.equal(hasFiledClaimBefore([{ id: "c1" }]), true);
assert.equal(shouldOfferClaim([{ id: "c1" }]), false);

console.log("walkthrough-logic: all assertions passed");
