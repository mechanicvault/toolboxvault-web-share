/** Inventory module types — mirror backend/app/modules/inventory/schemas.py. */

/** An item's standing (Package B): the authority for whether an
 *  asset is usable. `in_service` is the quiet default; the other
 *  four render as badges everywhere the item appears. */
export type Standing = "in_service" | "broken" | "in_repair" | "lost" | "stolen" | "sold" | "replaced";

export const STANDING_LABELS: Record<Standing, string> = {
  // Owner ruling 2026-11-03: the item's in-service status reads
  // "Available" now (the header status pill's vocabulary).
  in_service: "Available",
  broken: "Broken",
  in_repair: "In repair",
  lost: "Lost",
  stolen: "Stolen",
  sold: "Sold",
  // Retired by the broken-item Replace flow (claims two-types,
  // 2026-10-25): out of the lists, still readable on its own page.
  replaced: "Replaced",
};

/** One row of the sold ledger (wave 2): a sale or its reversal.
 *  Amounts are Decimal strings; `reversed` marks a sale a later
 *  reversal row cancelled (history, not a live sale). */
export interface SaleRecord {
  id: string;
  item_kind: "tool" | "battery" | "set_piece";
  item_id: string;
  set_id: string | null;
  item_name: string;
  quantity_sold: number;
  buyer_name: string;
  buyer_contact: string;
  sale_price: string;
  sold_on: string;
  note: string;
  source: string;
  kind: "sale" | "reversal";
  reverses_id: string | null;
  reversed: boolean;
  created_at: string;
}

export interface SalesTotals {
  total_sold_value: string;
  sale_count: number;
  units_sold: number;
  record_count: number;
}

/** One node of the owner's location tree (Package B): a toolbox,
 *  a drawer inside it, a bin inside that… `path` is the node's
 *  full label ("Shop Toolbox / Left Drawer 2") — the same string
 *  filed items carry as their `location` text. */
export interface LocationNode {
  id: string;
  owner_id: string;
  name: string;
  parent_id: string | null;
  /** Drawer-grid position (audit A3): the layout (toolbox) node
   *  this node is a drawer of + its position there. Null on
   *  ordinary nodes. */
  parent_layout_id: string | null;
  drawer_index: number | null;
  path: string;
  sort_order: number;
  /** Items filed directly under this node. */
  item_count: number;
  /** Items under this node plus its whole subtree. */
  subtree_item_count: number;
  created_at: string;
  updated_at: string;
}

/** One piece row submitted by the item form's inline set editor
 *  (Package B): the submitted list REPLACES the set's pieces
 *  exactly. `id` rides only for pieces that already exist. Any
 *  piece may carry a price (owner 2026-10-25). */
export interface SetPieceInline {
  id?: string;
  kind: "core" | "addon";
  name: string;
  part_number?: string;
  serial_number?: string;
  status?: "present" | "missing" | "sold" | "removed";
  price?: string | null;
  purchase_date?: string | null;
  sort_order?: number;
}

/** An optional first maintenance schedule riding an item save
 *  (Package B): an interval OR a due date is required. */
export interface InitialSchedule {
  kind: "calibration" | "service" | "inspection" | "other";
  label?: string;
  interval_days?: number | null;
  due_date?: string | null;
  last_done_at?: string | null;
}

export interface Attachment {
  key: string;
  filename: string;
  kind: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string | null;
  /** Provenance (wave 4): set on files the system fetched itself
   *  (origin "manual" — a located user manual). Null on uploads. */
  origin?: string | null;
  source_url?: string | null;
  source_name?: string | null;
  fetched_at?: string | null;
  /** Set when this file is one of the item's lost/stolen reports'
   *  documents (uploaded through the report panel). */
  loss_report_id?: string | null;
  /** Fresh presigned read URL, minted at read time. Render directly. */
  url: string;
  /** Signed rendition URLs for tile (320px) / list (128px) slots
   *  (F3-12) — photos only, null/absent otherwise. */
  thumb_url?: string | null;
  thumb_url_sm?: string | null;
}

/** One event in an item's life story (asset history). The feed
 *  merges every module's registered providers server-side; kinds
 *  map to icons in HistoryPanel. */
export interface HistoryEvent {
  ts: string;
  kind: string;
  title: string;
  detail: string;
  link: string | null;
}

export interface ItemHistory {
  item_kind: string;
  item_id: string;
  events: HistoryEvent[];
}

/** One of the owner's tags (item structure package). */
export interface Tag {
  id: string;
  name: string;
  color: string;
  item_count?: number;
}

/** One piece of a set. Any piece may carry its own price (null =
 *  none recorded); a core piece's price never joins the set's
 *  totals, addon prices do. */
export interface SetPiece {
  id: string;
  set_id: string;
  kind: "core" | "addon";
  name: string;
  part_number: string;
  serial_number: string;
  status: "present" | "missing" | "sold" | "removed";
  /** Repair standing (maintenance module) — distinct from the
   *  presence status above: a piece can be present AND broken. */
  repair_state: "in_service" | "broken" | "in_repair";
  repair_problem: string;
  price: string | null;
  purchase_date: string | null;
  sort_order: number;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
}

/** An addon tool inside a set's payload: identity + its own money. */
export interface AttachedToolRef {
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  quantity: number;
  purchase_price: string | null;
  purchase_total: string | null;
  replacement_cost: string | null;
}

export interface SetBlock {
  core_pieces: SetPiece[];
  addon_pieces: SetPiece[];
  attached_tools: AttachedToolRef[];
  price_total: string | null;
  replacement_total: string | null;
}

export interface Tool {
  id: string;
  owner_id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  /** Barcode / UPC (wave 4). */
  upc: string;
  category: string;
  location: string;
  /** Location tree node this item is filed under (Package B);
   *  `location` above is its denormalized path string. */
  location_id: string | null;
  /** Package B standing — see Standing. */
  standing: Standing;
  notes: string;
  purchase_price: string | null;
  purchase_date: string | null;
  replacement_cost: string | null;
  msrp: string | null;
  /** Warranty (maintenance build): the term is stored; the
   *  standing + end date are computed server-side by the same
   *  shared function batteries use. */
  warranty_months: number | null;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  /** term | lifetime | limited — null = not specified. */
  warranty_type: "term" | "lifetime" | "limited" | null;
  warranty_status: WarrantyStatus;
  warranty_end_date: string | null;
  /** Replaced marker (asset history): the swap date, the
   *  replacement item's id (either kind; may dangle after a
   *  delete), its name resolved live, and the owner's note.
   *  Pure history — a replaced item stays in the active set. */
  replaced_on: string | null;
  replaced_by_item_id: string | null;
  replaced_by_name: string | null;
  replaced_note: string;
  /** Item structure package: quantity (money is per unit), size,
   *  multi-value numbers (model/serial_number above stay the
   *  primary = first entry), consumable flag, dealer tag, tags. */
  quantity: number;
  size: string;
  model_numbers: string[];
  serial_numbers: string[];
  consumable: boolean;
  /** Business use (audit A9) + the computed sub-limit guidance. */
  business_use: boolean;
  sub_limit_warning: boolean;
  /** Re-buy block (audit A7): where the replacement comes from. */
  rebuy_store: string;
  rebuy_url: string;
  rebuy_sku: string;
  rebuy_notes: string;
  /** Sets: this tool IS a set; the full structure rides in `set`. */
  is_set: boolean;
  attached_to_set_id: string | null;
  attached_to_set: { id: string; name: string } | null;
  /** Dealer tag (dealers module): both null when the module is off
   *  for the viewer (the stored value is preserved server-side). */
  dealer_company_id: string | null;
  dealer_company_name: string | null;
  tags: Tag[];
  set_summary: { core_count: number; addon_count: number } | null;
  set: SetBlock | null;
  /** Owner search marks a set found through its contents. */
  matched_via?: "piece" | "attached" | null;
  matched_label?: string | null;
  /** Values keyed by field-definition id. */
  custom_data: Record<string, unknown>;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
  /** Entitlement standing (billing): false = over the plan's item
   *  limit while enforcement is on — shown greyed, excluded from
   *  stats and sharing. Absent/true = a normal, active tool. */
  active?: boolean;
}

export type FieldType = "text" | "number" | "date" | "dropdown" | "boolean";

export interface FieldDefinition {
  id: string;
  item_type: string;
  name: string;
  label: string;
  field_type: FieldType;
  required: boolean;
  searchable: boolean;
  options: string[];
  sort_order: number;
  created_at: string;
}

export interface ToolFormValues {
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  category: string;
  /** The location tree node id ("" = no location). */
  location_id: string;
  notes: string;
  purchase_price: string;
  purchase_date: string;
  replacement_cost: string;
  msrp: string;
  warranty_months: string;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  warranty_type: string;
  quantity: string;
  size: string;
  model_numbers: string[];
  serial_numbers: string[];
  /** Barcode / UPC (wave 4). */
  upc: string;
  consumable: boolean;
  business_use: boolean;
  rebuy_store: string;
  rebuy_url: string;
  rebuy_sku: string;
  rebuy_notes: string;
  is_set: boolean;
  dealer_company_id: string;
  tag_ids: string[];
  custom_data: Record<string, unknown>;
}

/** Computed warranty standing (backend: purchase_date + warranty_months). */
export type WarrantyStatus =
  | "in_warranty"
  | "expiring_soon"
  | "expired"
  | "unknown";

export const WARRANTY_LABELS: Record<WarrantyStatus, string> = {
  in_warranty: "In warranty",
  expiring_soon: "Warranty expiring soon",
  expired: "Warranty expired",
  unknown: "Warranty unknown",
};

/** Structured warranty type (gap wave 1): the coverage shape the
 *  owner recorded — a lifetime warranty never expires. */
export const WARRANTY_TYPE_LABELS: Record<string, string> = {
  term: "Term",
  lifetime: "Lifetime",
  limited: "Limited",
};

/** A battery: a first-class asset record (mirror of the backend's
 *  BatteryPublic) — same money/attachment/custom-field machinery as
 *  a tool, plus the battery facts and the "currently in" link. */
export interface Battery {
  id: string;
  owner_id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  /** Barcode / UPC (wave 4). */
  upc: string;
  /** Business use (audit A9) + the computed sub-limit guidance. */
  business_use: boolean;
  sub_limit_warning: boolean;
  category: string;
  location: string;
  location_id: string | null;
  standing: Standing;
  notes: string;
  purchase_price: string | null;
  purchase_date: string | null;
  replacement_cost: string | null;
  msrp: string | null;
  platform: string;
  voltage: string | null;
  capacity_ah: string | null;
  chemistry: string;
  warranty_months: number | null;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  /** term | lifetime | limited — null = not specified. */
  warranty_type: "term" | "lifetime" | "limited" | null;
  warranty_status: WarrantyStatus;
  warranty_end_date: string | null;
  /** Replaced marker — mirrors Tool's exactly. */
  replaced_on: string | null;
  replaced_by_item_id: string | null;
  replaced_by_name: string | null;
  replaced_note: string;
  currently_in_tool_id: string | null;
  currently_in_tool_name: string | null;
  quantity: number;
  dealer_company_id: string | null;
  dealer_company_name: string | null;
  tags: Tag[];
  custom_data: Record<string, unknown>;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
  /** Same entitlement annotation as Tool.active. */
  active?: boolean;
}

export interface BatteryFormValues {
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  category: string;
  /** The location tree node id ("" = no location). */
  location_id: string;
  notes: string;
  purchase_price: string;
  purchase_date: string;
  replacement_cost: string;
  msrp: string;
  platform: string;
  voltage: string;
  capacity_ah: string;
  chemistry: string;
  warranty_months: string;
  warranty_provider: string;
  warranty_contact: string;
  warranty_terms: string;
  warranty_type: string;
  currently_in_tool_id: string;
  quantity: string;
  /** Barcode / UPC (wave 4). */
  upc: string;
  business_use: boolean;
  dealer_company_id: string;
  tag_ids: string[];
  custom_data: Record<string, unknown>;
}

/** A lost/stolen report record (gap wave 1): the item's paper
 *  trail for one incident. One ACTIVE report per item; recovered
 *  reports stay as history. */
export interface LossReport {
  id: string;
  item_kind: "tool" | "battery";
  item_id: string;
  status: "active" | "recovered";
  standing: "lost" | "stolen";
  reported_date: string | null;
  police_report_number: string;
  police_department: string;
  insurer_name: string;
  claim_number: string;
  notes: string;
  recovered_date: string | null;
  created_at: string;
  updated_at: string;
  /** Documents tied to this report (police report scans etc.),
   *  resolved by the per-item reports read. */
  documents: Attachment[];
}

/** One Health Check row (gap wave 1): an active item missing
 *  claim-critical data. */
export interface HealthCheckItem {
  kind: "tool" | "battery";
  id: string;
  name: string;
  missing: Array<"identifier" | "photo" | "purchase_date">;
  pieces_missing_serial: string[];
  /** The same pieces as {id, name} pairs — each piece pill's
   *  Fix-it link lands on that piece's own serial field. */
  pieces_missing: Array<{ id: string; name: string }>;
  sub_limit_warning: boolean;
  /** Sweep E3: this item's missing photo is currently ignored
   *  (rides only items flagged for other gaps). */
  photo_ignored?: boolean;
  /** Identifying data for the fix-all wizard's steps (sweep E3). */
  brand?: string;
  model?: string;
  serial_number?: string;
}

export interface HealthCheckResult {
  total: number;
  counts: Record<string, number>;
  items: HealthCheckItem[];
  /** Active items the scan ran over (sweep B2-F16): 0 = the vault
   *  itself is empty, which is NOT the same as claim-ready. */
  total_items?: number;
  /** Sweep E3: active items whose missing photo is ignored —
   *  the Un-ignore surface. Never counted in total/counts. */
  photo_ignored_items?: Array<{ kind: "tool" | "battery"; id: string; name: string }>;
}

/* -- Health checks due (dashboard widget, widget wave 2, 2026-11-10) -----
 * The widget's read of the same scan: the HealthCheckItem plus
 * its primary photo's rendition URLs (null when the item has
 * no photo — a missing photo is one of the gaps the scan
 * flags). Display data only; the gaps are the scan's own. */

export interface HealthCheckDueItem extends HealthCheckItem {
  thumb_url?: string | null;
  thumb_url_sm?: string | null;
}

export interface HealthCheckDueResult {
  total: number;
  counts: Record<string, number>;
  items: HealthCheckDueItem[];
}

/** One category in the manager (gap wave 1). */
export interface CategoryRow {
  name: string;
  item_count: number;
  registered: boolean;
  /** Starred (owner spec 2026-10-24): the category is one of
   *  the owner's ≤5 shortcut links in the Inventory view row. */
  starred: boolean;
  /** Create responses only: the category was asked to be born
   *  starred but the cap was full, so it was created unstarred. */
  star_capped?: boolean;
  /** Preinstalled starter (owner spec 2026-10-25): one of the
   *  four seeded categories. Starters can't be deleted (or
   *  merged away); `system_key` says which one it is, and
   *  "batteries" is also fixed-name. */
  preinstalled: boolean;
  system_key: string | null;
}

/** Bulk edit (Package B): one selected item ref for
 *  POST /inventory/bulk, and the endpoint's result. A foreign id
 *  in the selection refuses the WHOLE batch with a 422. */
export interface BulkItemRef {
  kind: "tool" | "battery";
  id: string;
}

export interface BulkResult {
  action: string;
  affected: number;
  items: BulkItemRef[];
}

/** One row of the unified search (GET /inventory/search/all): a
 *  tool or a battery in its own public shape, marked by kind. */
export type AssetSearchItem =
  | (Tool & { item_kind: "tool" })
  | (Battery & { item_kind: "battery" });
