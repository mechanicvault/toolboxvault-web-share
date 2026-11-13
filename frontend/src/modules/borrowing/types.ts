/** Borrowing module shapes — mirror the backend's CheckoutView /
 *  overview payloads (app/modules/borrowing/schemas.py). */

export type CheckoutState =
  | "requested"
  | "checked_out"
  | "returned"
  | "declined"
  | "cancelled";

export type CheckoutItemKind = "tool" | "battery";

export interface Checkout {
  id: string;
  owner_id: string;
  /** The item owner's display name, resolved server-side — the
   *  "Borrowed by me" surface needs a face for the owner. */
  owner_name: string | null;
  item_kind: CheckoutItemKind;
  item_id: string;
  item_name: string;
  /** Set when the borrower has an account (a linked peer
   *  counterparty); null for manual name/contact lends. */
  borrower_user_id: string | null;
  borrower_name: string;
  borrower_contact: string;
  /** The address-book contact this lend came from (gap wave 1);
   *  null for lends typed fresh or to linked accounts. */
  borrower_contact_id: string | null;
  state: CheckoutState;
  requested_at: string;
  decided_at: string | null;
  checked_out_at: string | null;
  due_at: string | null;
  returned_at: string | null;
  /** Who marked the return — either party may (v1 rule). */
  returned_by: "owner" | "borrower" | null;
  /** Set-bundle lends: rows created together (a set + its chosen
   *  addon tools) share one group id; returning any returns all.
   *  Null for an ordinary single-item lend. */
  group_id: string | null;
  notes: string;
  overdue: boolean;
  created_at: string;
  updated_at: string;
}

export interface BorrowingCounts {
  pending_requests: number;
  checked_out: number;
  borrowed: number;
  overdue: number;
}

export interface BorrowingOverview {
  requests_for_me: Checkout[];
  my_requests: Checkout[];
  lent_out: Checkout[];
  borrowed_by_me: Checkout[];
  history: Checkout[];
  counts: BorrowingCounts;
}

export interface BorrowingStats {
  checked_out_count: number;
}

export interface ItemLending {
  item_kind: CheckoutItemKind;
  item_id: string;
  current: Checkout | null;
  history: Checkout[];
}

/** A person I can lend to by account: an accepted peer-grant
 *  counterparty, either direction. */
export interface Counterparty {
  id: string;
  name: string;
  account_number: string;
}

export interface CheckoutCreateRequest {
  item_kind: CheckoutItemKind;
  item_id: string;
  borrower_user_id?: string | null;
  borrower_name?: string | null;
  borrower_contact?: string;
  /** Address book pick (gap wave 1): prefills + links the lend. */
  borrower_contact_id?: string | null;
  due_at?: string | null;
  notes?: string;
  /** Sets only: also lend the set's attached addon tools in the
   *  same bundle (the "include addon pieces?" prompt). */
  include_addons?: boolean;
}

export interface BorrowRequestCreate {
  owner_id: string;
  item_kind: CheckoutItemKind;
  item_id: string;
  due_at?: string | null;
  notes?: string;
}

/** One address-book borrower (gap wave 1) with its live roll-up
 *  counts from the ledger. */
export interface BorrowerContact {
  id: string;
  name: string;
  contact: string;
  notes: string;
  linked_user_id: string | null;
  current_holds: number;
  total_lends: number;
  created_at: string;
  updated_at: string;
}

export interface BorrowerRollup {
  contact: BorrowerContact;
  current: Checkout[];
  history: Checkout[];
}

/** The nudge outcome: delivered in-app, or copy-text to send
 *  yourself (the message text always rides along). */
export interface NudgeResult {
  message: string;
  delivered_via: "message" | "copy";
  thread_id: string | null;
}
