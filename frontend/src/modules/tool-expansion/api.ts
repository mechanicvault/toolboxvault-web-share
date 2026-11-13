/** Tool Expansion API calls — thin typed wrappers over the
 *  shared client. Every call 403s with module_unavailable when
 *  the module isn't effective for the caller; embedding surfaces
 *  (badges, the item-page section) treat that as "render
 *  nothing", exactly like the borrowing footer and the claims
 *  panel beside them. */

import { api } from "../../lib/api";
import type {
  ArchivedExpansions,
  ExpansionItemRef,
  ExpansionSuggestions,
  ExpansionSummary,
} from "./types";

export function getExpansions(
  scope?: Pick<ExpansionItemRef, "kind" | "id">,
): Promise<ExpansionSuggestions> {
  const suffix = scope
    ? `?kind=${scope.kind}&item_id=${encodeURIComponent(scope.id)}`
    : "";
  return api<ExpansionSuggestions>(`/tool-expansion/suggestions${suffix}`);
}

export function getExpansionSummary(): Promise<ExpansionSummary> {
  return api<ExpansionSummary>("/tool-expansion/summary");
}

export function getExpansionCounts(): Promise<{ counts: Record<string, number> }> {
  return api<{ counts: Record<string, number> }>("/tool-expansion/counts");
}

/** Move to archived matches: this suggestion, on this item of
 *  mine, leaves my Matches tab and waits in my archive until I
 *  bring it back. */
export function dismissExpansion(body: {
  anchor_kind: "tool" | "battery";
  anchor_id: string;
  suggested_model: string;
}): Promise<void> {
  return api<void>("/tool-expansion/dismiss", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** My archived matches: the dismissal ledger read back, newest
 *  first, each entry resolved against the live derivation. */
export function getArchivedExpansions(): Promise<ArchivedExpansions> {
  return api<ArchivedExpansions>("/tool-expansion/archived");
}

/** Bring one archived match back: delete its ledger row. If the
 *  match still generates, it returns to the Matches tab. */
export function unarchiveExpansion(body: {
  anchor_kind: "tool" | "battery";
  anchor_id: string;
  suggested_model: string;
}): Promise<void> {
  return api<void>("/tool-expansion/unarchive", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Not relevant / inaccurate: judge the MATCH. Hides it for the
 *  reporter at once; at the kill threshold of distinct reporters
 *  it stops for everyone. */
export function reportExpansion(body: {
  anchor_model: string;
  suggested_model: string;
}): Promise<void> {
  return api<void>("/tool-expansion/report", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
