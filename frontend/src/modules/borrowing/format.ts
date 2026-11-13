/** Borrowing display helpers: dates and state wording shared by the
 *  Borrowing page, the detail-page lending panel, and the list-card
 *  chips — one phrasing everywhere. */

import { formatDate, formatDateShort } from "../../lib/format";
import type { Checkout, CheckoutState } from "./types";

/** Short + full forms of the shared date standard (lib/format). */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const out = formatDateShort(iso);
  return out === "—" ? "" : out;
}

export function fullDate(iso: string | null | undefined): string {
  return formatDate(iso);
}

/** A date-input value (YYYY-MM-DD) becomes an end-of-day ISO
 *  timestamp: "due Oct 30" means the item is late starting Oct 31,
 *  not at midnight that morning. */
export function dueDateToIso(dateValue: string): string | null {
  if (!dateValue) return null;
  const d = new Date(`${dateValue}T23:59:59`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export const STATE_LABELS: Record<CheckoutState, string> = {
  requested: "Requested",
  checked_out: "Checked out",
  returned: "Returned",
  declined: "Declined",
  cancelled: "Cancelled",
};

export const STATE_TONES: Record<
  CheckoutState,
  "accent" | "success" | "warning" | "danger" | "neutral"
> = {
  requested: "warning",
  checked_out: "accent",
  returned: "success",
  declined: "danger",
  cancelled: "neutral",
};

/** The one-line standing of an active lend, used by the detail-page
 *  chip and the list cards: "Checked out to Nate · due Oct 30" /
 *  "Requested by Bob". */
export function standingText(checkout: Checkout): string {
  if (checkout.state === "requested") {
    return `Requested by ${checkout.borrower_name}`;
  }
  const due = checkout.due_at ? ` · due ${shortDate(checkout.due_at)}` : "";
  const late = checkout.overdue ? " · overdue" : "";
  return `Checked out to ${checkout.borrower_name}${due}${late}`;
}

/** Where an item lives in the owner's vault — the detail route for
 *  its kind. */
export function itemPath(checkout: Checkout): string {
  return checkout.item_kind === "battery"
    ? `/inventory/batteries/${checkout.item_id}`
    : `/inventory/${checkout.item_id}`;
}

/** Where a lending-history row's borrower name links to (owner
 *  order, 2026-11-12: the borrower in a history list is a
 *  clickable link to that borrower). One rule per borrower kind:
 *  - A lend that came from the address book links to that book
 *    entry — /borrowing opens its Address book tab and expands
 *    the contact (the ?borrower= landing in BorrowingPage).
 *  - A linked member (an account on the other side) links to
 *    Shared tools' Coworkers tab, where that person stands as a
 *    sharing counterparty — the site's member view of them.
 *  - A name typed fresh at check-out has no record anywhere;
 *    the closest real home is the Address book tab, whose
 *    "From your lending history" list is exactly those people.
 *  Rows where the VIEWER is the borrower flip the parties: the
 *  name in the borrower seat is the owner, always a member, so
 *  the same Coworkers link serves. */
export function borrowerPath(row: Checkout, viewerId?: string | null): string {
  if (viewerId && row.borrower_user_id === viewerId) {
    return "/shared-tools#coworkers";
  }
  if (row.borrower_contact_id) {
    return `/borrowing?borrower=${row.borrower_contact_id}#address-book`;
  }
  if (row.borrower_user_id) {
    return "/shared-tools#coworkers";
  }
  return "/borrowing#address-book";
}
