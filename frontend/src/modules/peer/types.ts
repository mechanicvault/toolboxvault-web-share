/**
 * Peer sharing — frontend mirror of the backend surface
 * (backend/app/modules/core/peer_sharing*.py). A person shares their
 * tool LIST with specific people (crew-mates), who browse it and
 * search "who has this tool?" for borrowing.
 *
 * The item payload is FIXED and minimal by design: identity +
 * photos + who owns it. There are no price/notes/serial fields in
 * these types because the API never sends them.
 */

export interface PeerPerson {
  id: string;
  name: string;
  account_number: string;
}

/** A set piece as peers see it — identity only, never a price. */
export interface PeerSetPiece {
  name: string;
  part_number: string;
  serial_number: string;
}

/** The member structure of a shared set. Core pieces always ride;
 *  addon pieces + attached tools ride only when the owner chose to
 *  include them for peer sharing. */
export interface PeerSetBlock {
  include_addons: boolean;
  core_pieces: PeerSetPiece[];
  addon_pieces: PeerSetPiece[];
  attached_tools: PeerItem[];
}

/** One item on someone's shared list — the whole payload. Tools
 *  carry no kind (their payload is unchanged); batteries are marked
 *  kind: "battery". Sets gain is_set + the member block; every other
 *  entry stays exactly as it was. */
export interface PeerItem {
  id: string;
  kind?: string;
  name: string;
  brand: string;
  model: string;
  category: string;
  /** Fresh photo URLs (photos only — never documents). */
  photos: string[];
  owner: PeerPerson;
  is_set?: boolean;
  set?: PeerSetBlock;
}

/** A grant I've made. `viewer` is null while an email invite is
 *  still pending (the flow never reveals whether the address has an
 *  account); `invited_email` is set for email invites. */
export interface PeerOutgoingGrant {
  id: string;
  status: "pending" | "accepted";
  created_at: string;
  responded_at: string | null;
  viewer: PeerPerson | null;
  invited_email: string | null;
}

/** A grant addressed to me: who is sharing with me. */
export interface PeerIncomingGrant {
  id: string;
  status: "pending" | "accepted";
  created_at: string;
  responded_at: string | null;
  owner: PeerPerson;
}

/** One of my own tools (identity only) — the exclusions picker. */
export interface PeerToolIdentity {
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  is_set?: boolean;
}

/** My stored peer addon choice for one of my sets. */
export interface PeerSetChoice {
  tool_id: string;
  name: string;
  include_addons: boolean;
}

/** GET /core/sharing/peer. */
/** One peer withholding rule (Package C): a category / location
 *  subtree / tag whose items never reach the crew list, resolved
 *  live like tier rules but in the withholding direction. */
export interface PeerExclusionRule {
  id: string;
  scope: "category" | "location" | "tag";
  scope_value: string;
  scope_ref_id: string | null;
  scope_label: string;
  /** Items this rule is withholding right now. */
  match_count: number;
  created_at: string;
}

export interface PeerOverview {
  sharing_with: PeerOutgoingGrant[];
  shared_with_me: PeerIncomingGrant[];
  pending_for_me: PeerIncomingGrant[];
  excluded_tool_ids: string[];
  excluded_battery_ids: string[];
  my_tools: PeerToolIdentity[];
  my_batteries: PeerToolIdentity[];
  set_choices: PeerSetChoice[];
  /** Package C: scope withholding rules + the vocab their editor
   *  points at (same option shapes as the tier rule editor). */
  exclusion_rules: PeerExclusionRule[];
  categories: string[];
  tags: { id: string; name: string; item_count: number }[];
  locations: { id: string; name: string; path: string; subtree_item_count: number }[];
}

/** GET /core/sharing/peer/lists/{owner_id}. */
export interface PeerListResponse {
  owner: PeerPerson;
  items: PeerItem[];
}
