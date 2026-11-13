import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { api, closeGetCacheWindow, openGetCacheWindow } from "../../lib/api";
import { DICTIONARIES, type DictKey } from "../../i18n/dictionaries";
import { useLocale, useT } from "../../i18n/LocaleContext";
import {
  Alert,
  BrandIcon,
  Button,
  EmptyState,
  Modal,
  Panel,
  SectionPageHeader,
  useToast,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import type {
  BlockSettingValue,
  BlockSize,
  ResolvedBlock,
  StoredBlockEntry,
} from "../../lib/usePageLayout";
import { useAuth } from "./AuthContext";
import { useMyModules } from "./MyModules";
import { SetupBanner } from "./onboarding";
import { ConvertAccountBar } from "./TierConversion";
import {
  buildCustomEntries,
  buildHomeRegistry,
  type HomeBoxAccess,
  type HomeRegistryEntry,
  type ResolvedHomeEntry,
} from "./homeRegistry";
import {
  HEADER_STATS_KEY,
  HomeHeaderStats,
  defaultHeaderPicks,
} from "./homeHeaderStats";
import { HeaderStatsStudio } from "./homeHeaderStatsStudio";
import {
  CUSTOM_MODULES,
  CUSTOM_MODULE_BY_ID,
  isCustomKey,
  parseCustomSettings,
} from "./homeAspects";
import { CustomOptionsPanel } from "./CustomWidgetBody";
import { HomeWizard, type WizardModuleOffer } from "./HomeWizard";
import { renderWidgetOptions } from "./widgetOptions";

/**
 * THE NEW HOME SHELL (dashboard redesign, owner-approved design
 * 2026-11-10, Lane 1). What changed from the old CorePage stack:
 *
 *  - NO global Edit view, no draft, no Save/Cancel. Every box
 *    wears its two buttons (⛶ move, ⋯ menu) at all times —
 *    INSIDE the box's own card, top-right (Ryan, 2026-11-10
 *    17:29; they rode a strip above the card before); every
 *    change — option flip, move, add, remove — saves instantly
 *    to the same layout store Home has always used
 *    (GET/PUT /api/core/layouts/home), per change.
 *  - Chrome interactions never re-run a widget's data load: the
 *    shell opens a GET cache window in lib/api for its lifetime,
 *    so an option flip re-shapes from cached reads (zero network)
 *    and the page stays fully alive — links and actions work at
 *    all times, on every box.
 *  - The stored layout is the source of truth for what is ON
 *    Home: a registry box not in the stored list lives in the
 *    gallery, not appended to the page. No stored row at all ⇒
 *    an empty grid under the header (Lane 3 retired the stats
 *    widget: the stats live in the header now, for every seat).
 *    Stored entries whose registry def isn't built right now
 *    (a switched-off module, the "panel" pseudo-entry, the tip
 *    dismissal, the header-stats config) ride through every
 *    save verbatim — nothing a user set is lost silently.
 *  - THE HEADER (Lane 3): Home wears the standard
 *    SectionPageHeader kit — plate, title, Add a widget top
 *    right — with the user's stats as bare facts inside the
 *    panel. Which stats exist for a seat is the SERVER's call
 *    (GET /api/core/header-stats enumerates the catalog from
 *    the caller's effective reach); the picks + row count ride
 *    the layout row as the "header_stats" pseudo-entry's
 *    settings bundle, saved per change like everything else.
 *  - Move is one pointer mechanism (§3.4): press-and-hold the
 *    ⛶ button (or a widget's top bar) and the box lifts into a
 *    shadow that follows the pointer while siblings ease aside
 *    around a live gap; the ⋯ menu's Move is the stepper path
 *    (on-screen ◀ ▶ ▲ ▼ + arrow keys) for anyone who can't or
 *    won't drag.
 */

const TIP_KEY = "home_tip";
const GALLERY_SEEN_KEY = "tv-home-gallery-seen";
const HOLD_MS = 200;

/** Sanitize a stored settings bundle down to the store's leaf
 *  shapes (the same read the layout hook applies). */
function sanitizeSettings(raw: unknown): Record<string, BlockSettingValue> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, BlockSettingValue> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v === "boolean" || typeof v === "number" || typeof v === "string") {
      out[k] = v;
    } else if (Array.isArray(v)) {
      out[k] = v.filter((i): i is string => typeof i === "string");
    }
  }
  return out;
}

function stringList(raw: unknown): string[] {
  return Array.isArray(raw)
    ? raw.filter((s): s is string => typeof s === "string")
    : [];
}

/** One stored entry as the PUT payload carries it — the old
 *  hook's composition rules exactly (defaults stay absent, the
 *  panel's stat picks serialize whenever present, empty bundles
 *  drop), so a shell save never rewrites a stored shape it
 *  didn't mean to touch. */
function composeEntry(e: StoredBlockEntry): StoredBlockEntry {
  const out: StoredBlockEntry = { key: e.key, visible: e.visible };
  if (e.hidden_stats && e.hidden_stats.length > 0) out.hidden_stats = e.hidden_stats;
  if (e.order && e.order.length > 0) out.order = e.order;
  if (e.panel_hidden && e.panel_hidden.length > 0) out.panel_hidden = e.panel_hidden;
  if (e.panel_order && e.panel_order.length > 0) out.panel_order = e.panel_order;
  if (e.panel_stat_order !== undefined) out.panel_stat_order = e.panel_stat_order;
  if (e.size === "half" || e.size === "full") out.size = e.size;
  const settings = sanitizeSettings(e.settings);
  if (Object.keys(settings).length > 0) out.settings = settings;
  return out;
}

/** A registry entry's NEW freshness (§3.11): flagged within the
 *  last week (days 0–6), by calendar date. */
function isFresh(entry: HomeRegistryEntry): boolean {
  if (!entry.newSince) return false;
  const then = new Date(`${entry.newSince}T00:00:00`);
  if (Number.isNaN(then.getTime())) return false;
  const days = Math.floor((Date.now() - then.getTime()) / (24 * 60 * 60 * 1000));
  return days >= 0 && days <= 6;
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

interface CarryState {
  key: string;
  mode: "drag" | "tap" | "stepper";
  /** The shadow is up (hold fired, or tap/stepper pickup). */
  active: boolean;
}

export default function HomeShell() {
  const { user } = useAuth();
  const { modules, loading: modulesLoading } = useMyModules();
  const { toast } = useToast();
  const t = useT();
  const { locale } = useLocale();
  const statLabel = (key: string, fallback: string): string =>
    (DICTIONARIES[locale] as Record<string, string>)[
      `stat.${key}` as DictKey
    ] ?? fallback;

  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [loadNonce, setLoadNonce] = useState(0);
  // The header-stats catalog as the SERVER enumerates it for
  // this caller (Lane 3): reachable keys + the server-computed
  // staff values. Null until the load lands.
  const [headerCatalog, setHeaderCatalog] = useState<{
    available: string[];
    values: Record<string, number>;
  } | null>(null);
  const [statsPickerOpen, setStatsPickerOpen] = useState(false);
  const [storedRaw, setStoredRaw] = useState<StoredBlockEntry[]>([]);
  const storedRef = useRef<StoredBlockEntry[]>([]);
  storedRef.current = storedRaw;
  const loadStateRef = useRef(loadState);
  loadStateRef.current = loadState;

  const [menuKey, setMenuKey] = useState<string | null>(null);
  const [panelKey, setPanelKey] = useState<string | null>(null);
  const [galleryOpen, setGalleryOpen] = useState(false);
  // The Add door opens the CHOOSER (§3.5): predefined gallery
  // or the custom-widget wizard (Lane 2).
  const [addView, setAddView] = useState<"chooser" | "gallery" | "wizard">(
    "chooser",
  );
  const [galleryQuery, setGalleryQuery] = useState("");
  const [gallerySeen, setGallerySeen] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem(GALLERY_SEEN_KEY) === "1";
    } catch {
      return true;
    }
  });
  const [justAddedKey, setJustAddedKey] = useState<string | null>(null);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
  const [previewKey, setPreviewKey] = useState<string | null>(null);
  const [carry, setCarry] = useState<CarryState | null>(null);
  const [moveOrder, setMoveOrder] = useState<string[] | null>(null);

  const gridRef = useRef<HTMLDivElement | null>(null);
  const slotRefs = useRef(new Map<string, HTMLDivElement>());
  const rectsRef = useRef(new Map<string, DOMRect>());
  const shadowRef = useRef<HTMLDivElement | null>(null);
  const carryRef = useRef<CarryState | null>(null);
  carryRef.current = carry;
  const moveOrderRef = useRef<string[] | null>(null);
  moveOrderRef.current = moveOrder;

  // -- GET cache window: open for the shell's whole life so an
  // option flip's reshape reads cache, never the network (§3.9).
  useEffect(() => {
    openGetCacheWindow();
    return () => closeGetCacheWindow();
  }, []);

  // -- Load the stored layout + the header-stats catalog
  // together (retry via loadNonce; the retry also heals the
  // side panel's own read of the same row). Either read failing
  // lands the same error state: saves stay off until both
  // succeed, so a failed read can never clobber a real layout
  // or offer a stat the server hasn't cleared for this seat.
  useEffect(() => {
    if (!user) return;
    let live = true;
    setLoadState("loading");
    Promise.all([
      api<{ page_key: string; blocks: StoredBlockEntry[] }>("/core/layouts/home"),
      api<{ available: string[]; values?: Record<string, number> }>(
        "/core/header-stats",
      ),
    ])
      .then(([data, catalog]) => {
        if (!live) return;
        const blocks = Array.isArray(data?.blocks)
          ? data.blocks.filter(
              (b): b is StoredBlockEntry =>
                typeof b?.key === "string" && typeof b?.visible === "boolean",
            )
          : [];
        setStoredRaw(blocks);
        setHeaderCatalog({
          available: Array.isArray(catalog?.available)
            ? catalog.available.filter((k) => typeof k === "string")
            : [],
          values:
            catalog?.values && typeof catalog.values === "object"
              ? catalog.values
              : {},
        });
        setLoadState("ready");
      })
      .catch(() => {
        if (!live) return;
        // The page renders the fresh default below — and SAYS
        // so (the standing rule): defaults never pose as the
        // user's arrangement, and saves stay off until a load
        // succeeds, so a failed read can never clobber a real
        // layout.
        setLoadState("error");
      });
    return () => {
      live = false;
    };
  }, [user, loadNonce]);

  // -- Save queue: optimistic local state, coalesced PUTs of the
  // whole composed list, sequential so an older write can never
  // land over a newer one.
  const dirtyRef = useRef<StoredBlockEntry[] | null>(null);
  const flushingRef = useRef(false);
  const flushSaves = useCallback(async () => {
    if (flushingRef.current) return;
    flushingRef.current = true;
    // A short coalesce window: a burst of option flips becomes
    // one write of the latest list.
    await new Promise((r) => setTimeout(r, 120));
    while (dirtyRef.current) {
      const list = dirtyRef.current;
      dirtyRef.current = null;
      try {
        await api("/core/layouts/home", {
          method: "PUT",
          body: JSON.stringify({ blocks: list.map(composeEntry) }),
        });
      } catch {
        toast(t("home.saveFailed"), { tone: "danger" });
      }
    }
    flushingRef.current = false;
  }, [t, toast]);

  const commit = useCallback(
    (next: StoredBlockEntry[]): boolean => {
      if (loadStateRef.current !== "ready") return false;
      setStoredRaw(next);
      storedRef.current = next;
      dirtyRef.current = next;
      void flushSaves();
      return true;
    },
    [flushSaves],
  );

  /** The list a mutation starts from: the stored list (an
   *  empty stored list IS the fresh state now — Lane 3's empty
   *  grid under the header needs no materialized default). */
  const baseList = useCallback((): StoredBlockEntry[] => {
    return storedRef.current.map((e) => ({ ...e }));
  }, []);

  // -- Mutations (each one optimistic + instantly saved) --------
  const addWidget = useCallback(
    (key: string) => {
      const list = baseList();
      const at = list.findIndex((e) => e.key === key);
      if (at >= 0) {
        const [entry] = list.splice(at, 1);
        list.push({ ...entry, visible: true });
      } else {
        list.push({ key, visible: true });
      }
      if (!commit(list)) return;
      setJustAddedKey(key);
      window.setTimeout(() => setJustAddedKey((k) => (k === key ? null : k)), 700);
      toast(t("home.addedToast"), { tone: "success" });
    },
    [baseList, commit, t, toast],
  );

  /** The wizard's Add (Lane 2): append the finished custom
   *  entry and land it on Home. The layout store caps a page
   *  at 50 entries and drops overflow silently — the wizard
   *  refuses at the cap instead of losing the box quietly. */
  const addCustom = useCallback(
    (block: StoredBlockEntry) => {
      const list = baseList();
      if (list.length >= 50) {
        toast(t("home.tooManyWidgets"), { tone: "danger" });
        return;
      }
      list.push(block);
      if (!commit(list)) return;
      setGalleryOpen(false);
      setAddView("chooser");
      setJustAddedKey(block.key);
      window.setTimeout(
        () => setJustAddedKey((k) => (k === block.key ? null : k)),
        700,
      );
      toast(t("home.addedToast"), { tone: "success" });
    },
    [baseList, commit, t, toast],
  );

  const removeWidget = useCallback(
    (key: string) => {
      const before = baseList();
      const snapshot = before.map((e) => ({ ...e }));
      // A predefined box leaves Home (its gallery card offers
      // it back). A CUSTOM box is the user's own creation —
      // removing it deletes its entry outright (the Undo toast
      // restores the snapshot whole, picks and name included).
      const next = isCustomKey(key)
        ? before.filter((e) => e.key !== key)
        : before.map((e) => (e.key === key ? { ...e, visible: false } : e));
      if (!commit(next)) {
        return;
      }
      setMenuKey(null);
      setPanelKey(null);
      toast(t("home.removedToast"), {
        action: {
          label: t("home.undo"),
          onAction: () => commit(snapshot),
        },
      });
    },
    [baseList, commit, t, toast],
  );

  const setSize = useCallback(
    (key: string, size: BlockSize, defaultSize: BlockSize) => {
      const list = baseList().map((e) => {
        if (e.key !== key) return e;
        const next = { ...e };
        if (size === defaultSize) delete next.size;
        else next.size = size;
        return next;
      });
      commit(list);
    },
    [baseList, commit],
  );

  const setSetting = useCallback(
    (key: string, name: string, value: BlockSettingValue | undefined) => {
      const list = baseList().map((e) => {
        if (e.key !== key) return e;
        const settings = { ...sanitizeSettings(e.settings) };
        if (value === undefined) delete settings[name];
        else settings[name] = value;
        const next = { ...e };
        if (Object.keys(settings).length > 0) next.settings = settings;
        else delete next.settings;
        return next;
      });
      commit(list);
    },
    [baseList, commit],
  );

  /** The header stats' writer (Lane 3): picks + row count ride
   *  the layout row as the "header_stats" pseudo-entry's
   *  settings bundle — the panel/home_tip pattern, in the
   *  store's leaf shapes ({picks: string[], rows: number}).
   *  Saved per change, like every other shell mutation. */
  const setHeaderStats = useCallback(
    (picks: string[], rows: 1 | 2) => {
      const list = baseList();
      const entry: StoredBlockEntry = {
        key: HEADER_STATS_KEY,
        visible: true,
        settings: { picks: [...picks], rows },
      };
      const at = list.findIndex((e) => e.key === HEADER_STATS_KEY);
      if (at >= 0) list[at] = entry;
      else list.push(entry);
      commit(list);
    },
    [baseList, commit],
  );

  const dismissTip = useCallback(() => {
    const list = baseList();
    const at = list.findIndex((e) => e.key === TIP_KEY);
    if (at >= 0) list[at] = { ...list[at], visible: false };
    else list.push({ key: TIP_KEY, visible: false });
    commit(list);
  }, [baseList, commit]);

  const resetHome = useCallback(() => {
    const before = baseList();
    const snapshot = before.map((e) => ({ ...e }));
    // Start over: an empty grid. Non-box entries (the side
    // panel's data, the tip dismissal, the header-stats config,
    // boxes whose module is switched off right now) are NOT
    // Home boxes — they ride through untouched, exactly as
    // every other save keeps them.
    const defKeys = new Set(defsRef.current.map((d) => d.key));
    // Custom boxes reset too — including one whose module is
    // out of reach right now (it has no def this render, but
    // "start over" means start over).
    const kept = before.filter(
      (e) => !defKeys.has(e.key) && !isCustomKey(e.key),
    );
    if (!commit(kept)) return;
    toast(t("home.resetToast"), {
      action: {
        label: t("home.undo"),
        onAction: () => commit(snapshot),
      },
    });
  }, [baseList, commit, t, toast]);

  /** Commit a finished move: the visible boxes' stored slots
   *  keep their positions in the raw list; the new order fills
   *  them in sequence (hidden boxes and extras never move). */
  const commitMove = useCallback(
    (orderedVisibleKeys: string[]) => {
      const visibleSet = new Set(orderedVisibleKeys);
      const queue = [...orderedVisibleKeys];
      const list = baseList().map((e) => {
        if (!visibleSet.has(e.key) || !e.visible) return e;
        const nextKey = queue.shift();
        if (!nextKey || nextKey === e.key) return e;
        const source = storedRef.current.find((s) => s.key === nextKey);
        return source ? { ...source } : e;
      });
      // The map above swaps whole entries among the visible
      // slots; guard the (impossible) partial case by falling
      // back to a plain reorder of the visible subsequence.
      const seenKeys = list.map((e) => e.key);
      if (new Set(seenKeys).size !== seenKeys.length) return;
      commit(list);
    },
    [baseList, commit],
  );

  // -- The access bridge: bodies read their resolved entry
  // through a ref the render below refreshes each pass (the
  // registry's render closures are built before resolution runs
  // — same bridge the old CorePage used with its layoutRef).
  const resolvedRef = useRef(new Map<string, ResolvedHomeEntry>());
  const defsRef = useRef<HomeRegistryEntry[]>([]);
  const access: HomeBoxAccess = {
    entryFor: (key) => resolvedRef.current.get(key),
  };

  // The registry is rebuilt every render (it is hook-using by
  // design — buildHomeRegistry reads the translator and the nav
  // labels) and gated by the seat, exactly like the old defs.
  const isDownloadsLevel = user?.tier === "downloads";
  const predefinedDefs = buildHomeRegistry({ user, modules, access });
  const eligiblePredefined = isDownloadsLevel
    ? predefinedDefs
    : predefinedDefs.filter((d) =>
        d.groups.some((g) => (user?.account_types ?? []).includes(g)),
      );
  // Custom boxes (Lane 2) join the defs as first-class
  // entries: a stored custom entry whose module's host is
  // eligible renders; any other rides through saves verbatim
  // like every unreached box.
  const customDefs = buildCustomEntries({
    stored: storedRaw,
    eligibleKeys: new Set(eligiblePredefined.map((d) => d.key)),
    access,
    host: (hostKey) => {
      const h = eligiblePredefined.find((d) => d.key === hostKey);
      return h
        ? { title: h.title, defaultSize: h.defaultSize, groupLabel: h.groupLabel }
        : undefined;
    },
  });
  const defs = [...predefinedDefs, ...customDefs];
  defsRef.current = defs;
  const eligibleDefs = [...eligiblePredefined, ...customDefs];
  const defByKey = new Map(eligibleDefs.map((d) => [d.key, d]));

  // The wizard's offer list: the aspect catalog's modules
  // whose host this seat can reach, wearing the host's own
  // localized title and default width.
  const wizardOffered: WizardModuleOffer[] = CUSTOM_MODULES.filter((m) =>
    defByKey.has(m.hostKey),
  ).map((m) => {
    const hostDef = defByKey.get(m.hostKey)!;
    return { mod: m, title: hostDef.title, defaultSize: hostDef.defaultSize };
  });

  // Resolution: the stored list decides what is ON Home, in
  // stored order. No stored row ⇒ an empty grid (the stats
  // live in the header). A stored "overview" entry from before
  // Lane 3 has no def anymore and resolves away here — the box
  // is simply gone, every other entry untouched.
  const resolvedEntries: ResolvedHomeEntry[] = [];
  {
    const taken = new Set<string>();
    for (const raw of storedRaw) {
      const def = defByKey.get(raw.key);
      if (!def || taken.has(def.key)) continue;
      taken.add(def.key);
      resolvedEntries.push({
        key: def.key,
        visible: raw.visible,
        size:
          raw.size === "half" || raw.size === "full"
            ? raw.size
            : def.defaultSize,
        settings: sanitizeSettings(raw.settings),
        hiddenStats: stringList(raw.hidden_stats),
        statOrder: stringList(raw.order),
      });
    }
  }
  resolvedRef.current = new Map(resolvedEntries.map((e) => [e.key, e]));
  const visibleBoxes = resolvedEntries.filter((e) => e.visible);
  const visibleKeys = visibleBoxes.map((e) => e.key);
  const tipDismissed = storedRaw.some(
    (e) => e.key === TIP_KEY && e.visible === false,
  );
  const hasFresh = eligibleDefs.some(isFresh);
  const showAddDot = hasFresh && !gallerySeen;

  // -- Header stats (Lane 3): the stored pseudo-entry's picks,
  // or the reach-filtered default set when the user has never
  // customized — either way intersected with the server's
  // available list, so a pick whose module left the seat's
  // reach stops rendering (its stored place survives untouched
  // saves, like an unreached box's entry).
  const headerEntry = storedRaw.find((e) => e.key === HEADER_STATS_KEY);
  const headerSettings = sanitizeSettings(headerEntry?.settings);
  const headerAvailable = headerCatalog?.available ?? [];
  const headerPicks = (
    headerEntry !== undefined
      ? stringList(headerSettings.picks)
      : defaultHeaderPicks(headerAvailable, isDownloadsLevel)
  )
    .filter((k) => headerAvailable.includes(k))
    .slice(0, 12);
  const headerRows: 1 | 2 = headerSettings.rows === 2 ? 2 : 1;
  const statGroupLabel = (moduleId: string): string =>
    (DICTIONARIES[locale] as Record<string, string>)[
      `home.headerStats.group.${moduleId}` as DictKey
    ] ?? moduleId;

  const openGallery = useCallback(() => {
    setAddView("chooser");
    setGalleryOpen(true);
    if (!gallerySeen) {
      setGallerySeen(true);
      try {
        window.localStorage.setItem(GALLERY_SEEN_KEY, "1");
      } catch {
        /* private mode: the dot simply returns next visit */
      }
    }
  }, [gallerySeen]);

  // -- Move engine ------------------------------------------------
  const captureRects = useCallback(() => {
    slotRefs.current.forEach((el, key) => {
      rectsRef.current.set(key, el.getBoundingClientRect());
    });
  }, []);

  const removeShadow = useCallback(() => {
    shadowRef.current?.remove();
    shadowRef.current = null;
  }, []);

  const makeShadow = useCallback(
    (key: string) => {
      removeShadow();
      const slot = slotRefs.current.get(key);
      if (!slot) return;
      const rect = slot.getBoundingClientRect();
      const clone = slot.cloneNode(true) as HTMLDivElement;
      clone.classList.add("tv-home-shadow");
      clone.removeAttribute("id");
      clone
        .querySelectorAll("[id]")
        .forEach((n) => n.removeAttribute("id"));
      Object.assign(clone.style, {
        position: "fixed",
        left: `${rect.left}px`,
        top: `${rect.top}px`,
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        margin: "0",
        zIndex: "90",
        pointerEvents: "none",
      });
      document.body.appendChild(clone);
      shadowRef.current = clone;
    },
    [removeShadow],
  );

  const endCarry = useCallback(
    (commitIt: boolean) => {
      const order = moveOrderRef.current;
      const original = visibleKeysRef.current;
      if (commitIt && order && original) {
        const changed =
          order.length !== original.length ||
          order.some((k, i) => k !== original[i]);
        if (changed) commitMove(order);
      }
      removeShadow();
      setCarry(null);
      setMoveOrder(null);
    },
    [commitMove, removeShadow],
  );

  const beginCarry = useCallback(
    (key: string, mode: CarryState["mode"]) => {
      if (loadStateRef.current !== "ready") return;
      setMenuKey(null);
      setPanelKey(null);
      captureRects();
      setMoveOrder([...visibleKeysRef.current]);
      setCarry({ key, mode, active: true });
      if (mode !== "stepper") makeShadow(key);
    },
    [captureRects, makeShadow],
  );

  const visibleKeysRef = useRef<string[]>([]);
  visibleKeysRef.current = visibleKeys;

  // FLIP: after a working-order change, slide each sibling from
  // its previous spot to its new one (§3.9's ~220ms ease).
  useLayoutEffect(() => {
    if (!carry) return;
    const reduced = prefersReducedMotion();
    slotRefs.current.forEach((el, key) => {
      const prev = rectsRef.current.get(key);
      if (!prev) return;
      const now = el.getBoundingClientRect();
      const dx = prev.left - now.left;
      const dy = prev.top - now.top;
      if (dx !== 0 || dy !== 0) {
        el.animate(
          [
            { transform: `translate(${dx}px, ${dy}px)` },
            { transform: "none" },
          ],
          { duration: reduced ? 0 : 220, easing: "ease-in-out" },
        );
      }
    });
  }, [moveOrder, carry]);

  // Pointer tracking for pickup + carry. One window-level
  // listener set, alive only while a gesture is in flight.
  const pendingRef = useRef<{
    key: string;
    pointerId: number;
    x: number;
    y: number;
    fromBar: boolean;
    timer: number;
  } | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
  } | null>(null);

  const retarget = useCallback(
    (clientX: number, clientY: number) => {
      const order = moveOrderRef.current;
      const current = carryRef.current;
      if (!order || !current) return;
      const others = order.filter((k) => k !== current.key);
      const rects = others
        .map((k) => ({ key: k, rect: slotRefs.current.get(k)?.getBoundingClientRect() }))
        .filter((r): r is { key: string; rect: DOMRect } => !!r.rect);
      let index = rects.length;
      for (let i = 0; i < rects.length; i++) {
        const r = rects[i].rect;
        const cy = r.top + r.height / 2;
        if (clientY < cy) {
          // The pointer is in this box's row, above its middle:
          // the box lands BEFORE the row — unless the row holds
          // more boxes, where the horizontal midpoints arbitrate
          // (a full-width box's top half is simply "before it";
          // its left/right half must not decide).
          const next = rects[i + 1]?.rect;
          const aloneInRow =
            !next || Math.abs(next.top + next.height / 2 - cy) > 8;
          if (aloneInRow) {
            index = i;
          } else {
            index = i;
            for (let j = i; j < rects.length; j++) {
              const rj = rects[j].rect;
              if (Math.abs(rj.top + rj.height / 2 - cy) > 8) break;
              if (clientX > rj.left + rj.width / 2) index = j + 1;
              else break;
            }
          }
          break;
        }
      }
      const next = [...others];
      next.splice(index, 0, current.key);
      const changed = next.some((k, i) => k !== order[i]);
      if (changed) {
        captureRects();
        // The ref is the gesture's working truth and must move
        // NOW, in this task: a touch tap-carry's putting-down
        // press calls retarget + endCarry back-to-back with no
        // render (and no pointermove) in between, and endCarry
        // reads the ref — a render-synced ref would still hold
        // the pre-drop order and the drop would commit nothing.
        moveOrderRef.current = next;
        setMoveOrder(next);
      }
    },
    [captureRects],
  );

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const pending = pendingRef.current;
      if (pending && e.pointerId === pending.pointerId) {
        const moved =
          Math.abs(e.clientX - pending.x) > 8 ||
          Math.abs(e.clientY - pending.y) > 8;
        if (moved && pending.fromBar) {
          // A swipe that starts on the bar is a scroll, not a
          // pickup: disarm (the hold must be a HOLD).
          window.clearTimeout(pending.timer);
          pendingRef.current = null;
          return;
        }
        if (moved && !pending.fromBar) {
          // A drag that starts on the ⛶ button itself picks the
          // box up at once (the button is not a scroll surface);
          // a press on the bar must hold first (§3.4) so touch
          // scrolling from the bar still scrolls.
          window.clearTimeout(pending.timer);
          pendingRef.current = null;
          dragRef.current = {
            pointerId: e.pointerId,
            startX: pending.x,
            startY: pending.y,
          };
          beginCarry(pending.key, "drag");
        }
        return;
      }
      const drag = dragRef.current;
      const current = carryRef.current;
      if (drag && current && e.pointerId === drag.pointerId) {
        const dx = e.clientX - drag.startX;
        const dy = e.clientY - drag.startY;
        const shadow = shadowRef.current;
        if (shadow) {
          shadow.style.transform = `translate(${dx}px, ${dy}px)`;
        }
        retarget(e.clientX, e.clientY);
        // Edge auto-scroll so a long Home is one drag deep.
        if (e.clientY < 72) window.scrollBy(0, -14);
        else if (e.clientY > window.innerHeight - 72) window.scrollBy(0, 14);
        return;
      }
      if (
        current?.mode === "tap" &&
        current.active &&
        e.pointerType === "mouse"
      ) {
        // Tap-carry: the shadow follows the mouse until the
        // next press puts the box down.
        const slot = slotRefs.current.get(current.key);
        const shadow = shadowRef.current;
        if (slot && shadow) {
          const rect = slot.getBoundingClientRect();
          shadow.style.transform = `translate(${e.clientX - (rect.left + rect.width / 2)}px, ${e.clientY - (rect.top + rect.height / 2)}px)`;
        }
        retarget(e.clientX, e.clientY);
      }
    };
    const onUp = (e: PointerEvent) => {
      const pending = pendingRef.current;
      if (pending && e.pointerId === pending.pointerId) {
        window.clearTimeout(pending.timer);
        pendingRef.current = null;
        const moved =
          Math.abs(e.clientX - pending.x) > 8 ||
          Math.abs(e.clientY - pending.y) > 8;
        if (!moved) {
          // A clean tap on ⛶ (or the bar): pick the box up and
          // let the NEXT press put it down (§3.4's tap path).
          beginCarry(pending.key, "tap");
        }
        return;
      }
      const drag = dragRef.current;
      if (drag && e.pointerId === drag.pointerId) {
        dragRef.current = null;
        endCarry(true);
        return;
      }
      const current = carryRef.current;
      if (current?.mode === "tap" && current.active) {
        // The putting-down press: wherever it lands is home.
        // Mouse hover already tracked the target on the way;
        // touch has no hover, so retarget from the press point
        // itself before committing.
        retarget(e.clientX, e.clientY);
        endCarry(true);
      }
    };
    const onCancel = () => {
      const pending = pendingRef.current;
      if (pending) {
        window.clearTimeout(pending.timer);
        pendingRef.current = null;
      }
      if (dragRef.current) {
        dragRef.current = null;
        endCarry(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      const current = carryRef.current;
      if (!current) return;
      if (e.key === "Escape") {
        e.preventDefault();
        dragRef.current = null;
        endCarry(false);
        return;
      }
      if (current.mode === "stepper") {
        const order = moveOrderRef.current;
        if (!order) return;
        const at = order.indexOf(current.key);
        const step = (delta: number) => {
          const to = at + delta;
          if (to < 0 || to >= order.length) return;
          const next = [...order];
          next.splice(at, 1);
          next.splice(to, 0, current.key);
          captureRects();
          moveOrderRef.current = next; // synchronous-truth rule
          setMoveOrder(next);
        };
        if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          step(-1);
        } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          e.preventDefault();
          step(1);
        } else if (e.key === "Enter") {
          e.preventDefault();
          endCarry(true);
        }
      }
    };
    const onDownCapture = (e: PointerEvent) => {
      // Tap-carry's putting-down press must not ALSO click
      // whatever it lands on (a link press that both drops the
      // box and navigates is a bug, not a shortcut): swallow
      // the press; the matching pointerup ends the carry.
      const current = carryRef.current;
      if (current?.mode === "tap" && current.active) {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener("pointerdown", onDownCapture, true);
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDownCapture, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
    };
  }, [beginCarry, captureRects, endCarry, retarget]);

  /** Press on the ⛶ button or the chrome bar: arm a pickup.
   *  Hold (§3.4's fifth of a second) lifts the box; a drag from
   *  the button lifts it at once; a clean tap toggles tap-carry. */
  const armPickup = useCallback(
    (key: string, fromBar: boolean) =>
      (e: ReactPointerEvent) => {
        if (carryRef.current) return;
        if (e.button !== undefined && e.button !== 0) return;
        const timer = window.setTimeout(() => {
          pendingRef.current = null;
          dragRef.current = {
            pointerId: e.pointerId,
            startX: e.clientX,
            startY: e.clientY,
          };
          beginCarry(key, "drag");
        }, HOLD_MS);
        pendingRef.current = {
          key,
          pointerId: e.pointerId,
          x: e.clientX,
          y: e.clientY,
          fromBar,
          timer,
        };
      },
    [beginCarry],
  );

  const stepMove = useCallback(
    (key: string, delta: number) => {
      const order = moveOrderRef.current;
      if (!order) return;
      const at = order.indexOf(key);
      const to = at + delta;
      if (to < 0 || to >= order.length) return;
      const next = [...order];
      next.splice(at, 1);
      next.splice(to, 0, key);
      captureRects();
      moveOrderRef.current = next; // same synchronous-truth rule as retarget
      setMoveOrder(next);
    },
    [captureRects],
  );

  // -- Menu / options-panel dismissal: a press anywhere outside
  // the owning frame closes them; Esc closes them too.
  useEffect(() => {
    if (!menuKey && !panelKey) return;
    const openKey = panelKey ?? menuKey;
    const onDown = (e: PointerEvent) => {
      const frame = (e.target as HTMLElement).closest?.("[data-home-frame]");
      if (frame?.getAttribute("data-home-frame") !== openKey) {
        setMenuKey(null);
        setPanelKey(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuKey(null);
        setPanelKey(null);
      }
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuKey, panelKey]);

  // -- Gallery grouping: account first, admin last, the rest in
  // registry (assembly) order.
  const galleryGroups: { id: string; label: string; items: HomeRegistryEntry[] }[] =
    [];
  {
    const byGroup = new Map<string, { label: string; items: HomeRegistryEntry[] }>();
    for (const entry of eligibleDefs) {
      // The gallery is the PREDEFINED catalog (§3.5): custom
      // boxes are born in the wizard, never listed here.
      if (isCustomKey(entry.key)) continue;
      const g = byGroup.get(entry.group) ?? { label: entry.groupLabel, items: [] };
      g.items.push(entry);
      byGroup.set(entry.group, g);
    }
    const order = [...byGroup.keys()].sort((a, b) => {
      if (a === "account") return -1;
      if (b === "account") return 1;
      if (a === "admin") return 1;
      if (b === "admin") return -1;
      return 0;
    });
    for (const id of order) {
      const g = byGroup.get(id)!;
      galleryGroups.push({ id, label: g.label, items: g.items });
    }
  }
  const query = galleryQuery.trim().toLowerCase();
  const galleryFilter = (entry: HomeRegistryEntry): boolean =>
    !query ||
    entry.title.toLowerCase().includes(query) ||
    t(entry.descKey).toLowerCase().includes(query);
  const onHomeKeys = new Set(visibleKeys);

  const renderOrder = moveOrder ?? visibleKeys;
  const ready = loadState === "ready" && !modulesLoading;

  return (
    <>
      <SectionPageHeader
        thumb={<ArtIcon name="inventory" size={96} />}
        title={t("nav.core")}
        actions={
          <span className="tv-home-add-wrap">
            <Button size="sm" onClick={openGallery}>
              {t("home.addWidget")}
            </Button>
            {showAddDot && (
              <span className="tv-home-add-dot" aria-hidden="true" />
            )}
            {/* The stats Customize link (owner placement,
                2026-11-10): directly under the Add-a-widget
                button in this top-right cluster — it opens the
                same in-place stats picker it opened from the
                facts row, where it used to ride. It renders
                with the stats themselves (the ready state): no
                stats, no picker to open. */}
            {ready && (
              <button
                type="button"
                className="tv-home-hstats-customize"
                onClick={() => setStatsPickerOpen(true)}
              >
                {t("home.headerStats.customize")}
              </button>
            )}
          </span>
        }
        factsExtra={
          ready ? (
            <HomeHeaderStats
              picks={headerPicks}
              available={headerAvailable}
              serverValues={headerCatalog?.values ?? {}}
              statLabel={statLabel}
            />
          ) : undefined
        }
      />
      <SetupBanner />
      {/* Tier conversion (2026-11-10): the primary door out of
          the downloads level — a self-contained bar that renders
          ONLY for that tier, above the widget grid. */}
      <ConvertAccountBar />
      {loadState === "error" && (
        <Alert tone="danger">
          <span>{t("home.layoutLoadFailed")}</span>{" "}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setLoadNonce((n) => n + 1);
              // The side panel keeps its OWN read of the same
              // layout (HomePanel) — one retry heals both.
              window.dispatchEvent(new Event("tv:layout-retry"));
            }}
          >
            {t("home.layoutRetry")}
          </Button>
        </Alert>
      )}
      {!ready ? (
        <div className="tv-home-blocks" aria-hidden="true">
          <div className="tv-block-slot" data-size="full">
            <section>
              <div className="tv-overview-grid">
                {Array.from({ length: 6 }, (_, i) => (
                  <div key={i} className="tv-skel tv-skel-stat" />
                ))}
              </div>
            </section>
          </div>
        </div>
      ) : (
        <>
          {!tipDismissed && (
            <div className="tv-dash-tip" role="note">
              <div className="tv-dash-tip-text">
                <strong>{t("home.tip.title")}</strong>
                <p>{t("home.tip.body")}</p>
              </div>
              <div className="tv-dash-tip-actions">
                <Button variant="ghost" size="sm" onClick={dismissTip}>
                  {t("home.tip.dismiss")}
                </Button>
              </div>
            </div>
          )}
          {carry?.active && (
            <div className="tv-home-carry-hint" role="status">
              {t(
                carry.mode === "stepper"
                  ? "home.stepperHint"
                  : carry.mode === "tap"
                    ? "home.carryHintTap"
                    : "home.carryHint",
              )}
            </div>
          )}
          {visibleBoxes.length === 0 && (
            <Panel>
              <EmptyState
                icon={<BrandIcon name="apps-grid" size={56} />}
                title={t("home.emptyTitle")}
                description={t("home.emptyBody")}
                action={
                  <Button onClick={openGallery}>{t("home.addWidget")}</Button>
                }
              />
            </Panel>
          )}
          <div className="tv-home-blocks" ref={gridRef}>
            {renderOrder.map((key) => {
              const def = defByKey.get(key);
              const entry = resolvedRef.current.get(key);
              if (!def || !entry) return null;
              const isCarried = carry?.key === key && carry.active;
              const isStepping = isCarried && carry.mode === "stepper";
              const customParsed = isCustomKey(key)
                ? parseCustomSettings(entry.settings)
                : null;
              const customMod = customParsed
                ? CUSTOM_MODULE_BY_ID[customParsed.moduleId]
                : undefined;
              const optionsContent = customMod ? (
                  <CustomOptionsPanel
                    mod={customMod}
                    settings={entry.settings}
                    setSetting={(name, value) => setSetting(key, name, value)}
                  />
                ) : (
                  renderWidgetOptions(
                    {
                      ...def,
                      render: () => null,
                      visible: true,
                      hiddenStats: [],
                      statOrder: [],
                      size: entry.size,
                      settings: entry.settings,
                    } as ResolvedBlock,
                    (name, value) => setSetting(key, name, value),
                  )
                );
              return (
                <div
                  key={key}
                  className="tv-block-slot"
                  data-size={entry.size}
                  ref={(el) => {
                    if (el) slotRefs.current.set(key, el);
                    else slotRefs.current.delete(key);
                  }}
                >
                  <div
                    className={
                      "tv-home-frame" +
                      (justAddedKey === key ? " tv-home-frame--in" : "")
                    }
                    data-home-frame={key}
                    data-carrying={isCarried || undefined}
                    data-stepping={isStepping || undefined}
                  >
                    <div
                      className="tv-home-chrome"
                      onPointerDown={(e) => {
                        if (
                          (e.target as HTMLElement).closest(
                            "button, a, input, select, textarea",
                          )
                        ) {
                          return;
                        }
                        armPickup(key, true)(e);
                      }}
                    >
                      {isStepping ? (
                        <span
                          className="tv-home-stepper"
                          onPointerDown={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            aria-label="Move earlier"
                            onClick={() => stepMove(key, -1)}
                          >
                            {"◀"}
                          </button>
                          <button
                            type="button"
                            aria-label="Move later"
                            onClick={() => stepMove(key, 1)}
                          >
                            {"▶"}
                          </button>
                          <button
                            type="button"
                            aria-label="Move up"
                            onClick={() => stepMove(key, -1)}
                          >
                            {"▲"}
                          </button>
                          <button
                            type="button"
                            aria-label="Move down"
                            onClick={() => stepMove(key, 1)}
                          >
                            {"▼"}
                          </button>
                          <button
                            type="button"
                            className="tv-home-stepper-done"
                            onClick={() => endCarry(true)}
                          >
                            {t("home.moveDone")}
                          </button>
                        </span>
                      ) : (
                        <span className="tv-home-chrome-spacer" />
                      )}
                      <button
                        type="button"
                        className="tv-home-btn tv-home-btn--move"
                        aria-label={`${t("home.move")}: ${def.title}`}
                        title={t("home.move")}
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          armPickup(key, false)(e);
                        }}
                      >
                        <MoveGlyph />
                        <span className="tv-home-btn-label">{t("home.move")}</span>
                      </button>
                      <button
                        type="button"
                        className="tv-home-btn tv-home-btn--menu"
                        aria-label={`${t("home.widgetMenu")}: ${def.title}`}
                        aria-haspopup="menu"
                        aria-expanded={menuKey === key}
                        title={t("home.widgetMenu")}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() => {
                          setPanelKey(null);
                          setMenuKey((k) => (k === key ? null : key));
                        }}
                      >
                        <span aria-hidden="true">{"⋯"}</span>
                        <span className="tv-home-btn-label">{t("home.menuShort")}</span>
                      </button>
                    </div>
                    {menuKey === key && (
                      <div className="tv-home-menu" role="menu">
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setMenuKey(null);
                            setPanelKey(key);
                          }}
                        >
                          {t("home.editOptions")}
                        </button>
                        {isCustomKey(key) && (
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              setMenuKey(null);
                              setPanelKey(key);
                            }}
                          >
                            {t("home.rename")}
                          </button>
                        )}
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => beginCarry(key, "stepper")}
                        >
                          {t("home.move")}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          className="tv-home-menu-danger"
                          onClick={() => removeWidget(key)}
                        >
                          {t("home.remove")}
                        </button>
                      </div>
                    )}
                    {panelKey === key && (
                      <div
                        className="tv-home-opts"
                        role="dialog"
                        aria-label={`${t("home.options")}: ${def.title}`}
                      >
                        <div className="tv-home-opts-head">
                          <strong>{def.title}</strong>
                          <button
                            type="button"
                            className="tv-home-opts-close"
                            aria-label={t("home.close")}
                            onClick={() => setPanelKey(null)}
                          >
                            {"×"}
                          </button>
                        </div>
                        <div className="tv-block-opts-group">
                          <span className="tv-block-opts-label">
                            {t("home.boxWidth")}
                          </span>
                          <div
                            className="tv-opts-size"
                            role="group"
                            aria-label={t("home.boxWidth")}
                          >
                            <button
                              type="button"
                              aria-pressed={entry.size === "half"}
                              data-active={entry.size === "half" || undefined}
                              onClick={() => setSize(key, "half", def.defaultSize)}
                            >
                              {t("home.widthHalf")}
                            </button>
                            <button
                              type="button"
                              aria-pressed={entry.size === "full"}
                              data-active={entry.size === "full" || undefined}
                              onClick={() => setSize(key, "full", def.defaultSize)}
                            >
                              {t("home.widthFull")}
                            </button>
                          </div>
                        </div>
                        {optionsContent}
                      </div>
                    )}
                    <div className="tv-home-body">{def.render(access)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
      <Modal
        open={galleryOpen}
        onClose={() => {
          setGalleryOpen(false);
          setAddView("chooser");
        }}
        title={t("home.addWidget")}
        size="lg"
      >
        {addView === "chooser" && (
          <div className="tv-chooser">
            <p className="tv-muted">{t("home.chooser.intro")}</p>
            <div className="tv-chooser-doors">
              <button
                type="button"
                className="tv-chooser-door"
                onClick={() => setAddView("gallery")}
              >
                <span className="tv-chooser-door-name">
                  {t("home.chooser.predefined")}
                </span>
                <span className="tv-muted">
                  {t("home.chooser.predefinedDesc")}
                </span>
              </button>
              <button
                type="button"
                className="tv-chooser-door"
                onClick={() => setAddView("wizard")}
              >
                <span className="tv-chooser-door-name">
                  {t("home.chooser.custom")}
                </span>
                <span className="tv-muted">
                  {t("home.chooser.customDesc")}
                </span>
              </button>
            </div>
          </div>
        )}
        {addView === "wizard" && (
          <HomeWizard
            offered={wizardOffered}
            onCancel={() => setAddView("chooser")}
            onAdd={addCustom}
          />
        )}
        {addView === "gallery" && (
        <div className="tv-home-gallery">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAddView("chooser")}
          >
            {`← ${t("home.chooser.back")}`}
          </Button>
          <p className="tv-muted">{t("home.gallery.intro")}</p>
          <input
            type="search"
            className="tv-home-gallery-search"
            placeholder={t("home.gallery.search")}
            aria-label={t("home.gallery.search")}
            value={galleryQuery}
            onChange={(e) => setGalleryQuery(e.target.value)}
          />
          {galleryGroups.every((g) => g.items.filter(galleryFilter).length === 0) && (
            <p className="tv-muted">{t("home.gallery.noMatch")}</p>
          )}
          {galleryGroups.map((group) => {
            const items = group.items.filter(galleryFilter);
            if (items.length === 0) return null;
            return (
              <section key={group.id} className="tv-home-gallery-group">
                <h3>{group.label}</h3>
                <div className="tv-home-gallery-grid">
                  {items.map((entry) => {
                    const onHome = onHomeKeys.has(entry.key);
                    return (
                      <div key={entry.key} className="tv-home-gallery-card">
                        <div className="tv-home-gallery-card-head">
                          <span className="tv-home-gallery-icon" aria-hidden="true">
                            {entry.icon}
                          </span>
                          <strong>{entry.title}</strong>
                          {isFresh(entry) && (
                            <span className="tv-home-gallery-new">
                              {t("home.gallery.new")}
                            </span>
                          )}
                        </div>
                        <p className="tv-muted">{t(entry.descKey)}</p>
                        <div className="tv-home-gallery-card-actions">
                          {onHome ? (
                            <span className="tv-home-gallery-onhome">
                              {t("home.gallery.onHome")}
                            </span>
                          ) : (
                            <Button
                              size="sm"
                              onClick={() => addWidget(entry.key)}
                            >
                              {t("home.add")}
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-expanded={previewKey === entry.key}
                            onClick={() =>
                              setPreviewKey((k) =>
                                k === entry.key ? null : entry.key,
                              )
                            }
                          >
                            {t(
                              previewKey === entry.key
                                ? "home.gallery.hidePreview"
                                : "home.gallery.preview",
                            )}
                          </Button>
                        </div>
                        {previewKey === entry.key && (
                          <div
                            className="tv-home-gallery-preview"
                            aria-hidden="true"
                          >
                            {entry.render(access)}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
        )}
      </Modal>
      <Modal
        open={statsPickerOpen}
        onClose={() => setStatsPickerOpen(false)}
        title={t("home.headerStats.title")}
        size="lg"
        footer={
          <div className="tv-hstudio-footer">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setResetConfirmOpen(true)}
            >
              {t("home.resetHome")}
            </Button>
            <span className="tv-hstudio-autosave">
              {t("home.headerStudio.autoSave")}
            </span>
            <Button
              className="tv-hstudio-done"
              onClick={() => setStatsPickerOpen(false)}
            >
              {t("home.headerStudio.done")}
            </Button>
          </div>
        }
      >
        <HeaderStatsStudio
          picks={headerPicks}
          rows={headerRows}
          available={headerAvailable}
          serverValues={headerCatalog?.values ?? {}}
          statLabel={statLabel}
          groupLabel={statGroupLabel}
          onChange={setHeaderStats}
        />
      </Modal>
      <Modal
        open={resetConfirmOpen}
        onClose={() => setResetConfirmOpen(false)}
        title={t("home.resetConfirmTitle")}
        size="sm"
        footer={
          <div className="tv-home-gallery-foot">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setResetConfirmOpen(false)}
            >
              {t("home.cancel")}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                setResetConfirmOpen(false);
                setStatsPickerOpen(false);
                setGalleryOpen(false);
                resetHome();
              }}
            >
              {t("home.resetConfirmAction")}
            </Button>
          </div>
        }
      >
        <p>{t("home.resetConfirmBody")}</p>
      </Modal>
    </>
  );
}

/** The four-corner-squares move glyph (§3.2's ⛶ button face): a
 *  pure control symbol, drawn as four corner brackets. */
function MoveGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M1 5V1h4M11 1h4v4M15 11v4h-4M5 15H1v-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
