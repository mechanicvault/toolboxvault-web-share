/**
 * Consent sharing — frontend mirror of the backend surface
 * (backend/app/modules/core/sharing*.py). A mechanic shares their
 * tool list with the shop group and/or the insurance group: per group
 * they toggle the OPTIONAL fields that group may see (the locked
 * identity fields always go when an item is shared) and pick the
 * items. Settings → Sharing is the home of the controls; the add-tool
 * flow reads the same overview to decide whether to offer the
 * "add to the shared items?" prompt.
 */

export type ShareRecipientGroup = "shop_company" | "insurance";

/** The groups a tool list can be shared with, display order. */
export const SHARE_RECIPIENT_GROUPS: ShareRecipientGroup[] = [
  "shop_company",
  "insurance",
];

export interface ShareFieldOption {
  key: string;
  label: string;
}

/** Item identity — always shared when the item is shared. Shown in
 *  Settings checked and disabled, with an "Always shared" note. */
export const LOCKED_SHARE_FIELDS: ShareFieldOption[] = [
  { key: "name", label: "Name" },
  { key: "brand", label: "Brand" },
  { key: "model", label: "Model" },
  { key: "serial_number", label: "Serial number" },
];

/** Owner-toggleable per recipient group (backend catalog order). */
export const OPTIONAL_SHARE_FIELDS: ShareFieldOption[] = [
  { key: "category", label: "Category" },
  { key: "location", label: "Storage location" },
  { key: "purchase_price", label: "Purchase price" },
  { key: "purchase_date", label: "Purchase date" },
  { key: "msrp", label: "MSRP (market price)" },
  { key: "replacement_cost", label: "Replacement cost" },
  { key: "notes", label: "Notes" },
  { key: "photos", label: "Photos" },
  { key: "documents", label: "Documents & receipts" },
  { key: "custom_fields", label: "Custom fields" },
];

/** One shared item, kind-marked (tools and batteries share lists). */
export interface ShareItemRef {
  kind: "tool" | "battery";
  id: string;
}

/** One recipient group's sharing setup (GET /core/sharing). */
/** The stored addon choice for one shared set: when a set is
 *  shared, does the share include its addon pieces + attached
 *  tools? Core pieces always ride; the choice is asked per set. */
export interface ShareSetChoice {
  tool_id: string;
  include_addons: boolean;
}

/** Rule scopes beyond the per-item picks (Package C). The picks
 *  themselves are the "item" scope; a rule matches by category,
 *  location subtree, tag, or everything — resolved live. */
export type ShareRuleScope = "category" | "location" | "tag" | "all";

/** One stored sharing rule as the editor renders it. */
export interface ShareRule {
  id: string;
  scope: ShareRuleScope;
  scope_value: string;
  scope_ref_id: string | null;
  scope_label: string;
  include_addons: boolean;
  /** Items this rule is actually sharing right now. */
  match_count: number;
  created_at: string;
}

/** One tag the rule editor can point at. */
export interface ShareTagOption {
  id: string;
  name: string;
  item_count: number;
}

/** One location-tree node the rule editor can point at. */
export interface ShareLocationOption {
  id: string;
  name: string;
  path: string;
  subtree_item_count: number;
}

export interface ShareGroupState {
  recipient_group: ShareRecipientGroup;
  enabled: boolean;
  /** Chosen optional fields, catalog order. */
  fields: string[];
  shared_tool_ids: string[];
  /** Battery ids shared with this group — batteries are shareable
   *  items under the same field rules (2026-10-18). */
  shared_battery_ids: string[];
  /** Every shared item for the group, kind-marked. */
  shared_items: ShareItemRef[];
  /** Stored per-set addon choices for this group. */
  set_choices: ShareSetChoice[];
  /** Package C: the group's scope rules. */
  rules: ShareRule[];
  /** Items withheld from this group even when picked or matched
   *  by a rule — exclusions are the final word. */
  excluded_items: ShareItemRef[];
  /** The set that resolves as shared right now (picks ∪ rules −
   *  exclusions), kind-marked. */
  resolved_items: ShareItemRef[];
  resolved_count: number;
}

/** One of the owner's items (tool or battery), with the groups it
 *  is shared with. */
export interface ShareItemSummary {
  id: string;
  /** "tool" | "battery". */
  kind: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  /** Sets are marked so the picker can prompt for addons. */
  is_set?: boolean;
  shared_with: ShareRecipientGroup[];
}

/** GET /core/sharing payload: both groups + the owner's items. */
export interface SharingOverview {
  groups: ShareGroupState[];
  items: ShareItemSummary[];
  /** Package C: the rule editor's vocab — the owner's own
   *  categories, tags, and location tree to point rules at. */
  categories: string[];
  tags: ShareTagOption[];
  locations: ShareLocationOption[];
}

/** GET /core/sharing/summary: the Shared Tools page's at-a-glance
 *  panel (Package C) — tier state per group + peer grant counts. */
export interface SharingSummary {
  groups: {
    recipient_group: ShareRecipientGroup;
    enabled: boolean;
    shared_count: number;
    rule_count: number;
  }[];
  peer: {
    given_accepted: number;
    given_pending: number;
    received_accepted: number;
    received_pending: number;
  };
}

/** The groups the owner is actively sharing with (enabled config) —
 *  the add-tool prompt appears only when this is non-empty. */
export function enabledShareGroups(
  overview: SharingOverview,
): ShareGroupState[] {
  return overview.groups.filter((g) => g.enabled);
}
