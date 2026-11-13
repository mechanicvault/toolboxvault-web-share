/** Tool Expansion payloads (mirror of the backend schemas).
 *
 * PRIVACY: a suggestion is ONLY a name + a model number, the
 * match keys the Remove / Report actions act on, and the viewer's
 * OWN item. Nothing about any other user exists in these shapes —
 * the backend walks this contract in its tests.
 */

export interface ExpansionItemRef {
  kind: "tool" | "battery";
  id: string;
  name: string;
  is_set: boolean;
}

export interface ExpansionSuggestion {
  name: string;
  model_number: string;
  anchor_model: string;
  suggested_model: string;
}

export interface ExpansionGroup {
  item: ExpansionItemRef;
  suggestions: ExpansionSuggestion[];
}

export interface ExpansionSuggestions {
  total: number;
  groups: ExpansionGroup[];
}

export interface ExpansionTopSuggestion {
  name: string;
  model_number: string;
  item_name: string;
}

export interface ExpansionSummary {
  count: number;
  top: ExpansionTopSuggestion[];
}

/** One archived match: the viewer's own dismissal-ledger row
 *  read back. `item` is null when the viewer's item no longer
 *  exists; `name` is "" when the match no longer generates
 *  anywhere (then `model_number` is the ledger's stored key —
 *  the tombstone the data supports, never an invented name). */
export interface ArchivedExpansion {
  anchor_kind: "tool" | "battery";
  anchor_id: string;
  item: ExpansionItemRef | null;
  name: string;
  model_number: string;
  suggested_model: string;
  archived_at: string;
  restorable: boolean;
}

export interface ArchivedExpansions {
  total: number;
  entries: ArchivedExpansion[];
}
