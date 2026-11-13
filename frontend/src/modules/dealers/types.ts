/** Dealers module types — mirror backend app/modules/dealers/schemas.py. */

export interface DealerPhone {
  label: string;
  number: string;
}

/** The brand's warranty route when there is no simple mail-in:
 *  `gate` is the required first step (call / form / photo claim /
 *  return to store); `notes` are short researched process facts. */
export interface WarrantyProcess {
  gate: string | null;
  notes: string[];
}

export interface DealerCompany {
  id: string;
  name: string;
  email: string;
  website: string;
  address: string;
  phones: DealerPhone[];
  notes: string;
  is_directory: boolean;
  /** True when this is one of the signed-in user's private companies. */
  is_mine: boolean;
  /** Personal edits (2026-11-05): present exactly when the
   *  VIEWER keeps his own details for this directory dealer —
   *  the values above are already his; `fields` names the ones
   *  he overrode. Null for raw views and his own companies. */
  personal_edit: { fields: string[] } | null;
  /* Corporate directory data (2026-10-19). ship_to_* is null unless
   * the brand officially publishes a warranty mail-in address;
   * scoped addresses always carry their scope note. */
  kind: "manufacturer" | "retailer";
  warranty_url: string;
  warranty_phone: string | null;
  /** The phones entry labeled "Customer Service", else the first
   *  listed number, else null (computed server-side). */
  customer_service_phone: string | null;
  ship_to_name: string | null;
  ship_to_address: string | null;
  ship_to_scope: "general" | "scoped" | null;
  ship_to_scope_note: string | null;
  warranty_process: WarrantyProcess | null;
  logo_key: string | null;
  logo_url: string | null;
  /** "dark" renders the logo on a dark tile (white-glyph logos). */
  logo_tile: string | null;
}

export interface DealerCompanyWrite {
  name: string;
  email: string;
  website: string;
  address: string;
  phones: DealerPhone[];
  notes: string;
  kind: "manufacturer" | "retailer";
  warranty_url: string;
  warranty_phone: string | null;
  ship_to_name: string | null;
  ship_to_address: string | null;
  ship_to_scope: "general" | "scoped" | null;
  ship_to_scope_note: string | null;
  warranty_process: WarrantyProcess | null;
  logo_key: string | null;
  logo_tile: string | null;
}

/** Personal edits (2026-11-05): the identity/contact subset of
 *  DealerCompanyWrite a viewer may keep as HIS details for a
 *  directory dealer. The corporate warranty block is directory
 *  data and is never part of a personal save. */
export interface DealerCompanyPersonalWrite {
  name: string;
  email: string;
  website: string;
  address: string;
  phones: DealerPhone[];
  notes: string;
  logo_key: string | null;
  logo_tile: string | null;
}

export interface PrivateAgent {
  id: string;
  company_id: string | null;
  company_name: string | null;
  name: string;
  phone: string;
  email: string;
  notes: string;
  /** Private -> platform switch: an archived record was linked to
   *  a Toolbox Vault account (its preferences re-pointed there). */
  archived: boolean;
  linked_account_number: string | null;
  /** Agent code + takeover (2026-11-03): the record's own code —
   *  only the owner's surfaces ever receive it. link_source says
   *  how a link came to be; claimed_by_* names the agent who took
   *  this record over, when one has. */
  agent_code: string;
  agent_code_display: string;
  link_source: "takeover" | "switch" | null;
  claimed_by_name: string | null;
  claimed_by_account_number: string | null;
  /** The record fields (stage 1, 2026-11-04): route area, the
   *  route schedule triple (all null = no route), tenure. */
  location: string;
  route_frequency: "weekly" | "biweekly" | "monthly" | null;
  route_day_of_week: number | null;
  route_anchor_date: string | null;
  started_at: string | null;
  ended_at: string | null;
}

/** One pending takeover ask on one of MY records. */
export interface TakeoverRequest {
  id: string;
  requester_name: string;
  requester_account_number: string;
  created_at: string;
}

/** The outcome of entering an agent code. */
export interface TakeoverEnterResult {
  status: "pending" | "already_claimed" | "own_record";
  agent_name: string;
  company_name: string;
  company_id: string | null;
  private_agent_id: string;
  request_id: string | null;
}

/** A code-entry ask I made as an agent. */
export interface MyTakeoverRequest {
  id: string;
  status: "pending" | "accepted" | "declined" | "superseded";
  agent_name: string;
  company_name: string;
  company_id: string | null;
  owner_name: string;
  created_at: string;
  decided_at: string | null;
}

/** A customer record an agent account has taken over. */
export interface ClaimedRecord {
  private_agent_id: string;
  agent_name: string;
  company_id: string | null;
  company_name: string;
  owner_name: string;
  claimed_at: string;
}

export interface TakeoverMine {
  requests: MyTakeoverRequest[];
  claimed: ClaimedRecord[];
}

export interface PrivateAgentWrite {
  company_id: string | null;
  name: string;
  phone: string;
  email: string;
  notes: string;
  location?: string;
  route_frequency?: "weekly" | "biweekly" | "monthly" | null;
  route_day_of_week?: number | null;
  route_anchor_date?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface PreferredAgent {
  id: string;
  company_id: string;
  company_name: string | null;
  kind: "platform" | "private";
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
  phone: string;
  email: string;
  account_number: string | null;
  /** The row is a CONNECTION; this marks it as A preferred
   *  agent for (user, company) — any number of rows may carry
   *  it (multi-preferred, 2026-11-05). */
  is_preferred: boolean;
  tenure_started_at: string | null;
  tenure_ended_at: string | null;
  /** His next route day from his route schedule (the
   *  roster's computation, ridden on the preferred read for
   *  the directory row), or null with no complete schedule. */
  next_visit: string | null;
}

/** The preferred-agent SUMMARY for one company (owner ruling
 *  2026-11-06) — how SUMMARY displays name the viewer's
 *  preferred agent: "one" with the agent when exactly one is
 *  flagged (or, with none flagged, the earliest connection —
 *  the standing fallback); "many" with agent null when more
 *  than one is flagged (displays show "Multiple Agents" and
 *  name nobody); "none" when there is no connection at all. */
export interface PreferredSummary {
  state: "none" | "one" | "many";
  agent: PreferredAgent | null;
}

/* -- The roster + agent record (stage 1, 2026-11-04) ------------------ */

export interface RosterEntry {
  /** "private:<record id>" | "platform:<user id>" */
  key: string;
  kind: "private" | "platform";
  connection_id: string | null;
  private_agent_id: string | null;
  agent_user_id: string | null;
  name: string;
  phone: string;
  email: string;
  account_number: string | null;
  /** Route area: the record's location, or the platform
   *  agent's profile service area. */
  location: string;
  route_frequency: "weekly" | "biweekly" | "monthly" | null;
  route_day_of_week: number | null;
  route_anchor_date: string | null;
  next_visit: string | null;
  started_at: string | null;
  ended_at: string | null;
  is_preferred: boolean;
  claimed_by_name: string | null;
  claimed_by_account_number: string | null;
}

export interface RosterClaim {
  id: string;
  claim_number: string;
  status: string;
  is_open: boolean;
  item_name: string;
  created_at: string;
}

export interface RosterTruckAccount {
  id: string;
  status: string;
  balance: string;
  agent_name: string;
  /** Stage 2 (2026-11-05): the schedule face of the slot —
   *  next due + the computed missed state. */
  next_due_date: string | null;
  payment_amount: string | null;
  missed_payments: number;
  amount_past_due: string;
}

export interface RosterAgentDetail {
  entry: RosterEntry;
  /** The full private record for private seats; null for
   *  platform seats (their facts ride on the entry). */
  record: PrivateAgent | null;
  notes: string;
  claims: RosterClaim[];
  truck_accounts: RosterTruckAccount[];
  can_delete: boolean;
  delete_block_reason: string | null;
}

/* -- Dealer portal (agent side) -------------------------------------- */

/** GeoJSON Polygon as stored on the profile: coordinates are
 *  [lng, lat] pairs, ring closed. */
export interface AreaPolygon {
  type: "Polygon";
  coordinates: [number, number][][];
}

export interface AgentProfile {
  display_name: string;
  phone: string;
  contact_email: string;
  service_area: string;
  bio: string;
  photo_url: string | null;
  has_photo: boolean;
  /** The owner's visibility switch — default OFF. */
  publicly_listed: boolean;
  /* Service-area geometry (dealer build). has_area gates the
   * listing switch: no territory, no public listing. */
  has_area: boolean;
  area_type: "polygon" | "radius" | null;
  area_polygon: AreaPolygon | null;
  area_center_lat: number | null;
  area_center_lng: number | null;
  area_radius_miles: number | null;
  area_zip: string;
  /* Route schedule (audit A2): the three facts + the backend's
   * computed next visit (ISO date). All null = no fixed route. */
  route_frequency: "weekly" | "biweekly" | "monthly" | null;
  route_day_of_week: number | null;
  route_anchor_date: string | null;
  route_next_visit: string | null;
}

export interface AgentProfileWrite {
  display_name?: string;
  phone?: string;
  contact_email?: string;
  service_area?: string;
  bio?: string;
  publicly_listed?: boolean;
  /* Area write: area_type present selects the shape; explicit
   * null clears the territory. */
  area_type?: "polygon" | "radius" | null;
  area_polygon?: AreaPolygon | null;
  area_center_lat?: number | null;
  area_center_lng?: number | null;
  area_radius_miles?: number | null;
  area_zip?: string;
  route_frequency?: "weekly" | "biweekly" | "monthly" | null;
  route_day_of_week?: number | null;
  route_anchor_date?: string | null;
}

/* -- Find an Agent (dealer build) ------------------------------------- */

export interface FindAgentCompany {
  company_id: string;
  company_name: string;
  verified: boolean;
}

/** One search result. phone/contact_email/photo_url are ABSENT on
 *  the anonymous card and absent whenever the agent left them
 *  blank — same exact-key discipline as the company page cards. */
export interface FindAgentCard {
  agent_user_id: string;
  display_name: string;
  service_area: string;
  area_type: "polygon" | "radius" | null;
  verified: boolean;
  companies: FindAgentCompany[];
  photo_url?: string;
  phone?: string;
  contact_email?: string;
}

export interface FindAgentResult {
  query: string;
  point: { lat: number; lng: number; display_name: string };
  results: FindAgentCard[];
}

/* -- Find local Agent (stage 3, 2026-11-05): ZIP + radius --------------
 * The card narrows FindAgentCard's companies to the agent's VERIFIED
 * representations — the only ones a connect can attach to — and each
 * carries the viewer's connection state for it. distance_miles is to
 * the NEAREST point of the agent's territory: 0 (covers_zip) when the
 * territory covers the searched ZIP itself. */

export interface FindLocalCompany extends FindAgentCompany {
  connected: boolean;
  is_preferred: boolean;
}

export interface FindLocalAgentCard extends Omit<FindAgentCard, "companies"> {
  companies: FindLocalCompany[];
  distance_miles: number;
  covers_zip: boolean;
}

export interface FindLocalAgentResult {
  zip: string;
  radius_miles: number;
  point: { lat: number; lng: number; display_name: string };
  results: FindLocalAgentCard[];
}

export interface GeocodeResult {
  lat: number;
  lng: number;
  display_name: string;
}

/* -- Dealers near you (dashboard widget, widget wave 2, 2026-11-10) -----
 * The widget's read: the viewer's own ZIP (from the postal
 * address on their profile) through the find-local search.
 * state is the honest shape of the answer — no_location /
 * unknown_zip are payload states, never errors and never a
 * dressed-up empty list. Rows are (agent, company) pairs: the
 * company's logo fields ride along so the widget paints the
 * directory's own CompanyLogo treatment. */

export interface NearYouCompany {
  company_id: string;
  company_name: string;
  logo_url: string | null;
  logo_tile: string | null;
  connected: boolean;
  is_preferred: boolean;
}

export interface NearYouAgent {
  agent_user_id: string;
  display_name: string;
  service_area: string;
  photo_url?: string | null;
  distance_miles: number;
  covers_zip: boolean;
  companies: NearYouCompany[];
}

export interface NearYouResult {
  state: "ok" | "none_near" | "no_location" | "unknown_zip";
  zip: string | null;
  radius_miles: number;
  point: { lat: number; lng: number; display_name: string } | null;
  results: NearYouAgent[];
}

/* -- Warranty service requests (dealer build) -------------------------- */

export type WarrantyStatus =
  | "unclaimed"
  | "received"
  | "in_process"
  | "resolved";

export interface WarrantyAgentRef {
  user_id: string;
  display_name: string;
}

export interface WarrantyRequest {
  id: string;
  status: WarrantyStatus;
  status_label: string;
  company_id: string | null;
  company_name: string;
  claim_id: string;
  item_kind: "tool" | "battery" | "piece";
  item_id: string;
  item_name: string;
  brand: string;
  model: string;
  serials: string[];
  problem: string;
  purchase_date: string | null;
  warranty_status: string;
  requester_id: string;
  requester_name: string;
  requester_email: string;
  requester_phone: string;
  requester_area: string;
  requester_deleted: boolean;
  routed_agents: WarrantyAgentRef[];
  claimed_by: WarrantyAgentRef | null;
  claimed_by_me: boolean;
  mine: boolean;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

/** The exact payload a send would carry — shown to the user
 *  BEFORE they confirm (backend-built, never re-assembled here). */
export interface WarrantyPayloadPreview {
  requester_name: string;
  requester_email: string;
  requester_phone: string;
  requester_area: string;
  item_name: string;
  brand: string;
  model: string;
  serials: string[];
  problem: string;
  purchase_date: string | null;
  warranty_status: string;
}

export interface WarrantyEligibility {
  available: boolean;
  /** "" when available; "no_company" | "no_agents" |
   *  "already_sent" otherwise. */
  reason: string;
  company_name: string;
  has_preferred_agent: boolean;
  preferred_agent_names: string[];
  registered_agent_count: number;
  payload: WarrantyPayloadPreview | null;
  existing_request: WarrantyRequest | null;
}

export interface WarrantyCounts {
  incoming_unclaimed: number;
  claimed_open: number;
  resolved: number;
}

export interface Representation {
  id: string;
  company_id: string;
  company_name: string;
  verified: boolean;
}

export interface RepresentationAdmin {
  id: string;
  agent_user_id: string;
  agent_name: string;
  agent_email: string;
  agent_account_number: string;
  company_id: string;
  company_name: string;
  verified: boolean;
  verified_at: string | null;
}

/** A listed agent on a company page. Optional fields are ABSENT
 *  (not null) when the agent left them empty — the backend omits
 *  them so nothing falls back to account data. */
export interface PublicAgentCard {
  agent_user_id: string;
  display_name: string;
  verified: boolean;
  service_area?: string;
  bio?: string;
  phone?: string;
  contact_email?: string;
  photo_url?: string;
}

export interface CompanyDetail {
  company: DealerCompany;
  agents: PublicAgentCard[];
  my_preferred_agents: PreferredAgent[];
}

export interface DealerPortalStats {
  preferred_by_count: number;
  companies_represented_count: number;
  profile_visibility: string;
}

/* -- Dealer intermingling (2026-10-25): the viewer's OWN records
 *    for one company — their items from it, honest stats, and
 *    their claims touching it. ---------------------------------- */

export interface CompanyItemRef {
  id: string;
  item_kind: "tool" | "battery";
  name: string;
  brand: string;
  model: string;
  /** Serial(s), flattened — the claim picker searches on it. */
  serial: string;
  standing: string;
  quantity: number;
  is_set: boolean;
  purchase_date: string | null;
  /** Primary-photo renditions; null when the item has no photo
   *  (the row paints the shared no-photo placeholder). */
  photo?: {
    thumb_url?: string | null;
    thumb_url_sm?: string | null;
  } | null;
  /** Extended purchase total; null when no price is recorded. */
  spent: string | null;
}

export interface CompanyClaimRef {
  id: string;
  claim_number: string;
  /** Which section owns the claim (separation, 2026-11-04): the
   *  dealer page shows both kinds as factual records, but each
   *  row links into its OWN section. */
  kind: "warranty_repair" | "insurance_disaster";
  status: string;
  insurer_name: string;
  incident_type: string;
  incident_date: string | null;
  total_amount: string;
  /** The claim owner's currency — total_amount is in it. */
  owner_currency: string;
  created_at: string;
  /** Dealer page pass (2026-11-06): the claim rows' date
   *  (reported-or-filed, as the Repair claims list shows it)
   *  and last-update columns. */
  reported_at: string | null;
  updated_at: string | null;
  archived: boolean;
  items: string[];
}

export interface CompanyClaimsBlock {
  current: CompanyClaimRef[];
  history: CompanyClaimRef[];
}

export interface CompanyRecordsStats {
  items_count: number;
  total_spent: string;
  /** Null when no item from this dealer carries a recorded
   *  replacement value. */
  replacement_value: string | null;
  last_purchase_date: string | null;
  /** Null when the claims module is off for the viewer. */
  open_claims: number | null;
  total_claims: number | null;
}

export interface CompanyMyRecords {
  items: CompanyItemRef[];
  stats: CompanyRecordsStats;
  /** Null when the claims module is off for the viewer — the
   *  page then shows no claims areas at all. */
  claims: CompanyClaimsBlock | null;
}


/* -- My dealer list (owner directive, 2026-10-31): the per-user
 *    customization of the prefilled pick list — directory brands
 *    removed from MY list, plus my own template entries. An entry
 *    is not a dealer record: picking it mints the private company
 *    (created_company_id), and from then on the company is the
 *    record. */

export interface DealerListEntry {
  id: string;
  name: string;
  kind: "manufacturer" | "retailer";
  email: string;
  website: string;
  address: string;
  phones: DealerPhone[];
  notes: string;
  created_company_id: string | null;
  created_company_name: string;
}

export interface DealerListEntryWrite {
  name: string;
  kind: "manufacturer" | "retailer";
  email: string;
  website: string;
  address: string;
  phones: DealerPhone[];
  notes: string;
}

export interface DealerPickList {
  companies: DealerCompany[];
  entries: DealerListEntry[];
}

export interface DirectoryListState {
  company: DealerCompany;
  hidden: boolean;
}

export interface DealerListSettings {
  directory: DirectoryListState[];
  entries: DealerListEntry[];
}

export interface DealerListRestoreResult {
  hidden_removed: number;
  entries_removed: number;
  settings: DealerListSettings;
}
