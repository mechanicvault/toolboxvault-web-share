import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import {
  Alert,
  Badge,
  BrandIcon,
  Button,
  EmptyState,
  FormField,
  InventorySkeleton,
  Modal,
  SearchBar,
  SectionPageHeader,
  Select,
  Tabs,
  TextInput,
  useToast,
  LinkButton,
  type SectionPageFact,
} from "../../components";
import {HeaderArt} from "../../components/HeaderArt";
import type {InventoryStats} from "../../components/OverviewRow";
import {
  api,
  apiPage,
  ApiError,
  TOKEN_KEY,
} from "../../lib/api";
import {activeLocale} from "../../lib/format";
import {markTabRead, useTabBadges} from "../../lib/alertCounts";
import {getBorrowingOverview} from "../borrowing/api";
import {
  CheckoutModal,
  type CheckoutTarget,
} from "../borrowing/components/CheckoutModal";
import {standingText} from "../borrowing/format";
import type {Checkout} from "../borrowing/types";
import {useAuth} from "../core/AuthContext";
import CustomFieldsSettings from "../core/CustomFieldsSettings";
import WizardDefaultsSettings from "../core/WizardDefaultsSettings";
import {useMyModules} from "../core/MyModules";
import {groupLayerWaived} from "../core/accountTypes";
import {
  SETTINGS_SECTIONS,
  sectionVisibleFor,
} from "../core/settingsMeta";
import {
  SettingsActionsMenu,
  type SettingsActionEntry,
} from "../core/SettingsActionsMenu";
import {RequireAuth} from "../core";
import {listCompanies} from "../dealers/api";
import {getExpansionCounts} from "../tool-expansion/api";
import {ExpansionBadge} from "../tool-expansion/components";
import {
  ExpansionTab,
  type ExpansionScope,
  type ExpansionSectionId,
} from "../tool-expansion/ExpansionTab";
import {OutOfServiceTab} from "../repairs/OutOfServiceTab";
import {
  RepairClaimsTab,
  type RepairSectionId,
} from "../repairs/RepairClaimsTab";
import {MaintenanceSchedules} from "../maintenance/boards";
import {DisasterClaimsSection} from "../disaster-claims/DisasterClaimsPage";
import {HealthCheckTab} from "./HealthCheckPage";
import {getOutOfService} from "../maintenance/api";
import type {OutOfServiceEntry} from "../maintenance/types";
import type {DealerCompany} from "../dealers/types";
import {ItemActionsMenu} from "./components/ItemActionsMenu";
import type {ItemStatusData} from "./components/ItemStatusStrip";
import {LocationTreeManager} from "./components/LocationTreeManager";
import {
  buildLocationTree,
  listLocationNodes,
} from "./components/locationTree";
import {useT} from "../../i18n/LocaleContext";
import {money} from "./format";
import {
  AssetSearchItem,
  BulkResult,
  CategoryRow,
  LocationNode,
  Standing,
  Tag,
  Tool,
  WarrantyStatus,
} from "./types";
import {categoryDisplayName} from "./categoryLabel";
import {
  INVENTORY_SETTING_IDS,
  categoryKey,
  Filters,
  EMPTY_FILTERS,
  WARRANTY_OPTIONS,
  SortKey,
  SORT_KEY_STORAGE,
  SORT_OPTIONS,
  sortConvention,
  SORT_DIR_STORAGE,
  storedSortDir,
  storedSort,
  useDebounced,
  BulkModalKind,
} from "./listUtils";
import {InventoryListHead} from "./listHead";
import {
  RowLending,
  AssetRow,
} from "./assetRow";
import {BulkModals} from "./bulkModals";


// The Settings sections this page owns (settingsMeta ids):
// the header Actions menu's Settings group carries exactly
// these, each landing on its own section (Actions → Settings,
// owner order 2026-11-09).
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
  // The page's two tabs (owner order, sheet row 134,
  // 2026-11-18): ALL — this list — and EXPAND, the Tool
  // Expansion page moved in here (its standalone page and
  // main-menu entry are retired; /tool-expansion redirects
  // to this tab). The old category tabs are gone: categories
  // are a Filters-panel dropdown now, nothing else. A scoped
  // arrival (?kind=&id=, from the inventory badge / an item
  // page), an #expand hash, or an ?xsec= section named by
  // the redirect opens on EXPAND.
  const kindParam = searchParams.get("kind");
  const idParam = searchParams.get("id");
  const expandScope: ExpansionScope | null =
    (kindParam === "tool" || kindParam === "battery") && idParam
      ? { kind: kindParam, id: idParam }
      : null;
  const xsecParam = searchParams.get("xsec");
  // The consolidation tabs (owner, sheet rows 136-137,
  // 2026-11-18): REPAIR CLAIMS and MAINTENANCE move in from
  // the retired Repairs & Maintenance page (row 136; the
  // disaster tab is row 137). #repair-claims / #maintenance
  // hashes and an ?rcsec= section open them directly.
  const rcsecParam = searchParams.get("rcsec");
  // Tab notification bubbles (sheet row 190): unread counts for
  // the Claims / Maintenance / Disaster tabs + the Health Check
  // tab's live issue count, from the shared tab-badge feed.
  const tabBadges = useTabBadges();
  const initialHash = window.location.hash.replace(/^#/, "");
  const [view, setView] = useState<
    | "all"
    | "expand"
    | "claims"
    | "maintenance"
    | "disaster"
    | "health"
    | "custom-fields"
    | "wizard-defaults"
  >(() =>
    expandScope || xsecParam || initialHash === "expand"
      ? "expand"
      : initialHash === "repair-claims"
        ? "claims"
        : initialHash === "maintenance"
          ? "maintenance"
          : initialHash === "disaster-claim"
            ? "disaster"
            : initialHash === "health-check"
              ? "health"
              : initialHash === "custom-fields"
                ? "custom-fields"
                : initialHash === "wizard-defaults"
                  ? "wizard-defaults"
                  : "all",
  );
  const [expandSection, setExpandSection] =
    useState<ExpansionSectionId>(() =>
      expandScope
        ? "matches"
        : xsecParam === "matches" || xsecParam === "archived"
          ? xsecParam
          : "how",
    );
  const [repairSection, setRepairSection] =
    useState<RepairSectionId>(() =>
      rcsecParam === "new" || rcsecParam === "history"
        ? rcsecParam
        : "open",
    );
  const { hash } = useLocation();
  // Follow arrivals while the page stays mounted: a badge
  // click lands its scope here, an in-app #expand link opens
  // the tab — neither yanks the reader back off EXPAND.
  useEffect(() => {
    if (expandScope) {
      setView("expand");
      setExpandSection("matches");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindParam, idParam]);
  useEffect(() => {
    const h = hash.replace(/^#/, "");
    if (h === "expand") setView("expand");
    else if (h === "repair-claims") setView("claims");
    else if (h === "maintenance") setView("maintenance");
    else if (h === "disaster-claim") setView("disaster");
    else if (h === "health-check") setView("health");
    else if (h === "custom-fields") setView("custom-fields");
    else if (h === "wizard-defaults") setView("wizard-defaults");
  }, [hash]);
  const clearExpandScope = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("kind");
    next.delete("id");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
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

  // The full category count rides the same read — it is one of
  // the header's standing facts (null until the read lands, and
  // after a failed one: the fact simply never renders).
  const [categoryCount, setCategoryCount] = useState<number | null>(null);
  // The FULL registry (same read) feeds the Filters panel's
  // category dropdown (owner, 2026-11-12: a dropdown of the
  // categories, not a text box): starters first, then the
  // owner's own, in registry order — the same set the item
  // forms' CategoryPicker offers.
  const [categoryRows, setCategoryRows] = useState<CategoryRow[]>([]);
  useEffect(() => {
    api<CategoryRow[]>("/inventory/categories")
      .then((rows) => {
        setCategoryCount(rows.length);
        setCategoryRows(rows);
      })
      .catch(() => {
        setCategoryRows([]);
      });
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

  const [assets, setAssets] = useState<AssetSearchItem[] | null>(null);
  const [error, setError] = useState("");
  // Server paging (step-4 fix D2): the active view's full match
  // count (X-Total-Count) + the Load-more machinery. Lists hold
  // every page loaded so far, in server order.
  const [total, setTotal] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // ONE selection for everything (owner, 2026-11-15): the
  // checkboxes are ALWAYS on the rows — there are no select
  // modes to arm anymore. The single set of `kind:id` refs
  // feeds Print Labels (rides to the print page in the URL),
  // Print Posters (POST /sales/poster), and every bulk action,
  // all picked from the "Selected Items:" dropdown that appears
  // in the list header once anything is checked.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [actionModal, setActionModal] = useState<BulkModalKind>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
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
    const ref = `${kind}:${id}`;
    return {
      selected: selected.has(ref),
      onToggle: () => toggleRefIn(setSelected, ref),
      label: t("inventory.col.select"),
    };
  }

  // Borrowing standing per item (module doctrine): the lending
  // chip + Check out quick action on each card. Best-effort like
  // the detail-page panel — when the borrowing module isn't
  // effective for this user the read fails and the cards simply
  // render without the footer; inventory never depends on it.
  const { toast } = useToast();
  const { has, modules: effectiveModules } = useMyModules();
  // EXPAND shows only to seats that can reach Tool Expansion
  // (reach rule: never enumerate what a seat can't open).
  const canExpand = has("tool_expansion");
  // The consolidation tabs follow the same rule (row 136):
  // REPAIR CLAIMS rides the claims module, MAINTENANCE the
  // maintenance module.
  const canClaims = has("claims");
  const canMaintenance = has("maintenance");
  // DISASTER CLAIM (row 137) rides the disaster_claims module.
  const canDisaster = has("disaster_claims");

  // Out of Service (owner, sheet row 135, 2026-11-18): a text
  // link with the count rides the showing row; clicking it
  // swaps the list area below for the out-of-service board —
  // EVERY out-of-service item, borrowed ones included, with
  // NO borrowed toggle here (the board component is locked
  // into showing them). The board is the maintenance
  // module's settled read (the row 6 predicate); the count
  // beside the link is that board plus the lent-out rows,
  // the same population the view below renders.
  const [oosOpen, setOosOpen] = useState(false);
  const [oosEntries, setOosEntries] = useState<OutOfServiceEntry[] | null>(null);
  const [oosError, setOosError] = useState<string | null>(null);
  const [oosBorrowedCount, setOosBorrowedCount] = useState(0);
  const borrowingOn = has("borrowing");
  useEffect(() => {
    let cancelled = false;
    getOutOfService()
      .then((rows) => {
        if (cancelled) return;
        setOosEntries(rows);
        setOosError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setOosError(
            err instanceof ApiError
              ? err.message
              : "Couldn't load the out-of-service board.",
          );
        }
      });
    if (borrowingOn) {
      getBorrowingOverview()
        .then((overview) => {
          if (cancelled) return;
          setOosBorrowedCount(
            overview.lent_out.filter((row) => row.state === "checked_out").length,
          );
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [refreshTick, borrowingOn]);
  const oosCount =
    oosEntries === null ? null : oosEntries.length + oosBorrowedCount;
  // One link, two faces (owner, sheet row 140, 2026-11-18):
  // closed it offers the out-of-service list; while that list
  // shows it reads "View Tools" and goes back — no separate
  // Out of Service link rides the row in that view.
  const oosLink = (
    <button
      type="button"
      className="tv-inv-oos-link"
      aria-pressed={oosOpen}
      onClick={() => setOosOpen((open) => !open)}
    >
      {oosOpen
        ? t("inventory.viewToolsLink")
        : `${t("inventory.outOfServiceLink")}${oosCount !== null ? ` (${oosCount})` : ""}`}
    </button>
  );
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

  /** The list view's request path for one page. Every filter
   *  rides the query, and the sort key goes with it
   *  (server-side order, D2). The retired kind views' own
   *  platform filter rides too: it narrows its own kind inside
   *  the merged stream server-side (owner spec 2026-10-25).
   *  The price / replacement min-max fields left the Filters
   *  panel on the owner's word (2026-11-12): the panel no
   *  longer sends min_price / max_price / min_replacement /
   *  max_replacement at all. */
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

  // The Filters panel's category dropdown (owner, 2026-11-12):
  // the select's value is the registry spelling of the active
  // filter (the starred links and this dropdown share the one
  // `filters.category`, so they must agree on screen), and a
  // filter value the registry no longer holds rides along as
  // its own option — the CategoryPicker's legacy rule — so an
  // active filter is never silently invisible in its control.
  const activeCategory = filters.category.trim();
  const matchedCategoryRow =
    activeCategory !== ""
      ? categoryRows.find(
          (row) => categoryKey(row.name) === categoryKey(activeCategory),
        )
      : undefined;
  const categorySelectValue = matchedCategoryRow
    ? matchedCategoryRow.name
    : activeCategory;
  const categoryLegacyValue =
    activeCategory !== "" && !matchedCategoryRow ? activeCategory : null;

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

  // Refs of everything currently on screen — with server paging
  // (D2) that means every page LOADED SO FAR in the list.
  // Selections are plain id sets, so picks made on earlier pages
  // stay selected while more pages load.
  const visibleRefs: string[] = (displayAssets ?? []).map(
    (a) => `${a.item_kind}:${a.id}`,
  );
  const allVisibleSelected =
    visibleRefs.length > 0 && visibleRefs.every((ref) => selected.has(ref));

  // The header's Select all / Select none TEXT LINK (owner,
  // 2026-11-15): Select all checks every row on screen; once
  // they are all checked the link reads Select none and clears
  // the whole selection.
  function toggleSelectAll() {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected((prev) => new Set([...prev, ...visibleRefs]));
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
    const picks = [...selected].map((ref) => {
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
      setSelected(new Set());
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
    return [...selected].map((ref) => {
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
    setSelected(new Set());
    setActionModal(null);
    setRefreshTick((t) => t + 1);
    loadLending();
  }

  // The "Selected Items:" dropdown (owner, 2026-11-15): every
  // action a user can take on checked items lives here — the
  // two print runs first, then every bulk-edit action. Picking
  // one runs it (or opens its modal) and the dropdown snaps
  // back to its placeholder.
  function onSelectedAction(value: string) {
    switch (value) {
      case "print-labels":
        navigate(
          `/inventory/labels?ids=${encodeURIComponent([...selected].join(","))}`,
        );
        break;
      case "print-posters":
        if (selected.size > 50) {
          toast(t("inventory.posterLimit"), {
            tone: "danger",
            title: t("inventory.printPosters"),
          });
        } else {
          void buildPoster();
        }
        break;
      case "location":
      case "dealer":
      case "brand":
      case "category":
      case "tag":
      case "share":
      case "delete":
        setActionModal(value as BulkModalKind);
        break;
      case "broken":
        void runBulk("set_standing", { standing: "broken" satisfies Standing });
        break;
      case "available":
        void runBulk("set_standing", {
          standing: "in_service" satisfies Standing,
        });
        break;
      case "lost":
        void runBulk("set_standing", { standing: "lost" satisfies Standing });
        break;
      case "stolen":
        void runBulk("set_standing", { standing: "stolen" satisfies Standing });
        break;
      case "clear":
        setSelected(new Set());
        break;
    }
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
        {oosOpen
          ? `${t("inventory.showing")} ${oosCount ?? 0} ${t("inventory.outOfServiceCount")}`
          : `${t("inventory.showing")} ${displayAssets.length} ${t("inventory.of")} ${total ?? displayAssets.length} ${(total ?? displayAssets.length) === 1 ? t("inventory.nounItemOne") : t("inventory.nounItemMany")}`}
      </p>
      {/* Phone seat for the header's Select all / Select none
          link: the column header hides at phone width, so the
          same link rides the showing row there (CSS keeps
          exactly one seat visible per width). The list's own
          controls step aside while the out-of-service view is
          open — they steer this list, not the board. */}
      {!oosOpen && (
        <button
          type="button"
          className="tv-inv-selectall-link tv-inv-selectall-link--row"
          onClick={toggleSelectAll}
        >
          {allVisibleSelected ? t("inventory.selectNone") : t("inventory.selectAll")}
        </button>
      )}
      {/* Clear search & filters rides beside the count (owner
          spec 2026-10-25: it lives on this row, so the list
          never jumps when it appears or vanishes). Absent
          entirely when nothing is filtering. */}
      {!oosOpen && filtering && (
        <Button variant="secondary" size="sm" onClick={clearAll}>
          Clear search & filters
        </Button>
      )}
      {/* The Out of Service link (owner, sheet row 135): the
          middle seat of this row, its count after it. */}
      {oosLink}
      {!oosOpen && (
      <div className="tv-inv-showing-controls">
          {/* The "Selected Items:" dropdown (owner, 2026-11-15):
              appears the moment any box is checked, seated right
              beside the sort dropdown in this row's control
              cluster (Ryan, sheet row 81 — it used to float in
              the row's center with its label stacked on top), its
              label on the dropdown's left. It carries every
              action for the checked items: Print Labels, Print
              Posters, and all the bulk-edit actions. */}
        {selected.size > 0 && (
          <div className="tv-inv-selected-actions">
            <label htmlFor="inv-selected-action">
              {t("inventory.selectedItems")} ({selected.size})
            </label>
            <Select
              id="inv-selected-action"
              aria-label={t("inventory.selectedItems")}
              value=""
              disabled={bulkBusy || posterBusy}
              onChange={(e) => onSelectedAction(e.target.value)}
            >
              <option value="" disabled>
                {t("inventory.chooseAction")}
              </option>
              <option value="print-labels">{t("inventory.printLabels")}</option>
              <option value="print-posters">{t("inventory.printPosters")}</option>
              <option value="location">{t("inventory.bulk.moveLocation")}</option>
              <option value="dealer">{t("inventory.bulk.setDealer")}</option>
              <option value="brand">{t("inventory.bulk.setBrand")}</option>
              <option value="category">{t("inventory.bulk.setCategory")}</option>
              <option value="tag">{t("inventory.bulk.addTag")}</option>
              <option value="broken">{t("inventory.bulk.markBroken")}</option>
              <option value="available">{t("inventory.bulk.markAvailable")}</option>
              <option value="lost">{t("inventory.bulk.markLost")}</option>
              <option value="stolen">{t("inventory.bulk.markStolen")}</option>
              <option value="share">{t("inventory.bulk.share")}</option>
              <option value="delete">{t("inventory.bulk.delete")}</option>
              <option value="clear">{t("inventory.bulk.clearSelection")}</option>
            </Select>
          </div>
        )}
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
      )}
    </div>
  );

  // The ALL tab's content while the out-of-service view is
  // open (row 135): the showing row (with the link, pressed)
  // over the board. The board component is locked into
  // showing borrowed rows — no toggle exists here.
  const oosContent = (
    <>
      {showingRow ?? (
        <div className="tv-inv-showing-row">{oosLink}</div>
      )}
      <OutOfServiceTab
        entries={oosEntries}
        error={oosError}
        borrowingOn={borrowingOn}
        borrowedLocked
      />
    </>
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
          className="tv-inv-list tv-inv-table tv-inv-table--selecting"
          role="table"
        >
          <InventoryListHead
            allSelected={allVisibleSelected}
            onToggleSelectAll={toggleSelectAll}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={(key) => {
              // Row 80: a click on the running column reverses
              // it (the direction button's behavior); a click on
              // a new column runs its conventional direction
              // (the dropdown's behavior). One sort state — the
              // dropdown, the direction button and the headers
              // never disagree.
              if (key === sortKey) {
                setSortDir((d) => (d === "asc" ? "desc" : "asc"));
              } else {
                setSortKey(key);
                setSortDir(sortConvention(key));
              }
            }}
          />
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
  // their settled order. The old select-mode toggles (labels /
  // poster / bulk edit) are GONE (owner, 2026-11-15): the
  // checkboxes are always on the rows and their actions live
  // in the "Selected Items:" dropdown in the list header.
  const invActionEntries: SettingsActionEntry[] = [
    // No "Add battery" entry (owner order, 2026-11-12): adding
    // a battery rides the Add wizard's own first question —
    // the ADD TOOL button opens the wizard, whose fork asks
    // "Is it a battery?" and takes the battery branch from
    // there. The menu's old deep link into the pre-answered
    // branch was a second door to the same room.
    {
      key: "import",
      label: t("inventory.import"),
      run: () => navigate("/inventory/import"),
    },
    {
      key: "health-check",
      label: t("inventory.healthCheck"),
      run: () => navigate("/inventory#health-check"),
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
          thumb={<HeaderArt name="inventory" />}
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
            <div className="tv-inv-toolbar">
            {/* The whole filter bar steers the TOOLS LIST only
                (owner, sheet row 141, 2026-11-18): on any other
                tab — and while the out-of-service board replaces
                the list — the bar greys out and every control in
                it goes dead until the user is back on the list.
                A fieldset carries the disabling: one attribute
                stills the button, both selects, the search and
                the whole Filters panel at once. */}
            <fieldset
              className="tv-inv-toolbar-set"
              disabled={view !== "all" || oosOpen}
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
                {/* Category is a DROPDOWN of the registry
                    (owner, 2026-11-12), not a text box: the
                    server matches the category param exactly,
                    so a pick always lands; the starred links
                    above the list drive this same filter. */}
                <FormField label="Category" htmlFor="inv-acat">
                  <Select
                    id="inv-acat"
                    value={categorySelectValue}
                    onChange={(e) => set("category", e.target.value)}
                  >
                    <option value="">{t("inventory.filter.allCategories")}</option>
                    {categoryRows.map((row) => (
                      <option key={row.name} value={row.name}>
                        {categoryDisplayName(t, row)}
                      </option>
                    ))}
                    {categoryLegacyValue !== null && (
                      <option value={categoryLegacyValue}>
                        {categoryLegacyValue}
                      </option>
                    )}
                  </Select>
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
                {/* The Min/Max price and Min/Max replacement
                    fields were removed from this panel on the
                    owner's word (2026-11-12) — fields, state,
                    and request params together. */}
              </div>
            )}
            </fieldset>
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

        <Tabs
          activeId={
            view === "expand" && canExpand
              ? "expand"
              : view === "claims" && canClaims
                ? "claims"
                : view === "maintenance" && canMaintenance
                  ? "maintenance"
                  : view === "disaster" && canDisaster
                    ? "disaster"
                    : view === "health"
                      ? "health"
                      : view === "custom-fields"
                        ? "custom-fields"
                        : view === "wizard-defaults"
                          ? "wizard-defaults"
                          : "all"
          }
          onChange={(id) => {
            // Row 140: the ALL tab is also the way back — from
            // the out-of-service view it returns to the full
            // tools list, not just the (already active) tab.
            if (id === "all") setOosOpen(false);
            // Row 190: clicking a tab clears its notification
            // bubble — its unread notifications are marked read.
            // The Health Check tab is the exception (owner's
            // ruling): its bubble is the live issue count and
            // stays until the items are taken care of.
            if (id === "claims" || id === "maintenance" || id === "disaster") {
              void markTabRead(id);
            }
            setView(
              id === "expand"
                ? "expand"
                : id === "claims"
                  ? "claims"
                  : id === "maintenance"
                    ? "maintenance"
                    : id === "disaster"
                      ? "disaster"
                      : id === "health"
                        ? "health"
                        : id === "custom-fields"
                          ? "custom-fields"
                          : id === "wizard-defaults"
                            ? "wizard-defaults"
                            : "all",
            );
          }}
          tabs={[
            { id: "all", label: t("inventory.view.all"), content: oosOpen ? oosContent : allContent },
            ...(canClaims
              ? [
                  {
                    id: "claims",
                    label: t("inventory.view.repairClaims"),
                    badge: tabBadges.claims,
                    content: (
                      <RepairClaimsTab
                        section={repairSection}
                        onSectionChange={setRepairSection}
                      />
                    ),
                  },
                ]
              : []),
            ...(canMaintenance
              ? [
                  {
                    id: "maintenance",
                    label: t("inventory.view.maintenance"),
                    badge: tabBadges.maintenance,
                    content: <MaintenanceSchedules />,
                  },
                ]
              : []),
            ...(canDisaster
              ? [
                  {
                    id: "disaster",
                    label: t("inventory.view.disasterClaim"),
                    badge: tabBadges.disaster,
                    // Plain like every other tab (owner, sheet
                    // row 139, 2026-11-18): the row 137 accent
                    // outline came off — it read as highlighted.
                    content: <DisasterClaimsSection />,
                  },
                ]
              : []),
            // HEALTH CHECK (owner, sheet row 150, 2026-11-18):
            // the standalone Health Check page moved in here;
            // it rides the inventory module itself, so every
            // seat on this page sees the tab.
            {
              id: "health",
              label: t("inventory.view.healthCheck"),
              badge: tabBadges.health,
              content: <HealthCheckTab />,
            },
            // The two moved Settings tabs (owner, sheet row
            // 145, 2026-11-18): Custom fields and Add-tool
            // wizard defaults live here now, removed from the
            // Settings area. They ride the inventory module
            // like the Health Check tab — no separate gate.
            // They sit before TOOL EXPANSION, which stays last
            // (row 142).
            {
              id: "custom-fields",
              label: t("settings.section.custom-fields"),
              content: <CustomFieldsSettings />,
            },
            {
              id: "wizard-defaults",
              label: t("settings.section.wizard-defaults"),
              content: <WizardDefaultsSettings />,
            },
            ...(canExpand
              ? [
                  {
                    id: "expand",
                    label: t("inventory.view.expand"),
                    content: (
                      <ExpansionTab
                        scope={expandScope}
                        onClearScope={clearExpandScope}
                        section={expandSection}
                        onSectionChange={setExpandSection}
                      />
                    ),
                  },
                ]
              : []),

          ]}
        />

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
          modal={actionModal}
          onClose={() => setActionModal(null)}
          refs={bulkRefs()}
          lookup={bulkItemLookup}
          busy={bulkBusy}
          runBulk={runBulk}
          clearSelection={() => setSelected(new Set())}
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
