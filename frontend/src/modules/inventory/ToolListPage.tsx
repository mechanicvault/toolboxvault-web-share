import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  BrandIcon,
  Button,
  Checkbox,
  EmptyState,
  FormField,
  InventorySkeleton,
  Modal,
  Panel,
  SearchBar,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  TextInput,
  useToast,
  LinkButton,
  type SectionPageFact,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import type { InventoryStats } from "../../components/OverviewRow";
import { api, apiPage, ApiError, TOKEN_KEY } from "../../lib/api";
import { activeLocale } from "../../lib/format";
import { getBorrowingOverview } from "../borrowing/api";
import {
  CheckoutModal,
  type CheckoutTarget,
} from "../borrowing/components/CheckoutModal";
import { standingText } from "../borrowing/format";
import type { Checkout } from "../borrowing/types";
import { useAuth } from "../core/AuthContext";
import { useMyModules } from "../core/MyModules";
import { groupLayerWaived } from "../core/accountTypes";
import {
  SETTINGS_SECTIONS,
  sectionVisibleFor,
} from "../core/settingsMeta";
import {
  SettingsActionsMenu,
  type SettingsActionEntry,
} from "../core/SettingsActionsMenu";
import {
  accountTypeLabel,
  enabledShareGroups,
  RequireAuth,
  type ShareGroupState,
  type SharingOverview,
} from "../core";
import { listCompanies } from "../dealers/api";
import { DealerPicker } from "../dealers/components/DealerFields";
import { getExpansionCounts } from "../tool-expansion/api";
import { ExpansionBadge } from "../tool-expansion/components";
import type { DealerCompany } from "../dealers/types";
import { batterySpecChips } from "./components/BatteryCard";
import { ItemActionsMenu } from "./components/ItemActionsMenu";
import type { ItemStatusData } from "./components/ItemStatusStrip";
import { ItemPhoto } from "./components/ItemPhoto";
import { FieldSuggest } from "./components/FieldSuggest";
import { LocationTreePicker } from "./components/LocationTreePicker";
import { LocationTreeManager } from "./components/LocationTreeManager";
import {
  buildLocationTree,
  listLocationNodes,
} from "./components/locationTree";
import { useT } from "../../i18n/LocaleContext";
import { StandingBadge } from "./components/StandingBadge";
import { money } from "./format";
import type {
  AssetSearchItem,
  Battery,
  BulkResult,
  CategoryRow,
  LocationNode,
  Standing,
  Tag,
  Tool,
  WarrantyStatus,
} from "./types";
import { categoryDisplayName } from "./categoryLabel";

// The Settings sections this page owns (settingsMeta ids):
// the header Actions menu's Settings group carries exactly
// these, each landing on its own section (Actions → Settings,
// owner order 2026-11-09).
const INVENTORY_SETTING_IDS: readonly string[] = [
  "import-matching",
  "sharing",
  "custom-fields",
  "wizard-defaults",
];

// Selection-mode bars (labels / poster / bulk): one shared row
// layout for the panel that rides above the list in a select mode.
const selectionBarRowStyle: CSSProperties = {
  display: "flex",
  gap: "0.75rem",
  alignItems: "center",
  flexWrap: "wrap",
};

const CATEGORY_SUFFIXES = new Set([
  "inc", "incorporated", "corp", "corporation", "llc", "ltd",
  "limited", "co", "company", "llp", "lp",
]);

/** Client mirror of the server's category identity
 *  (inventory matching.normalize_match_value): casefold,
 *  punctuation to spaces, a leading "the" dropped, trailing
 *  company suffixes folded repeatedly. Used ONLY to decide
 *  which starred link is lit — the filter itself carries the
 *  raw name and is matched server-side. */
function categoryKey(value: string): string {
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

interface Filters {
  category: string;
  minPrice: string;
  maxPrice: string;
  minReplacement: string;
  maxReplacement: string;
  /** Dealer filter (intermingling, 2026-10-25): a company id, or
   *  "" for all dealers. The server matches the dealer TAG. */
  dealer: string;
}

const EMPTY_FILTERS: Filters = {
  category: "",
  minPrice: "",
  maxPrice: "",
  minReplacement: "",
  maxReplacement: "",
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

const WARRANTY_OPTIONS: { value: "" | WarrantyStatus | "due"; label: string }[] = [
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

type SortKey =
  | "warranty_end"
  | "featured"
  | "name"
  | "brand"
  | "dealer"
  | "category"
  | "location"
  | "purchase_date"
  | "price"
  | "created_at"
  | "updated_at";

const SORT_KEY_STORAGE = "tv-inventory-sort";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
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
  { value: "category", label: "Category (A → Z)" },
  { value: "location", label: "Location (A → Z)" },
  { value: "purchase_date", label: "Purchase date (oldest first)" },
  { value: "price", label: "Price (low to high)" },
  { value: "updated_at", label: "Recently updated (newest first)" },
  { value: "warranty_end", label: "Warranty ending (soonest first)" },
];

/** The direction each sort runs in until the user reverses it:
 *  recency sorts newest-first, value sorts ascending. */
function sortConvention(key: SortKey): "asc" | "desc" {
  return key === "featured" || key === "created_at" || key === "updated_at"
    ? "desc"
    : "asc";
}

const SORT_DIR_STORAGE = "tv-inventory-sort-dir";

/** One-time sort-prefs reset (owner spec 2026-10-25): the
 *  default changed to date added, newest first, and choices
 *  stored under the old regime would silently override it —
 *  so the stored sort + direction for a scope are dropped
 *  ONCE, landing the account on the new default. The version
 *  stamp is what gets stored instead: any choice made after
 *  the reset persists normally. */
const SORT_PREFS_VERSION_KEY = "tv-inventory-sort-version";
const SORT_PREFS_VERSION = "2026-10-25";

function ensureSortPrefsVersion(scope: string) {
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

function storedSortDir(scope = "anon"): "asc" | "desc" | null {
  ensureSortPrefsVersion(scope);
  try {
    const v = localStorage.getItem(`${SORT_DIR_STORAGE}:${scope}`);
    return v === "asc" || v === "desc" ? v : null;
  } catch {
    return null;
  }
}

function storedSort(scope = "anon"): SortKey {
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
interface SortableItem {
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

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Row spacer for the bulk selection bar (fixes pack, 2026-10-25). */
const SPACER_STYLE = { flex: 1 } as const;

/** The LIST view's header row (list standard, 2026-11-02): one
 *  label per column, laid out on the SAME grid template as the
 *  record rows (surfaces.css .tv-inv-thead / .tv-inv-row — the
 *  dealer directory's DirectoryTable pattern). The leading
 *  select column exists only while a selection mode is armed;
 *  the trailing column carries the per-row actions — its header
 *  cell is blank-visible with an accessible name, the shared
 *  DataTable's actions-column convention (Support, Admin). */
function InventoryListHead({ selecting }: { selecting: boolean }) {
  const t = useT();
  return (
    <div className="tv-inv-thead" role="row">
      {selecting && (
        <span role="columnheader" aria-label={t("inventory.col.select")} />
      )}
      <span role="columnheader">{t("inventory.col.item")}</span>
      <span role="columnheader">{t("inventory.col.brand")}</span>
      <span role="columnheader">{t("inventory.col.status")}</span>
      <span className="tv-inv-th--num" role="columnheader">
        {t("inventory.col.qty")}
      </span>
      <span className="tv-inv-th--num" role="columnheader">
        {t("inventory.col.price")}
      </span>
      <span role="columnheader" aria-label={t("inventory.actions")} />
    </div>
  );
}

/** A row's lending footer data (borrowing module): the item's
 *  current standing chip. Supplied by the list page, which owns
 *  the borrowing read; absent when borrowing isn't available. */
export interface RowLending {
  chip: string;
  /** The full standing text ("Checked out to … · due …"), carried
   *  as the pill's hover title (sweep B2-F6). */
  title?: string;
  tone: "accent" | "warning" | "danger";
}

/** One item in LIST layout: a TRUE list row (list standard,
 *  2026-11-02) — one record per row, each fact in its OWN column
 *  across the row on the header's grid template: thumbnail +
 *  name · brand · status badges · quantity · extended price,
 *  with the expansion badge and the item's Actions menu riding
 *  a trailing actions column. (The Model # and Location columns
 *  left the list on the owner's word, 2026-11-05 — both facts
 *  still live on the item itself and its page.) Battery spec
 *  chips (F1-16) stay as the item cell's sub-line, the way the
 *  battery page carries them. Clicking any fact cell opens the
 *  item page, as the old row-wide button did; the selection
 *  checkbox and the actions are siblings of the open control. */
function AssetRow({
  kind,
  item,
  onOpen,
  selection,
  lending,
  actions,
  badge,
}: {
  kind: "tool" | "battery";
  item: Tool | Battery;
  onOpen: () => void;
  selection?: { selected: boolean; onToggle: () => void; label?: string };
  lending?: RowLending | null;
  /** The item's Actions menu (the item page's ItemActionsMenu) —
   *  it replaced the row's lone Check out button (owner,
   *  2026-11-05). */
  actions?: ReactNode;
  /** Tool Expansion cart badge — a sibling of the open button,
   *  like the actions menu; absent when the item has no live
   *  suggestions or the module isn't effective. */
  badge?: ReactNode;
}) {
  const t = useT();
  const photo = item.attachments.find((a) => a.kind === "photo");
  const inactive = item.active === false;
  const total = extendedPrice(item);
  // F1-16: battery rows carry the battery's spec facts (deduped
  // chips as one line), the same facts its page headlines.
  const specLine =
    kind === "battery" ? batterySpecChips(item as Battery).join(" · ") : "";
  return (
    /* F1-12: a true list row — the parent .tv-inv-list supplies the
       shared surface + hairline separators; the row is not a card. */
    <div className={`tv-inv-row${inactive ? " is-inactive" : ""}`} role="row">
      {selection && (
        <div className="tv-inv-cell tv-inv-cell--select" role="cell">
          <Checkbox
            label={selection.label ?? "Select"}
            checked={selection.selected}
            onChange={selection.onToggle}
          />
        </div>
      )}
      <div className="tv-inv-cell tv-inv-cell--item tv-inv-fact" role="cell">
        <button
          type="button"
          onClick={onOpen}
          className="tv-open-btn tv-inv-open"
          aria-label={`Open ${item.name}`}
        >
          <ItemPhoto photo={photo} name={item.name} brand={item.brand} variant="row" />
          <span className="tv-inv-name-stack">
            <strong className="tv-inv-name" title={item.name}>
              {item.name}
            </strong>
            {(kind === "battery" || specLine) && (
              <span className="tv-inv-sub">
                {kind === "battery" ? "Battery" : ""}
                {specLine
                  ? `${kind === "battery" ? " · " : ""}${specLine}`
                  : ""}
              </span>
            )}
          </span>
        </button>
      </div>
      <div className="tv-inv-cell tv-inv-fact" role="cell" onClick={onOpen}>
        {item.brand || "—"}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--status tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        {inactive ? (
          <Badge tone="warning">Inactive</Badge>
        ) : (
          <StandingBadge standing={item.standing} />
        )}
        {/* Sweep B2-F6: an in-service row with no loan says so —
            "Available", the same pill the item header wears —
            instead of a blank cell that could mean anything. */}
        {!inactive && !lending && item.standing === "in_service" && (
          <Badge tone="success" dot>
            {t("inventory.status.available")}
          </Badge>
        )}
        {item.replaced_on && <Badge tone="neutral">Replaced</Badge>}
        {lending && (
          <span title={lending.title ?? lending.chip} className="tv-inv-status-pillwrap">
            <Badge tone={lending.tone} dot>
              {lending.chip}
            </Badge>
          </span>
        )}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--num tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        {item.quantity}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--num tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        <strong>{total === null ? "—" : money(String(total))}</strong>
      </div>
      <div className="tv-inv-cell tv-inv-cell--actions" role="cell">
        {badge}
        {actions}
      </div>
    </div>
  );
}

type BulkModalKind =
  | "location"
  | "dealer"
  | "brand"
  | "category"
  | "tag"
  | "share"
  | "delete"
  | null;

/**
 * Asset Inventory list: three views over the same vault — All
 * (tools + batteries together), Tools, and Batteries. Package B
 * slimmed the toolbar to ONE row, added Tiles | List layouts and
 * sorting (both persisted per user), standing badges, and a bulk
 * edit mode with a sticky action bar riding POST /inventory/bulk.
 * Sorting + paging run on the server (step-4 fix D2).
 * Owner redesign 2026-10-24: the toolbar leads with two
 * location dropdowns — Location (tier-1) and Sub Location
 * (tier-2), each option showing its server subtree count —
 * driving the same subtree URL filter the tree picker drove.
 * Main tab layout 2026-11-10 (program lane 2): the page wears
 * the shared SectionPageHeader; the 2026-10-24 commands
 * hamburger is REMOVED (owner order 2026-11-09) — its commands
 * are the header Actions menu's entries, its Settings group
 * carries this page's four Settings sections. The search +
 * filter bar first sat in a panel directly under the header;
 * the owner overruled that the same morning (2026-11-10,
 * with his screenshot): "in the header bar" means INSIDE it —
 * the bar rides the header panel itself, through the kit's
 * toolbar slot, in the same bar as the Actions button, and
 * the header's facts row carries his vault stats (total
 * items, total value, total quantity).
 * Batteries are first-class assets here, not attachments to tools.
 */
export default function ToolListPage() {
  const t = useT();
  const { user } = useAuth();
  // Per-user scope for the sort prefs below. Null until
  // /core/me lands: the state initializers read the anonymous
  // scope (defaults), a re-read effect below swaps in this
  // user's stored picks, and the write effects hold off until
  // the scope is known so defaults never overwrite real prefs.
  const prefScope = user ? user.id : null;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // Bin-label QRs land here as /inventory?location=<value>: the
  // location filter rides the URL (server-side, exact match) until
  // the user clears it.
  const locationParam = searchParams.get("location") ?? "";
  // The location TREE filter (Package B) rides its own URL param:
  // /inventory?location_id=<node> filters by the node's subtree.
  const locationIdParam = searchParams.get("location_id") ?? "";
  // F5-06: the header search submits here as ?q=… (Inventory's
  // smart search does the rest).
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  // Smart search (wave 4): the parser's read of the query line,
  // echoed back by the server ("Searching for: …" chips).
  const [searchChips, setSearchChips] = useState<
    { kind: string; label: string }[]
  >([]);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(() => Boolean(searchParams.get("warranty")));
  // The location tree, loaded for the Location / Sub Location
  // dropdowns (the toolbar tree picker retired with them). Each
  // node carries the server's subtree_item_count — the numbers
  // the dropdown options show. Reloaded after bulk runs (items
  // move) and whenever the manager modal reports a change.
  const [locationNodes, setLocationNodes] = useState<LocationNode[]>([]);
  const [locationNodesLoaded, setLocationNodesLoaded] = useState(false);
  const [locationTreeOk, setLocationTreeOk] = useState(false);
  const [locationTick, setLocationTick] = useState(0);
  const [locationManagerOpen, setLocationManagerOpen] = useState(false);
  const [platform, setPlatform] = useState("");
  // F5-02: the warranty view rides the URL — Home's warranty
  // counters land here with ?warranty=due&sort=warranty_end
  // (expired + expiring, soonest end first). "due" is the
  // combined filter the backend search understands.
  const warrantyParam = searchParams.get("warranty") ?? "";
  const [warranty, setWarranty] = useState<"" | WarrantyStatus | "due">(
    () =>
      (["in_warranty", "expiring_soon", "expired", "unknown", "due"].includes(warrantyParam)
        ? warrantyParam
        : "") as "" | WarrantyStatus | "due",
  );
  const [tagId, setTagId] = useState("");
  const [tagOptions, setTagOptions] = useState<Tag[]>([]);
  // Dealer filter options (intermingling): the companies the
  // dealers module answers with — directory + the user's own.
  // null = the module didn't answer (off/unassigned) and the
  // Dealer filter field hides, the DealerPicker's own posture.
  const [dealerOptions, setDealerOptions] = useState<DealerCompany[] | null>(
    null,
  );
  useEffect(() => {
    let cancelled = false;
    listCompanies()
      .then((rows) => {
        if (!cancelled) setDealerOptions(rows);
      })
      .catch(() => {
        if (!cancelled) setDealerOptions(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [sortKey, setSortKey] = useState<SortKey>(() =>
    searchParams.get("sort") === "warranty_end" ? "warranty_end" : storedSort(),
  );
  const [sortDir, setSortDir] = useState<"asc" | "desc">(
    () =>
      searchParams.get("sort") === "warranty_end"
        ? "asc"
        : (storedSortDir() ?? sortConvention(storedSort())),
  );
  const [refreshTick, setRefreshTick] = useState(0);

  // W-01: the URL-driven state above (q / warranty / sort) is
  // seeded by the initializers on MOUNT only — but the shell keys
  // its page wrapper on the pathname, so a navigation that changes
  // only the query string (the header search submitted while
  // already on /inventory is the daily case) remounts nothing and
  // the seed never re-ran: the query was silently dropped. Sync
  // each param when its VALUE changes, so a warm navigation lands
  // exactly what a cold load of the same URL would show. The refs
  // hold the last-applied value, so local edits (typing in the
  // search box, changing the sort by hand) never fight the sync —
  // only a genuine param change applies.
  const urlQ = searchParams.get("q") ?? "";
  const appliedQ = useRef(urlQ);
  useEffect(() => {
    if (appliedQ.current !== urlQ) {
      appliedQ.current = urlQ;
      setQuery(urlQ);
    }
  }, [urlQ]);
  const appliedWarranty = useRef(warrantyParam);
  useEffect(() => {
    if (appliedWarranty.current !== warrantyParam) {
      appliedWarranty.current = warrantyParam;
      setWarranty(
        (
          ["in_warranty", "expiring_soon", "expired", "unknown", "due"].includes(
            warrantyParam,
          )
            ? warrantyParam
            : ""
        ) as "" | WarrantyStatus | "due",
      );
      setFiltersOpen(Boolean(warrantyParam));
    }
  }, [warrantyParam]);
  const urlSort = searchParams.get("sort") ?? "";
  const appliedSort = useRef(urlSort);
  useEffect(() => {
    if (appliedSort.current !== urlSort) {
      appliedSort.current = urlSort;
      if (urlSort === "warranty_end") {
        setSortKey("warranty_end");
        setSortDir("asc");
      }
    }
  }, [urlSort]);

  // Swap in this user's stored picks once the scope is known
  // (the initializers ran pre-auth against the anonymous
  // scope). The ?sort=warranty_end URL seed keeps precedence,
  // exactly as it does in the initializers.
  const prefsLoadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!prefScope || prefsLoadedFor.current === prefScope) return;
    prefsLoadedFor.current = prefScope;
    if (searchParams.get("sort") !== "warranty_end") {
      const sort = storedSort(prefScope);
      setSortKey(sort);
      setSortDir(storedSortDir(prefScope) ?? sortConvention(sort));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefScope]);

  useEffect(() => {
    if (!prefScope) return;
    try {
      localStorage.setItem(`${SORT_KEY_STORAGE}:${prefScope}`, sortKey);
    } catch {
      /* ditto */
    }
  }, [sortKey, prefScope]);

  useEffect(() => {
    if (!prefScope) return;
    try {
      localStorage.setItem(`${SORT_DIR_STORAGE}:${prefScope}`, sortDir);
    } catch {
      /* ditto */
    }
  }, [sortDir, prefScope]);

  useEffect(() => {
    api<Tag[]>("/inventory/tags").then(setTagOptions).catch(() => setTagOptions([]));
  }, []);

  // Starred categories (owner spec 2026-10-24; row model
  // 2026-10-25): the owner's ≤5 shortcut links riding the
  // view row after All, in Categories-page order
  // (the four preinstalled starters first). They drive the
  // SAME category filter as the Filters panel — one source of
  // truth. Refetched on the page refresh tick, like the list
  // itself. The row never scrolls and never wraps (owner spec
  // 2026-10-25): the cap is 5, and should an account somehow
  // hold more starred than that, only the first 5 in list
  // order render — the rest stay starred, just not linked.
  const [starredCategories, setStarredCategories] = useState<CategoryRow[]>([]);
  // The full category count rides the same read — it is one of
  // the header's standing facts (null until the read lands, and
  // after a failed one: the fact simply never renders).
  const [categoryCount, setCategoryCount] = useState<number | null>(null);
  useEffect(() => {
    api<CategoryRow[]>("/inventory/categories")
      .then((rows) => {
        setCategoryCount(rows.length);
        setStarredCategories(rows.filter((row) => row.starred).slice(0, 5));
      })
      .catch(() => setStarredCategories([]));
  }, [refreshTick]);

  // The header's vault stats (owner order 2026-11-10): the
  // /inventory/stats read — the same whole-vault totals Home
  // and Reports print (active assets only, the billing
  // contract; total_value on the purchase-cost basis),
  // refetched on the refresh tick like the categories read.
  // Null until the read lands; a failed read simply leaves
  // the stat facts unrendered, never a placeholder.
  const [vaultStats, setVaultStats] = useState<InventoryStats | null>(null);
  useEffect(() => {
    api<InventoryStats>("/inventory/stats")
      .then(setVaultStats)
      .catch(() => undefined);
  }, [refreshTick]);

  function changeView(id: string) {
    // Clicking All clears the category filter (owner spec
    // 2026-10-24): the starred links filter this list, and All
    // is the reset. All is the only tab now (the Sold view
    // moved to My Listings, 2026-10-25).
    if (id === "all") set("category", "");
  }

  const [assets, setAssets] = useState<AssetSearchItem[] | null>(null);
  const [error, setError] = useState("");
  // Server paging (step-4 fix D2): the active view's full match
  // count (X-Total-Count) + the Load-more machinery. Lists hold
  // every page loaded so far, in server order.
  const [total, setTotal] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // QR label printing (blueprint §18): "Select for labels" mode
  // grows a checkbox on every card; the selection is a set of
  // `kind:id` refs that survives view switches and rides to the
  // print page in the URL.
  const [selecting, setSelecting] = useState(false);
  const [selectedRefs, setSelectedRefs] = useState<Set<string>>(new Set());

  // Bulk edit mode (Package B): its OWN selection, separate from
  // the label selection — the two modes never run at once.
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkSelected, setBulkSelected] = useState<Set<string>>(new Set());
  const [bulkModal, setBulkModal] = useState<BulkModalKind>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  // Select-all (owner, 2026-10-25): the refs of the WHOLE current
  // view once collected by paging the list endpoint, keyed by the
  // view's page-0 query — a filter/search/location change makes
  // the key stale and the scope stops speaking for the view.
  const [bulkScope, setBulkScope] = useState<{
    key: string;
    refs: Set<string>;
  } | null>(null);
  const [bulkCollecting, setBulkCollecting] = useState(false);

  // For-sale poster mode (audit A5): a THIRD selection, mirroring
  // the label selection's shape — its own set, never concurrent
  // with the other two modes. Picks ride to POST /sales/poster,
  // which already accepts a list (one PDF page per item).
  const [posterMode, setPosterMode] = useState(false);
  const [posterSelected, setPosterSelected] = useState<Set<string>>(new Set());
  const [posterBusy, setPosterBusy] = useState(false);

  function toggleRefIn(setter: React.Dispatch<React.SetStateAction<Set<string>>>, ref: string) {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
  }

  function cardSelection(kind: "tool" | "battery", id: string) {
    if (posterMode) {
      const ref = `${kind}:${id}`;
      return {
        selected: posterSelected.has(ref),
        onToggle: () => toggleRefIn(setPosterSelected, ref),
        label: "Select for poster",
      };
    }
    if (bulkMode) {
      const ref = `${kind}:${id}`;
      return {
        selected: bulkSelected.has(ref),
        onToggle: () => toggleRefIn(setBulkSelected, ref),
        label: "Select for bulk edit",
      };
    }
    if (!selecting) return undefined;
    const ref = `${kind}:${id}`;
    return {
      selected: selectedRefs.has(ref),
      onToggle: () => toggleRefIn(setSelectedRefs, ref),
    };
  }

  // Borrowing standing per item (module doctrine): the lending
  // chip + Check out quick action on each card. Best-effort like
  // the detail-page panel — when the borrowing module isn't
  // effective for this user the read fails and the cards simply
  // render without the footer; inventory never depends on it.
  const { toast } = useToast();
  const { has, modules: effectiveModules } = useMyModules();
  const [lendMap, setLendMap] = useState<Map<string, Checkout> | null>(null);
  const [checkoutTarget, setCheckoutTarget] = useState<CheckoutTarget | null>(null);
  // The row Actions menu's Delete entry lands here: the
  // list page runs the item page's own confirm + DELETE, then
  // reloads in place (the detail page navigates away instead).
  const [deleteTarget, setDeleteTarget] = useState<{
    kind: "tool" | "battery";
    id: string;
    name: string;
    isSet: boolean;
  } | null>(null);
  const [deleting, setDeleting] = useState(false);

  function loadLending() {
    getBorrowingOverview()
      .then((overview) => {
        const map = new Map<string, Checkout>();
        for (const row of [...overview.requests_for_me, ...overview.lent_out]) {
          map.set(`${row.item_kind}:${row.item_id}`, row);
        }
        setLendMap(map);
      })
      .catch(() => setLendMap(null));
  }

  useEffect(loadLending, []);

  // Tool Expansion cart badges (owner spec 2026-10-25): the
  // per-item live suggestion counts, read once per list load.
  // Best-effort exactly like lending — module not effective
  // (403) or read failed → no badges, inventory never depends
  // on it. Counts are the LIVE counts (dismissals and killed
  // matches already applied server-side).
  const [expansionCounts, setExpansionCounts] = useState<Record<
    string,
    number
  > | null>(null);

  useEffect(() => {
    getExpansionCounts()
      .then((result) => setExpansionCounts(result.counts))
      .catch(() => setExpansionCounts(null));
  }, []);

  function expansionBadge(kind: "tool" | "battery", id: string) {
    const count = expansionCounts?.[`${kind}:${id}`] ?? 0;
    if (count <= 0) return undefined;
    return <ExpansionBadge kind={kind} id={id} count={count} />;
  }

  function cardLending(kind: "tool" | "battery", id: string): RowLending | null {
    const row = lendMap?.get(`${kind}:${id}`);
    if (!row) return null;
    // Sweep B2-F6: the list pill carries the borrower — the whole
    // point of the pill — in the short form ("Checked out to …",
    // no due-date suffix; the item page's strip keeps the full
    // sentence). The pill wraps inside its cell instead of
    // ellipsizing the name away, and the full standing text rides
    // as its hover title. Overdue still says so.
    const chip =
      row.state === "requested"
        ? `Requested by ${row.borrower_name}`
        : `Checked out to ${row.borrower_name}${row.overdue ? " · overdue" : ""}`;
    return {
      chip,
      title: standingText(row),
      tone: row.overdue ? "danger" : row.state === "requested" ? "warning" : "accent",
    };
  }

  function canCheckout(kind: "tool" | "battery", item: { id: string; active?: boolean }) {
    return (
      lendMap !== null &&
      !lendMap.has(`${kind}:${item.id}`) &&
      item.active !== false
    );
  }

  const debouncedQuery = useDebounced(query, 350);
  const debouncedFilters = useDebounced(filters, 350);
  const debouncedPlatform = useDebounced(platform, 350);

  const PAGE_SIZE = 100;

  /** Read the smart-search chips off a search response. */
  function readChips(headers: Headers) {
    const raw = headers.get("X-Search-Chips");
    if (!raw) {
      setSearchChips([]);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as { kind: string; label: string }[];
      setSearchChips(Array.isArray(parsed) ? parsed : []);
    } catch {
      setSearchChips([]);
    }
  }

  /** The list view's request path for one page. Every filter —
   *  including the category/price filters, which the server
   *  judges on the extended total — rides the query, and the
   *  sort key goes with it (server-side order, D2). The retired
   *  kind views' own filters (platform, replacement range)
   *  ride too: each narrows its own kind inside the merged
   *  stream server-side (owner spec 2026-10-25). */
  function pagePath(offset: number): string {
    const params = new URLSearchParams();
    if (tagId) params.set("tag_id", tagId);
    if (debouncedQuery.trim()) {
      params.set("q", debouncedQuery.trim());
      params.set("smart", "true");
    }
    if (locationParam) params.set("location", locationParam);
    if (locationIdParam) params.set("location_id", locationIdParam);
    params.set("sort", sortKey);
    params.set("sort_dir", sortDir);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    if (warranty) params.set("warranty", warranty);
    if (debouncedFilters.category.trim()) params.set("category", debouncedFilters.category.trim());
    if (debouncedFilters.minPrice) params.set("min_price", debouncedFilters.minPrice);
    if (debouncedFilters.maxPrice) params.set("max_price", debouncedFilters.maxPrice);
    if (debouncedFilters.minReplacement) params.set("min_replacement", debouncedFilters.minReplacement);
    if (debouncedFilters.maxReplacement) params.set("max_replacement", debouncedFilters.maxReplacement);
    if (debouncedFilters.dealer) params.set("dealer_id", debouncedFilters.dealer);
    if (debouncedPlatform.trim()) params.set("platform", debouncedPlatform.trim());
    return `/inventory/search/all?${params.toString()}`;
  }

  useEffect(() => {
    let cancelled = false;
    const fail = (err: unknown, what: string) => {
      if (cancelled) return;
      setError(
        err instanceof ApiError ? err.message : `Couldn't load your ${what}.`,
      );
    };
    setTotal(null);
    apiPage<AssetSearchItem[]>(pagePath(0))
      .then(({ data, total: count, headers }) => {
        if (!cancelled) {
          readChips(headers);
          setAssets(data);
          setTotal(count);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) setAssets([]);
        fail(err, "inventory");
      });
    return () => {
      cancelled = true;
    };
    // pagePath reads the debounced inputs + sortKey captured above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery, debouncedFilters, debouncedPlatform, warranty, tagId, locationParam, locationIdParam, sortKey, sortDir, refreshTick]);

  const loadedCount = (assets ?? []).length;
  const hasMore = total !== null && loadedCount < total;

  /** Append the next page (offset = what's loaded). The result is
   *  dropped if the view/filters changed underneath it — the
   *  captured path no longer matches the screen. */
  function loadMore() {
    if (loadingMore || !hasMore) return;
    const path = pagePath(loadedCount);
    setLoadingMore(true);
    apiPage<AssetSearchItem[]>(path)
      .then(({ data }) => {
        setAssets((prev) => (prev === null ? data : [...prev, ...data]));
      })
      .catch(() => {
        /* the loaded pages stay; the button can be retried */
      })
      .finally(() => setLoadingMore(false));
  }

  // The list arrives in server order now (D2) — no client sort.
  const displayAssets = assets;

  const filtering =
    query.trim() !== "" ||
    Object.values(filters).some((v) => v !== "") ||
    platform.trim() !== "" ||
    warranty !== "" ||
    tagId !== "" ||
    locationParam !== "" ||
    locationIdParam !== "";

  function clearAll() {
    setQuery("");
    setFilters(EMPTY_FILTERS);
    setPlatform("");
    setWarranty("");
    setTagId("");
    if (locationParam || locationIdParam) {
      const params = new URLSearchParams(searchParams);
      params.delete("location");
      params.delete("location_id");
      setSearchParams(params, { replace: true });
    }
  }

  function setTreeLocation(locationId: string | null) {
    const params = new URLSearchParams(searchParams);
    if (locationId) params.set("location_id", locationId);
    else params.delete("location_id");
    setSearchParams(params, { replace: true });
  }

  // -- Location / Sub Location cascade (owner spec 2026-10-24) --
  // The URL still carries ONE location_id: the deepest node the
  // user picked, and the server filters by its whole subtree,
  // exactly as the retired tree picker drove it. The two
  // dropdowns are two windows onto that one param — Location
  // shows the picked chain's tier-1 node, Sub Location its
  // tier-2 node — and picking in either rewrites the param to
  // that level. A deeper pick (an old link whose location_id is
  // a tier-3 node) keeps filtering by its full subtree while the
  // dropdowns reflect the closest representable state: its
  // tier-1 + tier-2 ancestors.
  useEffect(() => {
    let cancelled = false;
    listLocationNodes()
      .then((rows) => {
        if (cancelled) return;
        setLocationNodes(rows);
        setLocationTreeOk(true);
        setLocationNodesLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        // A failed load leaves both dropdowns on "All" (nothing
        // else to offer) without touching the URL filter — the
        // page itself, and the filter's info bar, keep working.
        setLocationTreeOk(false);
        setLocationNodesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick, locationTick]);

  const locationTree = useMemo(
    () => buildLocationTree(locationNodes),
    [locationNodes],
  );
  const selectedChain = useMemo(() => {
    if (!locationIdParam) return [] as LocationNode[];
    const byId = new Map(locationNodes.map((n) => [n.id, n]));
    const chain: LocationNode[] = [];
    const seen = new Set<string>();
    let current = byId.get(locationIdParam);
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      chain.unshift(current);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return chain;
  }, [locationNodes, locationIdParam]);
  const selectedLocation = selectedChain[0] ?? null;
  const selectedSubLocation =
    selectedChain.length > 1 ? selectedChain[1] : null;
  const subLocationOptions = useMemo(() => {
    if (!selectedLocation) return [] as LocationNode[];
    const root = locationTree.find((n) => n.id === selectedLocation.id);
    return (root?.children ?? []) as LocationNode[];
  }, [locationTree, selectedLocation]);

  // A stale location_id (node deleted in another tab, a
  // hand-typed link) falls back to All instead of filtering the
  // page into a void — but only once the tree has actually
  // loaded; a failed load never clears a filter it can't judge.
  useEffect(() => {
    if (!locationTreeOk || !locationIdParam) return;
    if (!locationNodes.some((n) => n.id === locationIdParam)) {
      setTreeLocation(null);
    }
    // setTreeLocation reads the live searchParams each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locationTreeOk, locationNodes, locationIdParam]);

  function pickLocation(locationId: string) {
    // Picking a Location replaces the whole cascade: the param
    // becomes that node (Sub Location falls back to All, since
    // the new chain has no tier-2 pick).
    setTreeLocation(locationId || null);
  }

  function pickSubLocation(subId: string) {
    if (!selectedLocation) return;
    // "All" under a chosen Location = the Location's whole
    // subtree; a sub pick narrows the param to that node (whose
    // own subtree — tier-3 and deeper — rides along inside it).
    setTreeLocation(subId || selectedLocation.id);
  }

  // The three select/print modes are mutually exclusive, exactly
  // as the old toolbar buttons kept them; the Actions menu item
  // flips its mode (the shared menu closes itself first).
  function toggleSelecting() {
    setSelecting((v) => !v);
    setBulkMode(false);
    setPosterMode(false);
  }
  function toggleBulkMode() {
    setBulkMode((v) => !v);
    setSelecting(false);
    setPosterMode(false);
  }
  // Cancel (owner, 2026-10-25): the plain way OUT of bulk mode —
  // the menu toggle was undiscoverable. Leaves bulk mode and
  // drops the selection; nothing is applied.
  function cancelBulkEdit() {
    setBulkMode(false);
    setBulkSelected(new Set());
    setBulkScope(null);
    setBulkModal(null);
  }
  function togglePosterMode() {
    setPosterMode((v) => !v);
    setSelecting(false);
    setBulkMode(false);
  }

  // Refs of everything currently on screen — with server paging
  // (D2) that means every page LOADED SO FAR in the list:
  // "Select all visible" selects the loaded rows, and the count
  // line always shows how much of the vault is loaded. Selections
  // themselves are plain id sets, so picks made on earlier pages
  // stay selected while more pages load.
  const visibleRefs: string[] = (displayAssets ?? []).map(
    (a) => `${a.item_kind}:${a.id}`,
  );
  const allVisibleSelected =
    visibleRefs.length > 0 && visibleRefs.every((ref) => selectedRefs.has(ref));

  function selectAllVisible() {
    setSelectedRefs((prev) => new Set([...prev, ...visibleRefs]));
  }

  const allVisiblePosterSelected =
    visibleRefs.length > 0 &&
    visibleRefs.every((ref) => posterSelected.has(ref));

  function selectAllVisibleForPoster() {
    setPosterSelected((prev) => new Set([...prev, ...visibleRefs]));
  }

  /* -- bulk select-all (owner, 2026-10-25) -------------------------
   * The header checkbox speaks for the CURRENT VIEW: everything
   * matching the active search/filters/category/location across
   * ALL pages — not just the loaded rows, and never anything
   * outside the view. Collection pages the same list endpoint the
   * screen itself reads (pagePath), so "the view" is the server's
   * own definition of it. Until a collection exists for this view,
   * the checkbox judges by the loaded rows only. */
  const bulkViewKey = pagePath(0);
  const bulkScopeRefs =
    bulkScope && bulkScope.key === bulkViewKey ? bulkScope.refs : null;
  const bulkKnownRefs = bulkScopeRefs ?? new Set(visibleRefs);
  const bulkSelectedInView = [...bulkKnownRefs].filter((ref) =>
    bulkSelected.has(ref),
  ).length;
  const bulkAllViewSelected =
    bulkKnownRefs.size > 0 && bulkSelectedInView === bulkKnownRefs.size;
  const bulkSomeViewSelected =
    bulkSelectedInView > 0 && !bulkAllViewSelected;

  async function selectAllMatching() {
    if (bulkCollecting) return;
    setBulkCollecting(true);
    try {
      const refs = new Set<string>();
      let offset = 0;
      let matchTotal = Number.POSITIVE_INFINITY;
      while (offset < matchTotal) {
        const { data, total: count } = await apiPage<AssetSearchItem[]>(
          pagePath(offset),
        );
        if (count !== null) matchTotal = count;
        for (const a of data) refs.add(`${a.item_kind}:${a.id}`);
        if (data.length === 0) break;
        offset += data.length;
      }
      setBulkSelected((prev) => new Set([...prev, ...refs]));
      setBulkScope({ key: bulkViewKey, refs });
    } catch {
      toast("Couldn't select everything in this view — try again.", {
        tone: "danger",
        title: "Bulk edit",
      });
    } finally {
      setBulkCollecting(false);
    }
  }

  function onBulkSelectAllToggle(checked: boolean) {
    if (checked) {
      void selectAllMatching();
    } else {
      // Unchecking empties the selection — the same outcome as
      // the sticky bar's Clear selection.
      setBulkSelected(new Set());
      setBulkScope(null);
    }
  }

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  const currentItems: { active?: boolean }[] | null = assets;
  const anyInactive =
    currentItems !== null && currentItems.some((t) => t.active === false);

  /* -- for-sale poster (audit A5) ------------------------------- */

  async function buildPoster() {
    const picks = [...posterSelected].map((ref) => {
      const [kind, id] = ref.split(":");
      return {
        item_kind: kind as "tool" | "battery",
        item_id: id,
        // The bulk run carries no per-item price: the poster prints
        // "Make offer" (the renderer's standing rule for a null
        // price) and the QR points at the seller's public profile —
        // exactly the single-item rules with no listing attached.
        price: null,
        listing_url: "",
      };
    });
    setPosterBusy(true);
    try {
      // POST + binary body: the single-item poster's shape (raw
      // fetch with the stored token — api() is JSON-only).
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch("/api/inventory/sales/poster", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ items: picks }),
      });
      if (!response.ok) {
        throw new Error(`Poster failed (${response.status}).`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "for-sale-poster.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast(
        `Poster PDF built for ${picks.length} item${picks.length === 1 ? "" : "s"}.`,
        { tone: "success", title: "For-sale poster" },
      );
      setPosterSelected(new Set());
      setPosterMode(false);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't build the poster.", {
        tone: "danger",
        title: "For-sale poster",
      });
    } finally {
      setPosterBusy(false);
    }
  }

  /* -- bulk edit ------------------------------------------------ */

  function bulkRefs(): { kind: "tool" | "battery"; id: string }[] {
    return [...bulkSelected].map((ref) => {
      const [kind, id] = ref.split(":");
      return { kind: kind as "tool" | "battery", id };
    });
  }

  /** Name + set facts for the share modal, from the loaded list
   *  (one stream over both kinds now: a set picked simply
   *  defaults to "core pieces only" when its rows aren't loaded). */
  const bulkItemLookup = useMemo(() => {
    const map = new Map<string, { name: string; isSet: boolean }>();
    for (const a of assets ?? []) {
      map.set(`${a.item_kind}:${a.id}`, {
        name: a.name,
        isSet: a.item_kind === "tool" ? a.is_set : false,
      });
    }
    return map;
  }, [assets]);

  async function runBulk(
    action: string,
    params: Record<string, unknown>,
    verb = "updated",
  ) {
    setBulkBusy(true);
    // POST /inventory/bulk takes at most 500 items per call
    // (BulkRequest.max_length), so a select-all-sized run rides
    // in sequential chunks of 500 and the affected counts add up.
    // A chunk that fails stops the run: the toast says how much
    // landed before it stopped, and the selection stays put.
    const refs = bulkRefs();
    const CHUNK = 500;
    let affected = 0;
    let failure: unknown = null;
    for (let i = 0; i < refs.length; i += CHUNK) {
      try {
        const result = await api<BulkResult>("/inventory/bulk", {
          method: "POST",
          body: JSON.stringify({
            items: refs.slice(i, i + CHUNK),
            action,
            params,
          }),
        });
        affected += result.affected;
      } catch (err) {
        failure = err;
        break;
      }
    }
    setBulkBusy(false);
    if (failure) {
      // A 422's detail copy is friendly and specific — verbatim.
      const message =
        failure instanceof ApiError
          ? failure.message
          : "That bulk edit didn't work.";
      toast(
        affected > 0
          ? `${affected} item${affected === 1 ? "" : "s"} ${verb}, then it stopped: ${message}`
          : message,
        { tone: "danger", title: "Bulk edit" },
      );
      if (affected > 0) setRefreshTick((t) => t + 1);
      return;
    }
    toast(
      `${affected} item${affected === 1 ? "" : "s"} ${verb}.`,
      { tone: "success", title: "Bulk edit" },
    );
    setBulkSelected(new Set());
    setBulkScope(null);
    setBulkModal(null);
    setRefreshTick((t) => t + 1);
    loadLending();
  }

  const pager = hasMore ? (
    <div style={{ display: "flex", justifyContent: "center", marginTop: "1rem" }}>
      <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
        {loadingMore
          ? "Loading…"
          : `Load more (${(total ?? 0) - loadedCount} remaining)`}
      </Button>
    </div>
  ) : null;

  function loadingBlock() {
    // F1-01: a skeleton at the list's real geometry instead of
    // a lone spinner — the page frame is already painted
    // (header, toolbar), and the list swaps in whole.
    return <InventorySkeleton />;
  }

  function checkoutFor<T extends { id: string; name: string; active?: boolean }>(
    kind: "tool" | "battery",
    item: T,
    extra?: { isSet?: boolean },
  ) {
    return canCheckout(kind, item)
      ? () =>
          setCheckoutTarget({
            kind,
            id: item.id,
            name: item.name,
            isSet: extra?.isSet,
          })
      : undefined;
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(
        deleteTarget.kind === "tool"
          ? `/inventory/${deleteTarget.id}`
          : `/inventory/batteries/${deleteTarget.id}`,
        { method: "DELETE" },
      );
      setDeleteTarget(null);
      setRefreshTick((n) => n + 1);
      loadLending();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't delete it.", {
        tone: "danger",
      });
    } finally {
      setDeleting(false);
    }
  }

  /** The item's Actions menu for a list row (owner,
   *  2026-11-05): the item page's ItemActionsMenu itself — same
   *  entries, same state rules — with this page's wiring. The
   *  checkout state rides the lending read the cards already
   *  use; the loss-report state isn't read on this page, so the
   *  menu offers "Mark lost / stolen" and the item page's own
   *  window (where the entry lands) shows the open report when
   *  one exists. Entries that live in item-page windows jump
   *  there through the page's own deep links (#borrowing,
   *  #start-claim, #loss-report, #sale). */
  function itemActions(kind: "tool" | "battery", item: AssetSearchItem) {
    const path =
      kind === "tool" ? `/inventory/${item.id}` : `/inventory/batteries/${item.id}`;
    const checkout = lendMap?.get(`${kind}:${item.id}`) ?? null;
    const status: ItemStatusData = { lossReport: null, checkout, claims: null };
    const isSet = kind === "tool" ? (item as Tool).is_set : undefined;
    return (
      <ItemActionsMenu
        size="sm"
        itemKind={kind}
        item={item}
        status={status}
        hasModule={has}
        onJump={() => {
          // Lend / check out with no open loan keeps the row's
          // old quick action — the checkout modal, right here.
          // An open loan's entries (request / return) land on
          // the item's Borrowing tab, where the loan lives.
          if (!checkout) {
            const open = checkoutFor(kind, item, { isSet });
            if (open) {
              open();
              return;
            }
          }
          navigate(`${path}#borrowing`);
        }}
        onChanged={() => {
          setRefreshTick((n) => n + 1);
          loadLending();
        }}
        onDelete={() =>
          setDeleteTarget({
            kind,
            id: item.id,
            name: item.name,
            isSet: isSet === true,
          })
        }
        onStartClaim={() => navigate(`${path}#start-claim`)}
        onOpenLoss={() => navigate(`${path}#loss-report`)}
        onOpenSale={() => navigate(`${path}#sale`)}
      />
    );
  }

  // One row for one item — shared by the plain render and the
  // dealer-grouped render below so the two can never drift
  // apart.
  const renderAssetRow = (item: AssetSearchItem) =>
    item.item_kind === "battery" ? (
      <AssetRow
        key={`b-${item.id}`}
        kind="battery"
        item={item}
        onOpen={() => navigate(`/inventory/batteries/${item.id}`)}
        selection={cardSelection("battery", item.id)}
        lending={cardLending("battery", item.id)}
        actions={itemActions("battery", item)}
        badge={expansionBadge("battery", item.id)}
      />
    ) : (
      <AssetRow
        key={`t-${item.id}`}
        kind="tool"
        item={item}
        onOpen={() => navigate(`/inventory/${item.id}`)}
        selection={cardSelection("tool", item.id)}
        lending={cardLending("tool", item.id)}
        actions={itemActions("tool", item)}
        badge={expansionBadge("tool", item.id)}
      />
    );

  // Dealer sort renders GROUPED (owner, 2026-10-25): a header row
  // per dealer — name + that dealer's item count — then the
  // dealer's items, in the server's dealer order (either
  // direction). Items with no dealer group LAST under "No dealer"
  // in both directions. Counts cover the loaded rows, the same
  // loaded-set framing the count line above the list uses.
  interface DealerGroup {
    id: string | null;
    name: string;
    items: AssetSearchItem[];
  }
  function groupAssetsByDealer(items: AssetSearchItem[]): DealerGroup[] {
    const groups: DealerGroup[] = [];
    const byId = new Map<string, DealerGroup>();
    let none: DealerGroup | null = null;
    for (const item of items) {
      if (!item.dealer_company_id) {
        if (!none) none = { id: null, name: t("inventory.noDealer"), items: [] };
        none.items.push(item);
        continue;
      }
      let group = byId.get(item.dealer_company_id);
      if (!group) {
        group = {
          id: item.dealer_company_id,
          name: item.dealer_company_name ?? "",
          items: [],
        };
        byId.set(item.dealer_company_id, group);
        groups.push(group);
      }
      group.items.push(item);
    }
    return none ? [...groups, none] : groups;
  }
  const dealerGroupHead = (group: DealerGroup) => (
    <div key={`dg-${group.id ?? "none"}`} className="tv-inv-group-head">
      <strong>{group.name}</strong>
      <span>
        {group.items.length}{" "}
        {group.items.length === 1
          ? t("inventory.nounItemOne")
          : t("inventory.nounItemMany")}
      </span>
    </div>
  );
  const dealerGrouped = sortKey === "dealer" && displayAssets !== null;

  // Any of the three mutually exclusive selection modes arms the
  // list rows with checkboxes — the table grows its select
  // column (header + rows share the wider template).
  const anySelecting = selecting || bulkMode || posterMode;

  /* The list panel's "Showing X of Y items" row (owner rebuild,
   * 2026-11-03): the count at the left, and the row's right side
   * carries the sort dropdown with the sort-direction arrow
   * immediately beside (left of) it. The arrow is glyph-only;
   * its words ride the aria-label/title. These controls moved
   * here off the toolbar, whose bar keeps only Filters,
   * Location, Sub Location and Search. The
   * List | Tiles toggle that also rode this row is GONE (owner,
   * 2026-11-05 — the inventory is a list, only a list). The row
   * renders in the empty state too, so the sort controls (and
   * Clear, while filtering) never vanish with a zero-result
   * filter. */
  const showingRow = displayAssets === null ? null : (
    <div className="tv-inv-showing-row">
      <p className="tv-inv-showing-count">
        {t("inventory.showing")} {displayAssets.length} {t("inventory.of")} {total ?? displayAssets.length}{" "}
        {(total ?? displayAssets.length) === 1 ? t("inventory.nounItemOne") : t("inventory.nounItemMany")}
      </p>
      {/* Clear search & filters rides beside the count (owner
          spec 2026-10-25: it lives on this row, so the list
          never jumps when it appears or vanishes). Absent
          entirely when nothing is filtering. */}
      {filtering && (
        <Button variant="secondary" size="sm" onClick={clearAll}>
          Clear search & filters
        </Button>
      )}
      <div className="tv-inv-showing-controls">
        <Button
          size="sm"
          variant="secondary"
          className="tv-inv-dirbtn"
          aria-label={t("inventory.sort.reverse")}
          title={t("inventory.sort.reverse")}
          onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
        >
          {sortDir === "asc" ? "▲" : "▼"}
        </Button>
        <div className="tv-inv-sort">
          <Select
            id="inv-sort"
            aria-label={t("inventory.sort")}
            value={sortKey}
            onChange={(e) => {
              const next = e.target.value as SortKey;
              setSortKey(next);
              setSortDir(sortConvention(next));
            }}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.value === "featured" ? t("inventory.sort.featured") : t(`inventory.sortLabel.${o.value}` as never)}
              </option>
            ))}
          </Select>
        </div>
      </div>
    </div>
  );

  const allContent =
    displayAssets === null ? (
      loadingBlock()
    ) : displayAssets.length === 0 ? (
      <>
        {showingRow}
        <EmptyState
          icon={<BrandIcon name={filtering ? "search" : "briefcase"} size={52} />}
          title={filtering ? "Nothing matches" : "Nothing in your vault yet"}
          description={
            filtering
              ? "Try a different search or clear the filters."
              : "Add a tool or a battery to start building your vault."
          }
          action={
            !filtering ? (
              <LinkButton to="/inventory/new">Add your first tool</LinkButton>
            ) : undefined
          }
        />
      </>
    ) : (
      <>
        {showingRow}
        {/* The true list (list standard, 2026-11-02) — the ONLY
           rendering since the tiles view was removed (owner,
           2026-11-05): ONE table — header row, then one row per
           record; dealer-grouped sort keeps its spanning group
           heads between the column rows of each group. */}
        <div
          className={`tv-inv-list tv-inv-table${anySelecting ? " tv-inv-table--selecting" : ""}`}
          role="table"
        >
          <InventoryListHead selecting={anySelecting} />
          {dealerGrouped
            ? groupAssetsByDealer(displayAssets).map((group) => (
                <Fragment key={`dgwrap-${group.id ?? "none"}`}>
                  {dealerGroupHead(group)}
                  {group.items.map(renderAssetRow)}
                </Fragment>
              ))
            : displayAssets.map(renderAssetRow)}
        </div>
        {pager}
      </>
    );

  // The header Actions menu's command entries (main tab
  // layout, 2026-11-10): the retired ☰ hamburger's commands in
  // their settled order. The select-mode toggles keep their
  // state-swapping labels — the modes' state itself rides the
  // selection bars above the list, as it always has.
  const invActionEntries: SettingsActionEntry[] = [
    // No "Add battery" entry (owner order, 2026-11-12): adding
    // a battery rides the Add wizard's own first question —
    // the ADD TOOL button opens the wizard, whose fork asks
    // "Is it a battery?" and takes the battery branch from
    // there. The menu's old deep link into the pre-answered
    // branch was a second door to the same room.
    {
      key: "select-labels",
      label: selecting
        ? t("inventory.doneSelectingLabels")
        : t("inventory.selectLabels"),
      run: toggleSelecting,
    },
    {
      key: "select-poster",
      label: posterMode
        ? t("inventory.doneSelectingPoster")
        : t("inventory.selectPoster"),
      run: togglePosterMode,
    },
    {
      key: "bulk-edit",
      label: bulkMode ? "Done bulk editing" : t("inventory.bulkEdit"),
      run: toggleBulkMode,
    },
    {
      key: "import",
      label: t("inventory.import"),
      run: () => navigate("/inventory/import"),
    },
    {
      key: "health-check",
      label: t("inventory.healthCheck"),
      run: () => navigate("/inventory/health"),
    },
    {
      key: "edit-tags",
      label: t("inventory.editTags"),
      run: () => navigate("/inventory/categories?section=tags"),
    },
    {
      key: "edit-locations",
      label: t("inventory.editLocations"),
      run: () => setLocationManagerOpen(true),
    },
    {
      key: "edit-categories",
      label: t("inventory.editCategories"),
      run: () => navigate("/inventory/categories?section=categories"),
    },
  ];

  // The Actions menu's Settings group (Actions → Settings,
  // owner order 2026-11-09): the four Settings sections this
  // page owns — sharing, custom-fields, wizard-defaults
  // (site) and import-matching (account) — in the Settings
  // page's own tab order, gated by the very predicate the
  // Settings shell gates with, so the menu never offers a
  // section the shell would bounce. Each entry lands on its
  // section route (the conformance map's standard form).
  // Custom fields used to ride the command list above as a
  // one-off settings link (at the old #custom-fields hash);
  // it lives in this group now, at the standard route.
  const moduleIds: ReadonlySet<string> = new Set(
    (effectiveModules ?? []).map((m) => m.id),
  );
  const bareRung = user ? groupLayerWaived(user) : false;
  const invSettingsEntries: SettingsActionEntry[] = (
    ["site", "account"] as const
  )
    .flatMap((g) =>
      SETTINGS_SECTIONS.filter(
        (s) =>
          s.group === g &&
          INVENTORY_SETTING_IDS.includes(s.id) &&
          sectionVisibleFor(s, user?.account_types ?? [], moduleIds, bareRung),
      ),
    )
    .map((s) => ({
      key: s.id,
      label: t(`settings.section.${s.id}` as never),
      run: () => navigate(`/settings/${s.id}`),
    }));

  // The header's standing facts — none of them move with the
  // filters. First the vault stats (owner order 2026-11-10:
  // "that area should also have a few stats: total items,
  // total price for items, etc."): whole-vault totals from
  // /inventory/stats — the same numbers Home and Reports
  // print (active assets; Total value on the purchase-cost
  // basis). They are labelled as totals so they never read
  // as filter results; the FILTERED count stays the list's
  // own "Showing X of Y" row's fact, as it always has. Then
  // the page's furniture counts — its top-level locations
  // and its categories. Each fact appears only once its read
  // has landed — never a placeholder.
  const headerFacts: SectionPageFact[] = [];
  if (vaultStats !== null) {
    headerFacts.push(
      {
        label: t("panel.inventory.itemsTracked"),
        value: vaultStats.total_items.toLocaleString(activeLocale()),
      },
      {
        label: t("stat.inventory.total_market_value"),
        value: money(vaultStats.total_value),
      },
      {
        label: t("inventory.fact.quantity"),
        value: vaultStats.total_quantity.toLocaleString(activeLocale()),
      },
    );
  }
  if (locationNodesLoaded) {
    headerFacts.push({
      label: t("inventory.fact.locations"),
      value: locationTree.length,
    });
  }
  if (categoryCount !== null) {
    headerFacts.push({
      label: t("inventory.categories"),
      value: categoryCount,
    });
  }

  return (
    <RequireAuth>
      {/* W-05: the single column is minmax(0, 1fr) — a plain 1fr
       * track keeps min-width:auto, so wide min-content inside
       * (the toolbar/sort row) stretched the whole page 3px past
       * a 402px phone viewport. */}
      <div
        style={{
          display: "grid",
          gap: "var(--spacing)",
          gridTemplateColumns: "minmax(0, 1fr)",
        }}
      >
        {/* Main tab layout header (program lane 2, owner order
            2026-11-09): the shared SectionPageHeader — the
            inventory thumbnail, the title and the page's
            standing facts; at the top-right, the primary
            "Add tool" button (visible, never buried — the
            owner's 2026-10-24 correction, kept) beside the
            ONE Actions dropdown. The ☰ commands hamburger
            that headed the toolbar below is REMOVED: its
            commands are the Actions menu's entries now, and
            the menu's trailing Settings group carries the
            four Settings sections this page owns. The search +
            filter bar rides INSIDE this header panel (the
            toolbar slot below): the owner overruled its
            first seating in a panel under the header
            (2026-11-10, with his screenshot of the bar —
            "Put this area in the header bar with the action
            button"), and added the vault stats to the facts
            row the same morning. */}
        <SectionPageHeader
          thumb={<ArtIcon name="inventory" size={96} />}
          title={t("inventory.title")}
          facts={headerFacts}
          actions={
            <div className="tv-inv-head-actions">
              <LinkButton to="/inventory/new">
                {t("inventory.addTool")}
              </LinkButton>
              <SettingsActionsMenu
                ariaLabel={t("inventory.actions")}
                buttonLabel={t("inventory.actions")}
                entries={invActionEntries}
                settingsEntries={invSettingsEntries}
                settingsLabel={t("shell.settings")}
              />
            </div>
          }
          toolbar={
            <div
              className="tv-inv-toolbar"
              style={{ display: "grid", gap: "0.9rem" }}
            >
            {/* The header bar's search + filter row (owner
                orders 2026-11-09 + 2026-11-10: the searching
                and filtering live IN the header bar, inside
                the header panel with the Actions button — the
                separate panel this bar first rode in under
                the header is gone): ONE bar — Filters ·
                Location · Sub Location · search — with the
                Tags picker inside the Filters panel below and
                the sort down on the list panel's "Showing"
                row, as the 2026-11-03 rebuild settled them. */}
            <div className="tv-inv-toolbar-row">
              {/* Filters leads the bar (owner rebuild
                  2026-11-03; the hamburger it rode beside
                  retired with the main tab layout, 2026-11-10)
                  — the disclosure for the filter panel below,
                  Tags included. */}
              <Button
                variant="secondary"
                aria-expanded={filtersOpen}
                onClick={() => setFiltersOpen((v) => !v)}
                style={{ alignSelf: "flex-end" }}
              >
                {t("inventory.filters")} {filtersOpen ? "▴" : "▾"}
              </Button>
              {/* Location / Sub Location (owner spec 2026-10-24):
                  tier-1 places, then the chosen place's tier-2
                  children — every option carries its subtree
                  tool count, straight from the server. */}
              <div style={{ flex: "0 1 190px", minWidth: 0 }}>
                <FormField label={t("inventory.location")} htmlFor="inv-location">
                  <Select
                    id="inv-location"
                    value={selectedLocation?.id ?? ""}
                    disabled={!locationNodesLoaded}
                    onChange={(e) => pickLocation(e.target.value)}
                  >
                    <option value="">{t("inventory.allOption")}</option>
                    {locationTree.map((node) => (
                      <option key={node.id} value={node.id}>
                        {node.name} ({node.subtree_item_count})
                      </option>
                    ))}
                  </Select>
                </FormField>
              </div>
              <div style={{ flex: "0 1 190px", minWidth: 0 }}>
                <FormField label={t("inventory.subLocation")} htmlFor="inv-sublocation">
                  <Select
                    id="inv-sublocation"
                    value={selectedSubLocation?.id ?? ""}
                    disabled={!locationNodesLoaded}
                    onChange={(e) => pickSubLocation(e.target.value)}
                  >
                    <option value="">{t("inventory.allOption")}</option>
                    {subLocationOptions.map((node) => (
                      <option key={node.id} value={node.id}>
                        {node.name} ({node.subtree_item_count})
                      </option>
                    ))}
                  </Select>
                </FormField>
              </div>
              <div className="tv-inv-search" style={{ flex: "1 1 200px", minWidth: 0 }}>
                <FormField label={t("inventory.search")} htmlFor="inv-q">
                  <SearchBar
                    id="inv-q"
                    value={query}
                    onChange={setQuery}
                    placeholder="Name, brand, model, serial, notes…"
                    ariaLabel="Search inventory"
                  />
                </FormField>
              </div>
              {searchChips.length > 0 && (
                <div
                  style={{
                    flex: "1 1 100%",
                    display: "flex",
                    gap: "0.4rem",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    Searching for:
                  </span>
                  {searchChips.map((chip) => (
                    <Badge key={`${chip.kind}-${chip.label}`}>{chip.label}</Badge>
                  ))}
                </div>
              )}
            </div>

            {filtersOpen && (
              <div
                className="tv-filter-fields"
                style={{
                  display: "grid",
                  gap: "0.9rem",
                  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
                }}
              >
                <FormField label="Warranty" htmlFor="inv-awarr">
                  <Select
                    id="inv-awarr"
                    value={warranty}
                    onChange={(e) =>
                      setWarranty(e.target.value as "" | WarrantyStatus | "due")
                    }
                  >
                    {WARRANTY_OPTIONS.map((o) => (
                      <option key={o.label} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </Select>
                </FormField>
                {dealerOptions !== null && (
                  <FormField label={t("inventory.filter.dealer")} htmlFor="inv-dealer">
                    <Select
                      id="inv-dealer"
                      value={filters.dealer}
                      onChange={(e) => set("dealer", e.target.value)}
                    >
                      <option value="">{t("inventory.filter.allDealers")}</option>
                      {dealerOptions.map((company) => (
                        <option key={company.id} value={company.id}>
                          {company.name}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                )}
                <FormField label="Category" htmlFor="inv-acat">
                  <TextInput
                    id="inv-acat"
                    value={filters.category}
                    onChange={(e) => set("category", e.target.value)}
                  />
                </FormField>
                {/* The Tags picker lives INSIDE the Filters
                    panel now (owner rebuild 2026-11-03) — same
                    tags, same behavior, off the top bar. */}
                {tagOptions.length > 0 && (
                  <FormField label="Tag" htmlFor="inv-tag">
                    <Select id="inv-tag" value={tagId} onChange={(e) => setTagId(e.target.value)}>
                      <option value="">All tags</option>
                      {tagOptions.map((tag) => (
                        <option key={tag.id} value={tag.id}>
                          {tag.name}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                )}
                <FormField label="Platform" htmlFor="inv-plat">
                  <TextInput
                    id="inv-plat"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                    placeholder="M18, 20V MAX…"
                  />
                </FormField>
                <FormField label="Min price (total)" htmlFor="inv-aminp">
                  <TextInput
                    id="inv-aminp"
                    type="number"
                    min="0"
                    step="any"
                    value={filters.minPrice}
                    onChange={(e) => set("minPrice", e.target.value)}
                  />
                </FormField>
                <FormField label="Max price (total)" htmlFor="inv-amaxp">
                  <TextInput
                    id="inv-amaxp"
                    type="number"
                    min="0"
                    step="any"
                    value={filters.maxPrice}
                    onChange={(e) => set("maxPrice", e.target.value)}
                  />
                </FormField>
                <FormField label="Min replacement" htmlFor="inv-minr">
                  <TextInput
                    id="inv-minr"
                    type="number"
                    min="0"
                    step="any"
                    value={filters.minReplacement}
                    onChange={(e) => set("minReplacement", e.target.value)}
                  />
                </FormField>
                <FormField label="Max replacement" htmlFor="inv-maxr">
                  <TextInput
                    id="inv-maxr"
                    type="number"
                    min="0"
                    step="any"
                    value={filters.maxReplacement}
                    onChange={(e) => set("maxReplacement", e.target.value)}
                  />
                </FormField>
              </div>
            )}
            </div>
          }
        />

        {error && <Alert tone="danger">{error}</Alert>}

        {anyInactive && (
          <Alert tone="warning">
            Some of your items are over your plan's item limit and are
            marked <strong>Inactive</strong> — they're greyed out below,
            hidden from sharing and stats, and safe in your vault.
            Upgrading your plan (Settings → Plan &amp; billing)
            reactivates all of them.
          </Alert>
        )}

        {locationParam && (
          <Alert tone="info">
            Showing only items stored at <strong>{locationParam}</strong> — that’s
            where a bin-label scan lands.{" "}
            <Button variant="ghost" size="sm" onClick={clearAll}>
              Show everything
            </Button>
          </Alert>
        )}

        {locationIdParam && (
          <Alert tone="info">
            Showing items filed under the picked location and everything
            inside it.{" "}
            <Button variant="ghost" size="sm" onClick={() => setTreeLocation(null)}>
              Show everything
            </Button>
          </Alert>
        )}

        {bulkMode && (
          <Panel>
            <div style={selectionBarRowStyle}>
              <Checkbox
                name="bulk-select-all"
                label={t("inventory.bulkSelectAll")}
                checked={bulkAllViewSelected}
                disabled={bulkCollecting}
                ref={(el) => {
                  if (el) el.indeterminate = bulkSomeViewSelected;
                }}
                onChange={(e) => onBulkSelectAllToggle(e.target.checked)}
              />
              <strong>
                {t("inventory.bulkSelectedCount").replace(
                  "{count}",
                  String(bulkSelected.size),
                )}
              </strong>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setBulkSelected(new Set());
                  setBulkScope(null);
                }}
                disabled={bulkSelected.size === 0}
              >
                Clear
              </Button>
              <span style={SPACER_STYLE} />
              <Button variant="secondary" size="sm" onClick={cancelBulkEdit}>
                {t("inventory.bulkCancel")}
              </Button>
            </div>
          </Panel>
        )}

        {selecting && (
          <Panel>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <strong>
                {selectedRefs.size} item{selectedRefs.size === 1 ? "" : "s"} selected
                for labels
              </strong>
              <Button
                variant="secondary"
                size="sm"
                onClick={selectAllVisible}
                disabled={visibleRefs.length === 0 || allVisibleSelected}
              >
                Select all visible
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedRefs(new Set())}
                disabled={selectedRefs.size === 0}
              >
                Clear
              </Button>
              <span style={{ flex: 1 }} />
              <Button
                disabled={selectedRefs.size === 0}
                onClick={() =>
                  navigate(
                    `/inventory/labels?ids=${encodeURIComponent([...selectedRefs].join(","))}`,
                  )
                }
              >
                Print labels ({selectedRefs.size})
              </Button>
            </div>
          </Panel>
        )}

        {posterMode && (
          <Panel>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <strong>
                {posterSelected.size} item{posterSelected.size === 1 ? "" : "s"} selected
                for poster
              </strong>
              <Button
                variant="secondary"
                size="sm"
                onClick={selectAllVisibleForPoster}
                disabled={visibleRefs.length === 0 || allVisiblePosterSelected}
              >
                Select all visible
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPosterSelected(new Set())}
                disabled={posterSelected.size === 0}
              >
                Clear
              </Button>
              <span style={{ flex: 1 }} />
              {posterSelected.size > 50 && (
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  A poster run holds at most 50 items.
                </span>
              )}
              <Button
                disabled={
                  posterSelected.size === 0 ||
                  posterSelected.size > 50 ||
                  posterBusy
                }
                onClick={buildPoster}
              >
                {posterBusy
                  ? "Building…"
                  : `Build poster PDF (${posterSelected.size})`}
              </Button>
            </div>
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: "0.6rem 0 0" }}>
              One page per item with its photo and a QR to your public
              profile. Bulk posters print “Make offer” — for a priced
              poster (or one pointing at a marketplace listing), use
              the poster on the item's own page.
            </p>
          </Panel>
        )}

        <Tabs
          activeId={filters.category.trim() ? "" : "all"}
          onChange={changeView}
          stripExtraAfterId="all"
          stripExtra={
            starredCategories.length > 0 ? (
              <div className="tv-tabs-extra">
                {starredCategories.map((cat) => {
                  const active =
                    filters.category.trim() !== "" &&
                    categoryKey(filters.category) === categoryKey(cat.name);
                  return (
                    <button
                      key={cat.name}
                      type="button"
                      className={active ? "tv-tab is-active" : "tv-tab"}
                      aria-pressed={active}
                      onClick={() => set("category", cat.name)}
                    >
                      {categoryDisplayName(t, cat)}
                    </button>
                  );
                })}
              </div>
            ) : undefined
          }
          tabs={[
            { id: "all", label: t("inventory.view.all"), content: allContent },
          ]}
        />

        {/* Spacer so the sticky bulk bar never covers the last row. */}
        {bulkMode && bulkSelected.size > 0 && <div style={{ height: "5.5rem" }} />}

        {/* The row Actions menu's Delete confirm — the item
            page's own wording and rules, run in place. */}
        <Modal
          open={deleteTarget !== null}
          onClose={() => setDeleteTarget(null)}
          title={deleteTarget ? `Delete "${deleteTarget.name}"?` : "Delete"}
          size="sm"
          footer={
            <>
              <Button type="button" variant="secondary" onClick={() => setDeleteTarget(null)}>
                Keep it
              </Button>
              <Button
                type="button"
                variant="danger"
                onClick={() => void confirmDelete()}
                disabled={deleting}
              >
                {deleting
                  ? "Deleting…"
                  : deleteTarget?.kind === "battery"
                    ? "Delete battery"
                    : "Delete tool"}
              </Button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            This can't be undone.
            {deleteTarget?.isSet
              ? " Its pieces and their files are deleted too; attached tools are NOT deleted — they go back to standalone."
              : ""}
          </p>
        </Modal>

        <CheckoutModal
          target={checkoutTarget}
          onClose={() => setCheckoutTarget(null)}
          onDone={(checkout) => {
            setCheckoutTarget(null);
            toast(`“${checkout.item_name}” is checked out to ${checkout.borrower_name}.`, {
              tone: "success",
              title: "Checked out",
            });
            loadLending();
          }}
        />

        {/* Sticky bulk action bar (Package B): appears the moment
            one item is checked in bulk edit mode. */}
        {bulkMode && bulkSelected.size > 0 && (
          <div
            style={{
              position: "fixed",
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: "var(--z-drawer)" as unknown as number,
              background: "var(--surface)",
              borderTop: "1px solid var(--edge-strong)",
              boxShadow: "var(--shadow-bar)",
              padding: "0.6rem 0.9rem",
            }}
          >
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "center",
                flexWrap: "wrap",
                maxWidth: "1200px",
                margin: "0 auto",
              }}
            >
              <strong>
                {t("inventory.bulkSelectedCount").replace(
                  "{count}",
                  String(bulkSelected.size),
                )}
              </strong>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("location")}>
                Move to location
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("dealer")}>
                Set dealer
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("brand")}>
                Set brand
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("category")}>
                Set category
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("tag")}>
                Add tag
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={bulkBusy}
                onClick={() => void runBulk("set_standing", { standing: "broken" satisfies Standing })}
              >
                Mark broken
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={bulkBusy}
                onClick={() => void runBulk("set_standing", { standing: "in_service" satisfies Standing })}
              >
                Available
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={bulkBusy}
                onClick={() => void runBulk("set_standing", { standing: "lost" satisfies Standing })}
              >
                Lost
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={bulkBusy}
                onClick={() => void runBulk("set_standing", { standing: "stolen" satisfies Standing })}
              >
                Stolen
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setBulkModal("share")}>
                Share
              </Button>
              <Button size="sm" variant="danger" onClick={() => setBulkModal("delete")}>
                Delete
              </Button>
              <span style={{ flex: 1 }} />
              <Button size="sm" variant="ghost" onClick={() => setBulkSelected(new Set())}>
                Clear selection
              </Button>
              <Button size="sm" variant="secondary" onClick={cancelBulkEdit}>
                {t("inventory.bulkCancel")}
              </Button>
            </div>
          </div>
        )}

        {/* The location tree manager, opened from the Actions
            menu's Edit locations entry (it lived inside the
            retired toolbar tree picker) — the tree's
            add/edit/move/delete home. */}
        <LocationTreeManager
          open={locationManagerOpen}
          onClose={() => setLocationManagerOpen(false)}
          onChanged={() => setLocationTick((n) => n + 1)}
        />

        <BulkModals
          modal={bulkModal}
          onClose={() => setBulkModal(null)}
          refs={bulkRefs()}
          lookup={bulkItemLookup}
          busy={bulkBusy}
          runBulk={runBulk}
          clearSelection={() => setBulkSelected(new Set())}
        />
      </div>
    </RequireAuth>
  );
}

/** The bulk-edit action modals (Package B). Every value action
 *  rides POST /inventory/bulk through the parent's runBulk (which
 *  toasts the result or the server's 422 copy verbatim); Share is
 *  the exception — it merges the selection into the existing
 *  per-group shared lists (Settings → Sharing's PUT), sets included. */
function BulkModals({
  modal,
  onClose,
  refs,
  lookup,
  busy,
  runBulk,
  clearSelection,
}: {
  modal: BulkModalKind;
  onClose: () => void;
  refs: { kind: "tool" | "battery"; id: string }[];
  lookup: Map<string, { name: string; isSet: boolean }>;
  busy: boolean;
  runBulk: (action: string, params: Record<string, unknown>, verb?: string) => Promise<void>;
  clearSelection: () => void;
}) {
  const { toast } = useToast();
  const [locationId, setLocationId] = useState<string | null>(null);
  const [dealerId, setDealerId] = useState("");
  const [dealersAvailable, setDealersAvailable] = useState(false);
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [tagName, setTagName] = useState("");
  const [deleteText, setDeleteText] = useState("");
  // Share state: the sharing overview + per-group checks + the
  // per-set "include addons" answers for sets in the selection.
  const [shareOverview, setShareOverview] = useState<SharingOverview | null>(null);
  const [shareChecked, setShareChecked] = useState<Set<string>>(new Set());
  const [shareAddons, setShareAddons] = useState<Map<string, boolean>>(new Map());
  const [shareError, setShareError] = useState("");
  const [shareBusy, setShareBusy] = useState(false);

  useEffect(() => {
    if (modal === null) return;
    setLocationId(null);
    setDealerId("");
    setBrand("");
    setCategory("");
    setTagName("");
    setDeleteText("");
    setShareError("");
    if (modal === "share") {
      setShareOverview(null);
      api<SharingOverview>("/core/sharing")
        .then((overview) => {
          setShareOverview(overview);
          setShareChecked(
            new Set(enabledShareGroups(overview).map((g) => g.recipient_group)),
          );
        })
        .catch((err) =>
          setShareError(
            err instanceof ApiError ? err.message : "Couldn't load your sharing setup.",
          ),
        );
    }
  }, [modal]);

  const selectedSets = refs.filter(
    (r) => r.kind === "tool" && lookup.get(`tool:${r.id}`)?.isSet,
  );
  const shareGroups: ShareGroupState[] = shareOverview
    ? enabledShareGroups(shareOverview)
    : [];

  async function applyShare() {
    if (!shareOverview) return;
    setShareBusy(true);
    setShareError("");
    try {
      for (const group of shareGroups) {
        if (!shareChecked.has(group.recipient_group)) continue;
        const toolIds = new Set(group.shared_tool_ids);
        const batteryIds = new Set(group.shared_battery_ids);
        for (const ref of refs) {
          if (ref.kind === "tool") toolIds.add(ref.id);
          else batteryIds.add(ref.id);
        }
        const choices = new Map(
          (group.set_choices ?? []).map((c) => [c.tool_id, c.include_addons]),
        );
        for (const ref of selectedSets) {
          choices.set(ref.id, shareAddons.get(ref.id) ?? choices.get(ref.id) ?? false);
        }
        await api(`/core/sharing/${group.recipient_group}/items`, {
          method: "PUT",
          body: JSON.stringify({
            tool_ids: [...toolIds],
            battery_ids: [...batteryIds],
            set_choices: [...choices.entries()]
              .filter(([toolId]) => toolIds.has(toolId))
              .map(([tool_id, include_addons]) => ({ tool_id, include_addons })),
          }),
        });
      }
      toast(
        `${refs.length} item${refs.length === 1 ? "" : "s"} added to your shared list${shareChecked.size === 1 ? "" : "s"}.`,
        { tone: "success", title: "Shared" },
      );
      clearSelection();
      onClose();
    } catch (err) {
      setShareError(
        err instanceof ApiError ? err.message : "Couldn't update the shared lists.",
      );
    } finally {
      setShareBusy(false);
    }
  }

  const count = refs.length;
  const countLabel = `${count} item${count === 1 ? "" : "s"}`;

  return (
    <>
      <Modal
        open={modal === "location"}
        onClose={onClose}
        title={`Move ${countLabel} to a location`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() =>
                void runBulk("move_location", { location_id: locationId }, "moved")
              }
            >
              Move
            </Button>
          </>
        }
      >
        <FormField label="Location" htmlFor="bulk-location">
          <LocationTreePicker
            id="bulk-location"
            value={locationId}
            onChange={(next) => setLocationId(next)}
          />
        </FormField>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginBottom: 0 }}>
          “No location” unfiles the items — they keep every other detail.
        </p>
      </Modal>

      <Modal
        open={modal === "dealer"}
        onClose={onClose}
        title={`Set dealer on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!dealersAvailable}
              onClick={() =>
                void runBulk("set_dealer", { dealer_company_id: dealerId || null })
              }
            >
              Set dealer
            </Button>
          </>
        }
      >
        <DealerPicker
          id="bulk-dealer"
          label="Dealer (bought from)"
          hint="The company you bought it from — used for dealer contacts and warranty help."
          value={dealerId}
          onChange={setDealerId}
          onAvailability={setDealersAvailable}
        />
        {!dealersAvailable && (
          <p style={{ color: "var(--text-muted)", fontSize: "0.9rem", marginBottom: 0 }}>
            The dealers module isn't available, so the dealer can't be changed here.
          </p>
        )}
      </Modal>

      <Modal
        open={modal === "brand"}
        onClose={onClose}
        title={`Set brand on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!brand.trim()}
              onClick={() => void runBulk("set_brand", { brand: brand.trim() })}
            >
              Set brand
            </Button>
          </>
        }
      >
        <FormField label="Brand (manufacturer)" htmlFor="bulk-brand">
          <FieldSuggest field="brand" id="bulk-brand" value={brand} onChange={setBrand} />
        </FormField>
      </Modal>

      <Modal
        open={modal === "category"}
        onClose={onClose}
        title={`Set category on ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={() => void runBulk("set_category", { category: category.trim() })}
            >
              Set category
            </Button>
          </>
        }
      >
        <FormField label="Category" htmlFor="bulk-category">
          <FieldSuggest
            field="category"
            id="bulk-category"
            value={category}
            onChange={setCategory}
          />
        </FormField>
      </Modal>

      <Modal
        open={modal === "tag"}
        onClose={onClose}
        title={`Add a tag to ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!tagName.trim()}
              onClick={() => void runBulk("add_tag", { tag_name: tagName.trim() }, "tagged")}
            >
              Add tag
            </Button>
          </>
        }
      >
        <FormField label="Tag" htmlFor="bulk-tag">
          <TextInput
            id="bulk-tag"
            value={tagName}
            onChange={(e) => setTagName(e.target.value)}
            placeholder="Tag name"
          />
        </FormField>
      </Modal>

      <Modal
        open={modal === "share"}
        onClose={onClose}
        title={`Share ${countLabel}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={shareBusy}>
              Cancel
            </Button>
            <Button
              loading={shareBusy}
              disabled={shareGroups.length === 0 || shareChecked.size === 0}
              onClick={() => void applyShare()}
            >
              Share
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {shareError && <Alert tone="danger">{shareError}</Alert>}
          {shareOverview === null && !shareError ? (
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              <Spinner size="sm" /> Loading your sharing setup…
            </p>
          ) : shareGroups.length === 0 ? (
            <p style={{ margin: 0 }}>
              You're not sharing with any group yet — turn sharing on in
              Settings → Sharing first, then bulk-share from here.
            </p>
          ) : (
            <>
              <p style={{ margin: 0 }}>
                Add the selected items to the shared lists for:
              </p>
              <div style={{ display: "grid", gap: "0.35rem" }}>
                {shareGroups.map((g) => (
                  <Checkbox
                    key={g.recipient_group}
                    name={`bulk-share-${g.recipient_group}`}
                    label={`Share with ${accountTypeLabel(g.recipient_group)}`}
                    checked={shareChecked.has(g.recipient_group)}
                    onChange={(e) =>
                      setShareChecked((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(g.recipient_group);
                        else next.delete(g.recipient_group);
                        return next;
                      })
                    }
                  />
                ))}
              </div>
              {selectedSets.length > 0 && (
                <div style={{ display: "grid", gap: "0.35rem" }}>
                  <p style={{ margin: 0, fontWeight: 600 }}>
                    Sets in this selection — include their addons?
                  </p>
                  {selectedSets.map((ref) => (
                    <Checkbox
                      key={ref.id}
                      name={`bulk-share-addons-${ref.id}`}
                      label={`${lookup.get(`tool:${ref.id}`)?.name ?? "Set"} — include addons`}
                      checked={shareAddons.get(ref.id) ?? false}
                      onChange={(e) =>
                        setShareAddons((prev) => new Map(prev).set(ref.id, e.target.checked))
                      }
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </Modal>

      <Modal
        open={modal === "delete"}
        onClose={onClose}
        title={`Delete ${countLabel}?`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={busy}
              disabled={deleteText !== "DELETE"}
              onClick={() => void runBulk("delete", {}, "deleted")}
            >
              Delete {countLabel}
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "0.7rem" }}>
          <Alert tone="danger">
            This permanently deletes the selected items and their
            attachments. It can't be undone.
          </Alert>
          <FormField label="Type DELETE to confirm" htmlFor="bulk-delete-confirm">
            <TextInput
              id="bulk-delete-confirm"
              value={deleteText}
              onChange={(e) => setDeleteText(e.target.value)}
              placeholder="DELETE"
              autoComplete="off"
            />
          </FormField>
        </div>
      </Modal>
    </>
  );
}
