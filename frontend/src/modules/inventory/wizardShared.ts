import "./wizard.css";
import {todayLocalIso} from "../../lib/format";
import {
  BatteryFormValues,
  ToolFormValues,
} from "./types";

export const EMPTY_TOOL: ToolFormValues = {
  name: "",
  brand: "",
  model: "",
  serial_number: "",
  category: "",
  location_id: "",
  notes: "",
  purchase_price: "",
  purchase_date: "",
  replacement_cost: "",
  msrp: "",
  warranty_months: "",
  warranty_provider: "",
  warranty_contact: "",
  warranty_terms: "",
  warranty_type: "",
  quantity: "1",
  size: "",
  model_numbers: [""],
  serial_numbers: [""],
  upc: "",
  consumable: false,
  business_use: false,
  rebuy_store: "",
  rebuy_url: "",
  rebuy_sku: "",
  rebuy_notes: "",
  is_set: false,
  dealer_company_id: "",
  tag_ids: [],
  custom_data: {},
};

export const EMPTY_BATTERY: BatteryFormValues = {
  name: "",
  brand: "",
  model: "",
  serial_number: "",
  category: "",
  location_id: "",
  notes: "",
  purchase_price: "",
  purchase_date: "",
  replacement_cost: "",
  msrp: "",
  platform: "",
  voltage: "",
  capacity_ah: "",
  chemistry: "",
  warranty_months: "",
  warranty_provider: "",
  warranty_contact: "",
  warranty_terms: "",
  warranty_type: "",
  currently_in_tool_id: "",
  quantity: "1",
  upc: "",
  business_use: false,
  dealer_company_id: "",
  tag_ids: [],
  custom_data: {},
};

/* The wizard's today — the shared local-calendar helper
 * (lib/format), so a US-evening default is the user's own today,
 * not UTC's tomorrow. */
export function today(): string {
  return todayLocalIso();
}

// The wizard's truck-account charge (owner, 2026-10-31): with a
// dealer picked and a price entered, the buyer may put any
// portion of the price on his truck account with that dealer.
// The context is the truck module's own read for the company —
// which active accounts exist, whether an invite is waiting,
// and whose name a self-opened tab would land under.
export interface TruckWizardAccount {
  id: string;
  agent_name: string;
  balance: string;
}

export interface TruckWizardAgent {
  agent_user_id: string | null;
  private_agent_id: string | null;
  name: string;
  is_preferred: boolean;
  is_default: boolean;
  active_accounts: TruckWizardAccount[];
}

export interface TruckWizardContext {
  company_id: string;
  company_name: string;
  active_accounts: TruckWizardAccount[];
  invited_exists: boolean;
  new_account_agent_name: string | null;
  /** Every roster agent for the company (multi-preferred,
   *  2026-11-05); the top-level fields above are the display
   *  default agent's. */
  agents: TruckWizardAgent[];
}

export function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export type Branch = "fork" | "tool" | "battery";
export type StepId =
  | "lookup"
  | "basics"
  | "include"
  | "set"
  | "review"
  | "battery-pick"
  | "battery-lookup"
  | "battery-details"
  | string; // a WIZARD_SECTIONS key

export const pageStackStyle = { display: "grid", gap: "var(--spacing)" } as const;
export const pageWidthStyle = {
  maxWidth: "760px",
  margin: "0 auto",
  display: "grid",
  gap: "var(--spacing)",
} as const;
export const mutedStyle = { margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" } as const;
export const navRowStyle = {
  display: "flex",
  gap: "0.75rem",
  flexWrap: "wrap",
  alignItems: "center",
} as const;
export const checkColumnStyle = { display: "grid", gap: "0.7rem" } as const;

export interface DuplicateHit {
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  matched_on: string;
}

