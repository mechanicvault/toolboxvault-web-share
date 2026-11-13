/** Claims module wire types — mirrors backend/app/modules/claims/schemas.py. */

export type ClaimStatus =
  | "draft"
  | "filed"
  | "in_review"
  | "approved"
  | "denied"
  | "paid"
  | "closed"
  // The warranty ladder (two-types build, 2026-10-25; overhauled
  // 2026-11-06 to Ryan's 8 statuses): a broken item's claim walks
  // these instead of the insurance spine. "closed" is NOT one of
  // them anymore — closing is a layer (closed_at), not a status.
  | "not_reported"
  | "reported"
  | "waiting_on_agent"
  | "waiting_on_parts"
  | "in_repair"
  | "agent_has_tool"
  | "completed"
  | "backordered";

/** The warranty statuses in Ryan's order — the claim page's
 *  status picker walks exactly this list. */
export const WARRANTY_STATUSES: ClaimStatus[] = [
  "not_reported",
  "reported",
  "waiting_on_agent",
  "waiting_on_parts",
  "in_repair",
  "agent_has_tool",
  "completed",
  "backordered",
];

/** Ryan's three filing routes (2026-11-05 #6): with the agent,
 *  on your own, or straight with the dealer company. */
export type FiledWith = "agent" | "self" | "corporate";

/** The two kinds of claim (owner model, 2026-10-25). */
export type ClaimKind = "warranty_repair" | "insurance_disaster";

export type IncidentType = "theft" | "loss" | "damage" | "fire" | "other";
export type TargetKind = "tool" | "battery" | "set" | "piece";
/** Line value bases. "purchase" (what the owner paid) and
 * "entered" (the owner's own figure) are the only bases a NEW
 * line can take — claim money is purchase cost (owner ruling,
 * 2026-11-06). "replacement" / "msrp" remain in the type
 * because lines priced before the ruling still carry them. */
export type ValueBasis = "purchase" | "replacement" | "msrp" | "entered";
export type EvidenceKind = "photo" | "document" | "receipt";
export type CommChannel =
  | "phone"
  | "email"
  | "mail"
  | "portal"
  | "in_person"
  | "other";

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

export interface ClaimLine {
  id: string;
  claim_id: string;
  target_kind: TargetKind;
  target_id: string;
  set_id: string | null;
  target_name: string;
  set_name: string;
  /** Piece lines: the piece's own part/model number and the
   *  parent set's model number — both ride the claim so a dealer
   *  can find the piece by either (owner steering, 2026-10-25). */
  target_part_number: string;
  set_model_number: string;
  include_addons: boolean;
  value_basis: ValueBasis;
  /** Decimal string from the API (money, snapshotted). */
  amount: string | null;
  /** Wave 3: the per-line claim-package toggle — excluded lines
   * stay on the claim but leave the generated package PDF. */
  include_in_package: boolean;
  created_at: string;
}

export interface ClaimEvidence {
  id: string;
  claim_id: string;
  source: "reference" | "upload";
  item_kind: "tool" | "battery" | "piece" | null;
  item_id: string | null;
  attachment_key: string;
  filename: string;
  kind: EvidenceKind;
  content_type: string;
  size_bytes: number;
  url: string | null;
  /** False when a referenced file has since left its item. */
  available: boolean;
  created_at: string;
}

export interface ClaimCommunication {
  id: string;
  claim_id: string;
  channel: CommChannel;
  contact: string;
  summary: string;
  occurred_at: string;
  created_at: string;
  updated_at: string;
  /** Who wrote the entry (two-party warranty log): empty on
   *  legacy rows, which are the owner's. */
  author_id: string | null;
  author_role: "" | "owner" | "dealer";
  author_name: string;
}

/** One agent a warranty claim can be pointed at (agent scope,
 *  2026-10-31) — the same shape serves the claim's current agent
 *  (Claim.warranty_agent) and the owner's pick list
 *  (Claim.agent_options). Exactly one of agent_user_id /
 *  private_agent_id is set. has_access is live only on the
 *  claim's own agent: true when the pointer resolves to a
 *  platform account whose link to the dealer is VERIFIED. */
export interface WarrantyAgent {
  kind: "platform" | "private";
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
  phone: string;
  email: string;
  account_number: string | null;
  has_access: boolean;
}

/** The broken-item form's agent choices for one target. */
export interface WarrantyFilingOptions {
  dealer_company_id: string | null;
  dealer_name: string;
  agents: WarrantyAgent[];
  default_agent_user_id: string | null;
  default_private_agent_id: string | null;
}

export interface Claim {
  id: string;
  claim_number: string;
  /** Which of the two kinds this claim is. */
  kind: ClaimKind;
  /** A warranty claim's dealer (snapshot at creation); empty on
   *  insurance claims. */
  dealer_company_id: string | null;
  dealer_name: string;
  /** Which of Ryan's three filing routes the claim took — who
   *  its counterparty seat is (claims overhaul, 2026-11-06). */
  filed_with: FiledWith;
  /** When the dealer was told about a warranty claim, and how:
   *  "system" = Toolbox Vault reported it, "user" = the owner
   *  told them. Empty until reported. */
  reported_at: string | null;
  report_method: "" | "system" | "user";
  /** Who is looking: the claim's owner, or a dealer the claim
   *  is addressed to (both parties drive a warranty claim). */
  viewer_role: "owner" | "dealer";
  owner_name: string;
  owner_email: string;
  /** The claim's amounts are the OWNER's money: they label in
   *  this currency on every surface, never the viewer's. */
  owner_currency: string;
  insurer_name: string;
  policy_number: string;
  /** The manufacturer's claim / case number (warranty claims
   *  only — they carry no insurance policy; insurance claims
   *  always carry "" here and never render the field). */
  manufacturer_case_number: string;
  /** The repair working end ON the claim (repairs ∪ claims
   *  merge, 2026-11-04): where the item was sent for repair,
   *  what the repair cost, when the work finished. Warranty
   *  claims only — insurance claims leave them empty. */
  repair_sent_to: string;
  repair_cost: string | null;
  repair_completed_at: string | null;
  /** The warranty claim's ONE agent (agent scope, 2026-10-31),
   *  or null: no agent — the claim is the owner's alone. Always
   *  null on insurance claims. */
  warranty_agent: WarrantyAgent | null;
  /** Owner seat only: the agents the owner may point this claim
   *  at (their agents on record for the claim's dealer). */
  agent_options: WarrantyAgent[];
  /** The agent block snapshotted from the My Insurance profile at
   *  creation (Package C) — the claim keeps its own copy. */
  agent_name: string;
  agent_phone: string;
  agent_email: string;
  incident_type: IncidentType;
  incident_date: string | null;
  description: string;
  status: ClaimStatus;
  police_report_number: string;
  police_department: string;
  police_report_date: string | null;
  proof_of_loss_due: string | null;
  proof_of_loss_sent_at: string | null;
  depreciation_deadline: string | null;
  filed_at: string | null;
  closed_at: string | null;
  /** Wave 3: archive shelving — archived claims leave the
   * default list + the home stat, readable via the filter. */
  archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  lines: ClaimLine[];
  evidence: ClaimEvidence[];
  communications: ClaimCommunication[];
  checklist: ChecklistItem[];
  checklist_done: number;
  checklist_total: number;
  total_amount: string;
  allowed_transitions: ClaimStatus[];
}

export interface ClaimDealerRef {
  id: string;
  name: string;
}

/** The slim claim shape the dealer page and the item pages
 *  render (dealer intermingling): recognize it, click through. */
export interface LinkedClaim {
  id: string;
  claim_number: string;
  kind: ClaimKind;
  dealer_name: string;
  filed_with: FiledWith;
  status: ClaimStatus;
  insurer_name: string;
  incident_type: IncidentType;
  incident_date: string | null;
  total_amount: string;
  /** The repair working end (merge, 2026-11-04). */
  repair_sent_to: string;
  repair_cost: string | null;
  /** The owner's currency — total_amount is in it. */
  owner_currency: string;
  created_at: string;
  archived: boolean;
  items: string[];
}

export interface ItemClaims {
  current: LinkedClaim[];
  history: LinkedClaim[];
}

export interface ClaimSummary {
  id: string;
  claim_number: string;
  kind: ClaimKind;
  dealer_name: string;
  filed_with: FiledWith;
  insurer_name: string;
  policy_number: string;
  incident_type: IncidentType;
  incident_date: string | null;
  description: string;
  status: ClaimStatus;
  proof_of_loss_due: string | null;
  proof_of_loss_sent_at: string | null;
  depreciation_deadline: string | null;
  filed_at: string | null;
  reported_at: string | null;
  closed_at: string | null;
  archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  line_count: number;
  /** The first line's item name (widget options Wave 2: the
   *  home widget's recent-claims rows name it); "" when the
   *  claim carries no lines yet. */
  first_item_name: string;
  total_amount: string;
  /** The owner's currency — total_amount is in it. */
  owner_currency: string;
  checklist_done: number;
  checklist_total: number;
  /** Dealers this claim touches through its items' dealer tags
   *  (dealer intermingling) — drives the list's dealer filter and
   *  sort and the row's dealer links. */
  dealers: ClaimDealerRef[];
  /** Agent scope (2026-10-31): the warranty claim's agent, named
   *  on the owner's rows; "" for insurance claims / no agent. */
  warranty_agent_name: string;
  /** The claim's repair facts (merge, 2026-11-04): where the
   *  item was sent and what the repair cost, on the summary so
   *  list rows read them without a second fetch. */
  repair_sent_to: string;
  repair_cost: string | null;
  /** The manufacturer's claim / case number (warranty claims). */
  manufacturer_case_number: string;
}

export interface ClaimHeaderInput {
  insurer_name?: string;
  policy_number?: string;
  manufacturer_case_number?: string;
  agent_name?: string;
  agent_phone?: string;
  agent_email?: string;
  incident_type?: IncidentType;
  incident_date?: string | null;
  description?: string;
  police_report_number?: string;
  police_department?: string;
  police_report_date?: string | null;
  proof_of_loss_due?: string | null;
  depreciation_deadline?: string | null;
}

export interface TargetAttachment {
  key: string;
  filename: string;
  kind: EvidenceKind;
  content_type: string;
  size_bytes: number;
  url: string | null;
}

export interface TargetPiece {
  id: string;
  name: string;
  kind: "core" | "addon";
  part_number: string;
  serial_number: string;
  status: string;
  attachments: TargetAttachment[];
}

export interface ClaimTarget {
  kind: "tool" | "battery" | "set";
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  quantity: number;
  purchase_price: string | null;
  replacement_cost: string | null;
  msrp: string | null;
  attachments: TargetAttachment[];
  pieces: TargetPiece[];
}

export interface ClaimTargets {
  tools: ClaimTarget[];
  batteries: ClaimTarget[];
}

export interface ClaimsStats {
  open_claims_count: number;
}

/** The agent side's worklist row: a warranty claim currently
 *  routed to the viewer as its agent, plus the customer's name. */
export interface IncomingClaim extends ClaimSummary {
  owner_name: string;
}

/** POST /claims/warranty's answer: the claim, and whether the
 *  dealer has been told (and through which channels). */
export interface WarrantyCreateResult {
  claim: Claim;
  reported: boolean;
  report_via: string[];
}

/** POST /claims/replace-item's answer: the retired item, and
 *  the fresh one when the replacement was the exact same item. */
export interface ReplaceItemResult {
  retired_id: string;
  new_item: { kind: string; id: string; name: string } | null;
}
