import {
  useEffect,
  useState,
} from "react";
import {
  WarrantyStatus,
} from "./types";

export const INVENTORY_SETTING_IDS: readonly string[] = [
  "import-matching",
  "sharing",
  "custom-fields",
  "wizard-defaults",
];

export const CATEGORY_SUFFIXES = new Set([
  "inc", "incorporated", "corp", "corporation", "llc", "ltd",
  "limited", "co", "company", "llp", "lp",
]);

/** Client mirror of the server's category identity
 *  (inventory matching.normalize_match_value): casefold,
 *  punctuation to spaces, a leading "the" dropped, trailing
 *  company suffixes folded repeatedly. Used ONLY to decide
 *  which starred link is lit — the filter itself carries the
 *  raw name and is matched server-side. */
export function categoryKey(value: string): string {
  const words = value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (words[0] === "the") words.shift();
  while (words.length > 1 && CATEGORY_SUFFIXES.has(words[words.length - 1])) {
    words.pop();
  }
  return words.join(" ");
}

export interface Filters {
  category: string;
  /** Dealer filter (intermingling, 2026-10-25): a company id, or
   *  "" for all dealers. The server matches the dealer TAG. */
  dealer: string;
}

export const EMPTY_FILTERS: Filters = {
  category: "",
  dealer: "",
};

// The row is All + the starred categories, and the list below
// is the one stream over both kinds (owner spec 2026-10-25).
// The old Tools / Batteries kind views are gone — kind is a
// CATEGORY now (the starred Batteries starter does that job in
// the row) — and the Sold link/view left Inventory the same
// day: sold items live in Tools For Sale → My Listings now, in
// its Sold items section (the sale ledger, SoldSection). The
// view was never persisted (not in localStorage, not in the
// URL), so removing it strands no one.

export const WARRANTY_OPTIONS: { value: "" | WarrantyStatus | "due"; label: string }[] = [
  { value: "", label: "Any warranty status" },
  { value: "due", label: "Expired or expiring" },
  { value: "in_warranty", label: "In warranty" },
  { value: "expiring_soon", label: "Expiring soon" },
  { value: "expired", label: "Expired" },
  { value: "unknown", label: "Unknown" },
];

/* -- sort (Package B): the sort menu, persisted per user in
 *    localStorage. The storage keys are SCOPED by user id
 *    (cross-account bleed sweep, owner bug report 2026-10-24):
 *    unscoped, one account's sort greeted the next account on
 *    the same browser.
 *    The Tiles | List layout choice that rode beside the sort
 *    is GONE (owner, 2026-11-05): the inventory is a list, only
 *    a list — the tile rendering and its stored per-user
 *    preference were removed outright, so an old "tiles" pref
 *    simply lands on the list like it never existed. --------- */

export type SortKey =
  | "warranty_end"
  | "featured"
  | "name"
  | "brand"
  | "dealer"
  | "status"
  | "category"
  | "location"
  | "purchase_date"
  | "price"
  | "quantity"
  | "created_at"
  | "updated_at";

export const SORT_KEY_STORAGE = "tv-inventory-sort";

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  // The DEFAULT order (owner spec 2026-10-25): date added,
  // newest first — labels ride the dictionary (en+es) at
  // render. "Featured" (F1-04: photo items first, then
  // recently updated) stays an explicit pick, no longer the
  // default. F2-17: every label STATES its natural direction,
  // the way Marketplace's sort labels do, and the direction
  // toggle beside the select reverses it (the server honours
  // sort_dir).
  { value: "created_at", label: "Date added (newest first)" },
  { value: "featured", label: "Photos first" },
  { value: "name", label: "Name (A → Z)" },
  { value: "brand", label: "Brand (A → Z)" },
  { value: "dealer", label: "Dealer (A → Z)" },
  { value: "status", label: "Status (A → Z)" },
  { value: "category", label: "Category (A → Z)" },
  { value: "location", label: "Location (A → Z)" },
  { value: "purchase_date", label: "Purchase date (oldest first)" },
  { value: "price", label: "Price (low to high)" },
  { value: "quantity", label: "Quantity (low to high)" },
  { value: "updated_at", label: "Recently updated (newest first)" },
  { value: "warranty_end", label: "Warranty ending (soonest first)" },
];

/** The direction each sort runs in until the user reverses it:
 *  recency sorts newest-first, value sorts ascending. */
export function sortConvention(key: SortKey): "asc" | "desc" {
  return key === "featured" || key === "created_at" || key === "updated_at"
    ? "desc"
    : "asc";
}

export const SORT_DIR_STORAGE = "tv-inventory-sort-dir";

/** One-time sort-prefs reset (owner spec 2026-10-25): the
 *  default changed to date added, newest first, and choices
 *  stored under the old regime would silently override it —
 *  so the stored sort + direction for a scope are dropped
 *  ONCE, landing the account on the new default. The version
 *  stamp is what gets stored instead: any choice made after
 *  the reset persists normally. */
export const SORT_PREFS_VERSION_KEY = "tv-inventory-sort-version";
export const SORT_PREFS_VERSION = "2026-10-25";

export function ensureSortPrefsVersion(scope: string) {
  try {
    if (
      localStorage.getItem(`${SORT_PREFS_VERSION_KEY}:${scope}`) ===
      SORT_PREFS_VERSION
    ) {
      return;
    }
    localStorage.removeItem(`${SORT_KEY_STORAGE}:${scope}`);
    localStorage.removeItem(`${SORT_DIR_STORAGE}:${scope}`);
    localStorage.setItem(
      `${SORT_PREFS_VERSION_KEY}:${scope}`,
      SORT_PREFS_VERSION,
    );
  } catch {
    /* persistence is a nicety, never a blocker */
  }
}

export function storedSortDir(scope = "anon"): "asc" | "desc" | null {
  ensureSortPrefsVersion(scope);
  try {
    const v = localStorage.getItem(`${SORT_DIR_STORAGE}:${scope}`);
    return v === "asc" || v === "desc" ? v : null;
  } catch {
    return null;
  }
}

export function storedSort(scope = "anon"): SortKey {
  ensureSortPrefsVersion(scope);
  try {
    const value = localStorage.getItem(`${SORT_KEY_STORAGE}:${scope}`);
    // No stored choice = the default: date added, newest first
    // (owner spec 2026-10-25). A sort the user actually picked
    // (after the one-time reset) is always honoured as-is.
    return SORT_OPTIONS.some((o) => o.value === value)
      ? (value as SortKey)
      : "created_at";
  } catch {
    return "created_at";
  }
}

/** The fields sorting reads — Tool and Battery both carry them. */
export interface SortableItem {
  name: string;
  brand: string;
  category: string;
  location: string;
  purchase_date: string | null;
  purchase_price: string | null;
  quantity: number;
  is_set?: boolean;
  set?: { price_total: string | null } | null;
  created_at: string;
  updated_at: string;
}

/** Extended total for sorting/display: purchase_price × quantity;
 *  for sets, the set's own price_total when the payload carries it. */
export function extendedPrice(item: SortableItem): number | null {
  if (item.is_set && item.set && item.set.price_total !== null && item.set.price_total !== undefined) {
    const total = Number(item.set.price_total);
    return Number.isNaN(total) ? null : total;
  }
  if (item.purchase_price === null || item.purchase_price === undefined) return null;
  const unit = Number(item.purchase_price);
  return Number.isNaN(unit) ? null : unit * (item.quantity || 1);
}

/* Sorting runs on the SERVER (step-4 fix D2): the sort key rides
 * every list request and the server orders the owner's WHOLE
 * filtered set under the same convention this menu always used —
 * value sorts ascending, recency sorts (date added / recently
 * updated) newest first, missing values last — then pages it.
 * The page accumulates pages via "Load more" so ANY item in the
 * vault is reachable by browsing, not just the first window. */

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}


/**
 * The LIST view's header row (list standard, 2026-11-02): one
 * label per column, laid out on the SAME grid template as the
 * record rows (surfaces.css .tv-inv-thead / .tv-inv-row — the
 * dealer directory's DirectoryTable pattern). The second
 * column is Dealer/Brand (owner, 2026-11-12): brand and the
 * dealer tag in one column. The leading select column is
 * PERMANENT (owner, 2026-11-15): every row always carries its
 * checkbox, and the column's header cell carries the
 * Select all / Select none TEXT LINK, above the checkboxes
 * exactly as ordered. The trailing column carries the per-row
 * actions — its header cell is blank-visible with an
 * accessible name, the shared DataTable's actions-column
 * convention (Support, Admin). */
export type BulkModalKind =
  | "location"
  | "dealer"
  | "brand"
  | "category"
  | "tag"
  | "share"
  | "delete"
  | null;
