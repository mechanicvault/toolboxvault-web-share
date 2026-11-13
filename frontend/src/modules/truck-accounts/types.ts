/** Truck Accounts types — mirroring
 *  backend/app/modules/truck_accounts/schemas.py. Money is
 *  Decimal-as-string everywhere; entry amounts are SIGNED as
 *  stored (charges positive, payments negative). */

export type TruckStatus = "invited" | "active" | "closed";
export type TruckCadence = "weekly" | "biweekly";
export type TruckEntryKind = "charge" | "payment" | "adjustment";

export interface TruckAccount {
  id: string;
  /** Null while a private (off-platform) agent holds the
   *  account — the customer maintains that tab himself. */
  dealer_user_id: string | null;
  dealer_name: string | null;
  dealer_account_number: string | null;
  /** The agent + company face (2026-10-31): the company the
   *  account nests under on the dealer page, and the current
   *  agent's name as the customer reads it. */
  dealer_company_id: string | null;
  dealer_company_name: string | null;
  agent_name: string;
  agent_kind: "platform" | "private" | null;
  /** Stage 2 (2026-11-05): the holding private record, who
   *  keeps the ledger, the stored pay-through-the-site choice,
   *  and the computed missed-payment state. */
  private_agent_id: string | null;
  ledger_keeper: "agent" | "customer";
  payment_mode: "manual" | "automatic";
  missed_payments: number;
  amount_past_due: string;
  /** Decimal strings; null when the agent set no credit line. */
  credit_limit: string | null;
  credit_available: string | null;
  customer_maintained: boolean;
  customer_user_id: string | null;
  customer_name: string;
  customer_account_number: string | null;
  customer_email: string;
  status: TruckStatus;
  payment_cadence: TruckCadence;
  /** Decimal string; null until the dealer sets the schedule. */
  payment_amount: string | null;
  next_due_date: string | null;
  balance: string;
  /** Dealer page pass (2026-11-06): the balance the ledger's
   *  first entry took the account to. */
  starting_balance: string;
  /** Truck page fixes (2026-11-06): the highest credit limit —
   *  the highest balance this account has ever stood at.
   *  Stored server-side; never decreases; nobody edits it. */
  highest_balance: string;
  agreement_version: string | null;
  agreement_accepted_at: string | null;
  my_role: "dealer" | "customer" | null;
  currency: string;
  /** True only when online payment is actually configured for
   *  this dealer (the dark Connect seam) — false in the dark. */
  pay_online_available: boolean;
  created_at: string;
  updated_at: string;
}

export interface TruckEntry {
  id: string;
  account_id: string;
  kind: TruckEntryKind;
  amount: string;
  note: string;
  item_link_id: string | null;
  /** Stage 2: the linked item resolved server-side — the
   *  ledger links through to the tool a charge was for. */
  item_name: string | null;
  item_kind: "tool" | "set" | "battery" | null;
  entry_date: string;
  source: string;
  recorded_by: string | null;
  recorded_by_name: string | null;
  created_at: string;
}

/** Stage 2: the computed schedule state — missed payments
 *  counted and listed by date, never silently skipped. */
export interface TruckScheduleStatus {
  has_schedule: boolean;
  overdue: boolean;
  missed_payments: number;
  missed_due_dates: string[];
  amount_past_due: string;
  days_until_due: number | null;
}

/** Stage 2: an agent's payment request on a shared account —
 *  the customer approves (a payment entry lands, marked
 *  agent_request) or declines. */
export interface TruckPaymentRequest {
  id: string;
  account_id: string;
  requested_by: string | null;
  requested_by_name: string | null;
  amount: string;
  note: string;
  status: "pending" | "approved" | "declined";
  entry_id: string | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string;
}

/** Stage 2: one roster agent the customer could open a
 *  self-kept account with (or already has one with). */
export interface SelfOpenTarget {
  kind: "platform" | "private";
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
  is_preferred: boolean;
  has_open_account: boolean;
}

export interface SelfOpenInput {
  company_id: string;
  private_agent_id?: string | null;
  agent_user_id?: string | null;
  opening_balance?: string;
  opening_note?: string;
  payment_cadence?: TruckCadence;
  payment_amount?: string | null;
  next_due_date?: string | null;
  payment_mode?: "manual" | "automatic";
}

export interface TruckTransfer {
  id: string;
  from_agent_name: string;
  to_agent_name: string;
  from_agent_kind: "platform" | "private" | null;
  to_agent_kind: "platform" | "private" | null;
  created_at: string;
}

export interface TruckTransferOption {
  kind: "platform" | "private";
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
}

export interface TruckAccountDetail {
  account: TruckAccount;
  entries: TruckEntry[];
  agreement_preview: string | null;
  transfers: TruckTransfer[];
  transfer_options: TruckTransferOption[];
  /** Stage 2: computed schedule state + payment requests. */
  schedule: TruckScheduleStatus;
  payment_requests: TruckPaymentRequest[];
}

export interface IssuableCompany {
  company_id: string;
  company_name: string;
}

export interface RouteVisit {
  agent_name: string;
  company_name: string;
  next_visit: string;
  frequency: string | null;
}

export interface TruckStatusSummary {
  customer_open_accounts: number;
  customer_total_balance: string;
  dealer_open_accounts: number;
  dealer_total_outstanding: string;
  payments_this_week: string;
  route_visits: RouteVisit[];
}

export interface TruckDashboard {
  open_accounts: number;
  total_outstanding: string;
  due_this_week: TruckDueRow[];
  overdue: TruckDueRow[];
}

export interface TruckDueRow {
  account_id: string;
  customer_name: string;
  amount: string | null;
  balance: string;
  next_due_date: string;
}
