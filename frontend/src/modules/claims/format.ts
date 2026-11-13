import type { BadgeTone } from "../../components";
import { formatDate, formatDateTime } from "../../lib/format";
import { formatMoney } from "../../lib/money";
import type {
  ClaimStatus,
  CommChannel,
} from "./types";

/** Claims display vocabulary: labels + badge tones per status,
 *  incident type, channel, and value basis. */

export const STATUS_LABELS: Record<ClaimStatus, string> = {
  draft: "Draft",
  filed: "Filed",
  in_review: "In review",
  approved: "Approved",
  denied: "Denied",
  paid: "Paid",
  closed: "Closed",
  // Ryan's warranty words (2026-11-05) — the screens render the
  // i18n twins of these (claims.status.*); this record is the
  // English fallback vocabulary.
  not_reported: "Broken, not reported",
  reported: "Broken, Reported",
  waiting_on_agent: "Waiting on agent",
  waiting_on_parts: "Waiting on replacement parts",
  in_repair: "Tool sent in for repairs",
  agent_has_tool: "Agent has tool",
  completed: "Repaired",
  backordered: "Backordered",
};

export const STATUS_TONES: Record<ClaimStatus, BadgeTone> = {
  draft: "neutral",
  filed: "accent",
  in_review: "warning",
  approved: "success",
  denied: "danger",
  paid: "success",
  closed: "neutral",
  not_reported: "warning",
  reported: "accent",
  waiting_on_agent: "neutral",
  waiting_on_parts: "warning",
  in_repair: "warning",
  agent_has_tool: "accent",
  completed: "success",
  backordered: "danger",
};


export const CHANNEL_LABELS: Record<CommChannel, string> = {
  phone: "Phone",
  email: "Email",
  mail: "Mail",
  portal: "Portal",
  in_person: "In person",
  other: "Other",
};


/** Money from the API's decimal strings (wave 3: the one
 * formatter, lib/money — cents shown: claim amounts are
 * evidence, they read exactly). A claim's amounts are the
 * OWNER's money, so claim call sites pass the claim's
 * owner_currency and the label tells the truth for any viewer;
 * the no-currency default (the viewer's own) remains for the
 * owner's own non-claim figures this module renders (wizard
 * target values). */
export function money(
  value: string | number | null | undefined,
  currency?: string | null,
): string {
  return formatMoney(value, currency);
}

/** The shared date standard (lib/format, Round G): "Oct 19, 2026"
 *  in the active locale — Spanish renders "19 oct 2026" (F5-28). */
export function fullDate(iso: string | null | undefined): string {
  return formatDate(iso);
}

/** "Oct 19, 2026, 2:41 PM" for communications timestamps. */
export function fullDateTime(iso: string | null | undefined): string {
  return formatDateTime(iso);
}

/** Is this deadline within the warning window (or past) and still
 *  open? Drives the warning badges on the list and detail. */
export function deadlineState(
  due: string | null,
  settled: boolean,
): "ok" | "soon" | "overdue" {
  if (!due || settled) return "ok";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dueDate = new Date(`${due}T12:00:00`);
  const days = Math.round((dueDate.getTime() - today.getTime()) / 86400000);
  if (days < 0) return "overdue";
  if (days <= 7) return "soon";
  return "ok";
}
