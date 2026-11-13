/** Reports module types — mirrors backend/app/modules/reports. */

export interface ReportColumn {
  key: string;
  label: string;
  type: "text" | "money" | "number" | "date" | "photo";
  custom?: boolean;
  item_type?: string;
}

export interface ReportFilters {
  q?: string;
  kind?: string | null;
  category?: string | null;
  dealer_id?: string | null;
  tag?: string | null;
  location?: string | null;
  min_price?: string | null;
  max_price?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  warranty?: string | null;
  only_sets?: boolean;
  only_checked_out?: boolean;
}

export interface ReportSpec {
  columns?: string[] | null;
  filters?: ReportFilters;
  grouping?: string;
  sets_mode?: string;
  sort?: { key: string; direction: "asc" | "desc" };
  /** Display options (app-format furniture): the "#" row-number
   * overlay, the top summary block, and the PDF orientation. */
  show_row_numbers?: boolean;
  show_summary?: boolean;
  orientation?: "landscape" | "portrait";
}

/** A row's first photo (screen thumbnail) — null = placeholder. */
export interface ReportPhoto {
  key: string;
  filename: string;
  content_type: string;
  url: string;
}

export interface ReportRow {
  row_type: "asset" | "core_piece" | "addon_piece" | "attached_tool";
  kind: string;
  set_name: string | null;
  /** The "#" when row numbers are on; null when off. */
  number: number | null;
  photo: ReportPhoto | null;
  values: Record<string, string | number | null>;
  display: Record<string, string>;
}

export interface ReportSubtotal {
  count: number;
  price_total: string;
  replacement: string;
}

export interface ReportGroup {
  key: string;
  label: string;
  subtotal: ReportSubtotal;
  row_count: number;
  rows: ReportRow[];
}

/** The top summary block: the FULL filtered set (assets only for
 * items/units), never just the visible page. */
export interface ReportSummary {
  items: number;
  units: number;
  price_total: string;
  replacement: string;
}

/** The Prepared-For block's facts. phone/address are "" when the
 * owner hasn't set them — renderers treat "" as absent. */
export interface ReportPreparedFor {
  name: string;
  email: string;
  phone: string;
  address: string;
}

export interface ReportResult {
  columns: ReportColumn[];
  groups: ReportGroup[];
  totals: ReportSubtotal;
  summary: ReportSummary;
  prepared_for: ReportPreparedFor | null;
  options: {
    show_row_numbers: boolean;
    show_summary: boolean;
    orientation: string;
  };
  total_rows: number;
  grouping: string;
  sets_mode: string;
  page: number;
  page_size: number;
  pages: number;
}

export interface ReportConfigView {
  id: string;
  name: string;
  spec: ReportSpec;
  builtin: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/* -- Reports page redesign (2026-11-06): catalog, templates,
 *    history. The catalog is the wizard's source of truth — every
 *    type the system can produce, its home area, the formats a
 *    real producer exists for, and the settings kind it honestly
 *    supports. Templates store type + settings (never a frozen
 *    file); History stores the generated files themselves. */

export type ReportArea = "quick" | "accounting" | "admin";

export type ReportSettingsKind =
  | "none"
  | "year"
  | "year_or_all"
  | "period"
  | "inventory";

export interface CatalogType {
  key: string;
  home_area: ReportArea;
  formats: string[];
  settings: ReportSettingsKind;
  module: string | null;
  /** False when the module that owns this report's books is off
   *  for the signed-in user — listed, never runnable. */
  available: boolean;
  /** System-written, in the user's language. */
  name: string;
  description: string;
}

export interface ReportTemplateView {
  id: string;
  report_type: string;
  name: string;
  description: string;
  area: ReportArea;
  settings: Record<string, unknown>;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface HistoryEntry {
  id: string;
  template_id: string | null;
  name: string;
  report_type: string;
  format: string;
  content_type: string;
  size_bytes: number;
  settings: Record<string, unknown>;
  created_at: string | null;
}

export interface ReportsMeta {
  columns: ReportColumn[];
  default_columns: string[];
  groupings: { key: string; label: string }[];
  sets_modes: { key: string; label: string; hint: string }[];
  categories: string[];
  locations: string[];
  tags: string[];
}
