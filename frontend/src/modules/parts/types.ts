/** Used Parts module shapes — mirror backend/app/modules/parts/schemas.py. */

export type LocationLevel = "warehouse" | "aisle" | "bin" | "shelf" | "other";

export const LOCATION_LEVELS: { value: LocationLevel; label: string }[] = [
  { value: "warehouse", label: "Warehouse" },
  { value: "aisle", label: "Aisle" },
  { value: "bin", label: "Bin" },
  { value: "shelf", label: "Shelf" },
  { value: "other", label: "Other" },
];

export function levelLabel(level: string): string {
  return LOCATION_LEVELS.find((l) => l.value === level)?.label ?? "Other";
}

export interface PartLocation {
  id: string;
  name: string;
  level: string;
  parent_id: string | null;
  /** Parts filed directly at this node. */
  own_count: number;
  /** Parts in this node + every descendant (the rollup). */
  part_count: number;
  created_at: string;
  updated_at: string;
}

export interface PartAttachment {
  key: string;
  filename: string;
  kind: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string | null;
  url: string;
}

export interface PartLocationRef {
  id: string;
  name: string;
  level: string;
  /** "Warehouse / Aisle 3 / Bin 12" — root to node. */
  path: string;
}

export interface Part {
  id: string;
  title: string;
  quantity: number;
  condition: string;
  notes: string;
  location_id: string | null;
  location: PartLocationRef | null;
  custom_data: Record<string, unknown>;
  attachments: PartAttachment[];
  converted_tool_id: string | null;
  // Community pool (2026-10-19).
  year: number | null;
  make: string;
  model: string;
  engine: string;
  category: string;
  asking_price: string | number | null;
  public_area_label: string | null;
  visibility_override: string | null;
  show_phone_override: boolean | null;
  /** Resolved visibility: the part's override, else its
   *  category's pool setting, else the pool default. */
  visibility: string;
  /** Resolved public AND the pool itself is switched on. */
  is_public: boolean;
  created_at: string;
  updated_at: string;
}

export interface PartWrite {
  title: string;
  quantity: number;
  condition: string;
  notes: string;
  location_id: string | null;
  custom_data: Record<string, unknown>;
  year?: number | null;
  make?: string;
  model?: string;
  engine?: string;
  category?: string;
  asking_price?: string | null;
  public_area_label?: string | null;
  visibility?: string | null;
  show_phone_override?: boolean | null;
}

export interface PoolSettings {
  default_visibility: string;
  category_visibility: Record<string, string>;
}

/** THE pool listing payload — the exact-key contract from the
 *  API: no storage location, no notes, no email; the phone only
 *  while the seller opted in. */
export interface CommunityListing {
  id: string;
  title: string;
  quantity: number;
  condition: string;
  category: string;
  year: number | null;
  make: string;
  model: string;
  engine: string;
  asking_price: string | number | null;
  area_label: string | null;
  photos: { filename: string; url: string }[];
  seller_id: string;
  seller_name: string;
  seller_member_since: string;
  /** Wave 3: the asking price is in the SELLER's currency. */
  seller_currency: string;
  phone: string | null;
  created_at: string;
  updated_at: string;
}

export interface PartsStats {
  parts_count: number;
  total_units: number;
}

export interface ConvertResult {
  part: Part;
  tool_id: string;
}
