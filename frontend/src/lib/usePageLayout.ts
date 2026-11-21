import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { AccountType } from "../modules/core/accountTypes";
import { api } from "./api";

/**
 * PAGE LAYOUTS — per-user page block arrangement (owner directive
 * 2026-10-17: users choose which blocks appear on each page they can
 * access, and their order; the layout is stored per account, server
 * side, via GET/PUT /api/core/layouts/{pageKey}).
 *
 * ADOPTING THIS ON A NEW PAGE (a few lines):
 *   1. Define the page's blocks: an array of PageBlockDef — a stable
 *      `key`, a `title` (shown in customize mode), the account
 *      `groups` the block serves (union rule, same as modules and
 *      overview stats), and a `render()` for its content.
 *   2. Call the hook:
 *        const layout = usePageLayout("inventory", blocks, {
 *          accountTypes: user?.account_types,
 *          enabled: !!user,
 *        });
 *   3. Render <PageBlocks {...layout} /> and, for signed-in users, a
 *      "Customize view" button calling layout.beginEdit() — while
 *      layout.editing is true, show Save (layout.saveEdit()) and
 *      Cancel (layout.cancelEdit()) instead. That's it: ordering,
 *      visibility, group gating, persistence, and "new blocks append
 *      visibly at the end" all come from here.
 *
 * RESOLUTION RULES (resolvePageBlocks):
 *   - A block renders only when ANY of the user's groups is in the
 *     block's `groups` (omit `accountTypes` — style guide only — and
 *     every registered block counts).
 *   - No saved layout → registered order, all visible — except a
 *     block whose def registers `defaultVisible: false` (Home's
 *     Notifications block, owner 2026-11-03), which starts hidden.
 *   - Saved layout → saved order/visibility for blocks still
 *     registered AND group-eligible; stored keys for anything else
 *     are ignored; registered blocks missing from the saved layout
 *     (new since the user customized) append at the end, visible —
 *     or hidden when the def registers `defaultVisible: false`.
 *     A block the layout DOES carry keeps its stored visibility
 *     either way: an explicit saved choice always wins.
 *   - A block's stored size/settings (widget options Wave 1)
 *     ride through resolution the same way: size falls back to
 *     the def's defaultSize, settings to an empty bundle.
 */

/** A block's Home grid width (widget options Wave 1, owner
 *  design 2026-11-02): the grid runs two columns, so a block is
 *  either half a row or the whole row. */
export type BlockSize = "half" | "full";

/** One value of a block's settings bundle: the flat leaf shapes
 *  the layout store carries (the server sanitizes to exactly
 *  these on save — see core's save_page_layout). */
export type BlockSettingValue = string | number | boolean | string[];

export interface PageBlockDef {
  /** Stable identity — persisted in the user's saved layout. Never rename. */
  key: string;
  /** Human name, shown on the block's chrome bar in customize mode. */
  title: string;
  /** Account groups this block serves (union visibility). */
  groups: AccountType[];
  /**
   * The width the block takes until the user chooses otherwise
   * (widget options Wave 1): module widgets register "half";
   * the special blocks (Overview, Notifications, the dealer
   * dashboard) leave the "full" default — today's shapes.
   */
  defaultSize?: BlockSize;
  /**
   * Whether the block shows for a user whose saved layout does
   * not explicitly carry it (no layout at all, or no entry for
   * this block). Absent = visible — the standing rule. A def may
   * register `false` to start hidden (Home's Notifications
   * block, owner 2026-11-03: "make the notifications widget off
   * by default"). Never a one-way door: the block stays in the
   * registry, so Edit view's ADD menu offers it and a stored
   * entry always overrides the default in both directions.
   */
  defaultVisible?: boolean;
  render: () => ReactNode;
}

export interface StoredBlockEntry {
  key: string;
  visible: boolean;
  /**
   * Block-level extra the overview block carries (owner review
   * round 1, 2026-10-19): the stat keys the user hid inside the
   * block. The server stores and returns it opaquely on the
   * block's entry; absent = nothing hidden.
   */
  hidden_stats?: string[];
  /**
   * Second block-level extra (Home + Header program, 2026-10-24):
   * the overview block's per-stat display ORDER (stat keys in the
   * user's drag order). Same opaque contract; absent = registry
   * order.
   */
  order?: string[];
  /**
   * Home panel pseudo-entry extras (Phase C, 2026-10-24): the
   * entry with key "panel" carries the Home side panel's hidden
   * section keys and section order. Same opaque contract; absent
   * = all sections shown in registry order.
   */
  panel_hidden?: string[];
  panel_order?: string[];
  /**
   * Third panel extra (Phase 3, 2026-10-24): the user's panel
   * stat PICKS in display order — a pick list, not a hidden
   * list (see the backend schema note). Unlike the other
   * extras this one serializes whenever it is PRESENT, empty
   * list included: an empty list is a real choice (no stat
   * rows), while absence means "never customized".
   */
  panel_stat_order?: string[];
  /**
   * Framework extras (widget options Wave 1, 2026-11-02): the
   * block's grid width and its per-widget options bundle. The
   * server stores them opaquely on the block's entry (size as a
   * closed pair, settings sanitized leaf-by-leaf); absent =
   * the registered default width / no options set.
   */
  size?: string;
  settings?: Record<string, unknown>;
}

/** Snapshot a resolved block for the edit draft: the settings
 *  bundle is copied too, so a draft write can never mutate the
 *  resolved (saved) arrangement behind Cancel's back. */
function cloneBlockForDraft(b: ResolvedBlock): ResolvedBlock {
  return { ...b, settings: { ...b.settings } };
}

/** A registered block with its resolved visibility for this user. */
export interface ResolvedBlock extends PageBlockDef {
  visible: boolean;
  /** Stat keys hidden inside this block (overview block only). */
  hiddenStats: string[];
  /** Stat display order inside this block (overview block only). */
  statOrder: string[];
  /** Resolved grid width: the stored choice when valid, else
   *  the def's registered default (widget options Wave 1). */
  size: BlockSize;
  /** The block's options bundle (widget options Wave 1): only
   *  the store's leaf shapes survive the read; {} = none set. */
  settings: Record<string, BlockSettingValue>;
}

/** Read a stored settings bundle down to the store's leaf
 *  shapes (the server sanitizes again on save — this keeps a
 *  foreign or corrupt payload from ever reaching a widget). */
function sanitizeBlockSettings(
  raw: unknown,
): Record<string, BlockSettingValue> {
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

/** A stored entry's width when it names a valid one, else the
 *  def's registered default ("full" when the def doesn't say). */
function resolveBlockSize(def: PageBlockDef, entry?: StoredBlockEntry): BlockSize {
  if (entry?.size === "half" || entry?.size === "full") return entry.size;
  return def.defaultSize ?? "full";
}

interface StoredLayoutResponse {
  page_key: string;
  blocks: StoredBlockEntry[];
}

function isEligible(def: PageBlockDef, accountTypes?: AccountType[]): boolean {
  return (
    accountTypes === undefined ||
    def.groups.some((g) => accountTypes.includes(g))
  );
}

/** Pure resolution: registered defs + stored layout + the user's
 *  groups → the ordered, group-filtered block list to render. */
export function resolvePageBlocks(
  defs: PageBlockDef[],
  stored: StoredBlockEntry[] | null,
  accountTypes?: AccountType[],
): ResolvedBlock[] {
  const eligible = defs.filter((d) => isEligible(d, accountTypes));
  if (!stored || stored.length === 0) {
    return eligible.map((d) => ({
      ...d,
      visible: d.defaultVisible ?? true,
      hiddenStats: [],
      statOrder: [],
      size: resolveBlockSize(d),
      settings: {},
    }));
  }
  const byKey = new Map(eligible.map((d) => [d.key, d]));
  const taken = new Set<string>();
  const resolved: ResolvedBlock[] = [];
  for (const entry of stored) {
    const def = byKey.get(entry.key);
    if (!def || taken.has(def.key)) continue;
    taken.add(def.key);
    resolved.push({
      ...def,
      visible: entry.visible,
      hiddenStats: Array.isArray(entry.hidden_stats)
        ? entry.hidden_stats.filter((s) => typeof s === "string")
        : [],
      statOrder: Array.isArray(entry.order)
        ? entry.order.filter((s) => typeof s === "string")
        : [],
      size: resolveBlockSize(def, entry),
      settings: sanitizeBlockSettings(entry.settings),
    });
  }
  for (const def of eligible) {
    if (!taken.has(def.key)) {
      resolved.push({
        ...def,
        visible: def.defaultVisible ?? true,
        hiddenStats: [],
        statOrder: [],
        size: resolveBlockSize(def),
        settings: {},
      });
    }
  }
  return resolved;
}

export interface PageLayout {
  /** Blocks to render: resolved (or the working draft while editing). */
  blocks: ResolvedBlock[];
  /** True once the saved-layout fetch has settled (success OR
   *  failure) for the current user/page. */
  loaded: boolean;
  /** True when the saved-layout fetch FAILED: the page is
   *  showing the registered defaults, which are NOT the user's
   *  saved layout — callers must surface this (with retryLoad)
   *  instead of letting defaults pose as the user's own. */
  loadError: boolean;
  /** Re-run the saved-layout fetch (after a loadError). */
  retryLoad: () => void;
  /**
   * Stored entries that do NOT resolve to a registered block for
   * this user (Phase C generic extension): pseudo-entries like
   * Home's {key:"panel"} ride here — surfaced at load, editable
   * via updateExtra while editing, and re-included at save so a
   * page's block save never silently drops them.
   */
  extras: StoredBlockEntry[];
  /** Patch one extra entry (draft only while editing). */
  updateExtra: (key: string, patch: Partial<StoredBlockEntry>) => void;
  editing: boolean;
  saving: boolean;
  beginEdit: () => void;
  cancelEdit: () => void;
  /** Persists the draft. Resolves true on success, false on failure
   *  (the draft stays open so the user can retry or cancel). */
  saveEdit: () => Promise<boolean>;
  toggleBlock: (key: string) => void;
  /** Set a block's visibility outright (draft only) — the red X
   *  (remove) and the ADD dropdown (restore) speak this, not the
   *  toggle, so a click can never land on the wrong side. */
  setBlockVisible: (key: string, visible: boolean) => void;
  /** Replace the draft's block order wholesale (drag reorder). */
  reorderBlocks: (keys: string[]) => void;
  /** Flip one stat's hidden state inside a block (draft only). */
  toggleStat: (blockKey: string, statKey: string) => void;
  /** Replace one block's stat order wholesale (drag reorder). */
  setStatOrder: (blockKey: string, statKeys: string[]) => void;
  /** Set one block's grid width (draft only, widget options
   *  Wave 1) — the options popover's Half | Full choice. */
  setBlockSize: (key: string, size: BlockSize) => void;
  /** Write one option into a block's settings bundle (draft
   *  only, widget options Wave 1); undefined removes the key —
   *  absence is the bundle's unset state. */
  setBlockSetting: (
    key: string,
    name: string,
    value: BlockSettingValue | undefined,
  ) => void;
}

export interface UsePageLayoutOptions {
  /** The signed-in user's group set; omit only outside the app. */
  accountTypes?: AccountType[];
  /** False (e.g. signed out) = never fetch or save; defaults apply. */
  enabled?: boolean;
  /**
   * One-shot stored-layout migration (Home + Header program):
   * transforms the fetched entries before resolution — Home uses
   * it to fold the retired "modules" block into the per-module
   * widget blocks. Runs on LOAD only (the server echo after a
   * save is already in the new shape).
   */
  migrateStored?: (blocks: StoredBlockEntry[]) => StoredBlockEntry[];
}

export function usePageLayout(
  pageKey: string,
  defs: PageBlockDef[],
  options: UsePageLayoutOptions = {},
): PageLayout {
  const { accountTypes, enabled = true, migrateStored } = options;
  const migrateRef = useRef(migrateStored);
  migrateRef.current = migrateStored;
  const defsRef = useRef(defs);
  defsRef.current = defs;
  const accountTypesRef = useRef(accountTypes);
  accountTypesRef.current = accountTypes;
  const [stored, setStored] = useState<StoredBlockEntry[] | null>(null);
  const [draft, setDraft] = useState<ResolvedBlock[] | null>(null);
  const [extraDraft, setExtraDraft] = useState<StoredBlockEntry[] | null>(null);
  const [saving, setSaving] = useState(false);
  // Load settlement (owner bug report, 2026-10-24): beginEdit
  // used to snapshot whatever was resolved at call time — call
  // it before the fetch landed (the header's Edit view request
  // fires at mount) and the draft was the page DEFAULTS wearing
  // the user's name: "my saved changes are gone." An edit
  // requested before settlement now QUEUES and snapshots the
  // freshly loaded layout when the fetch lands. A failed fetch
  // settles too, but raises loadError so the page can say so —
  // defaults must never silently pose as the user's layout.
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loadNonce, setLoadNonce] = useState(0);
  const loadedRef = useRef(false);
  const pendingEditRef = useRef(false);
  // Set when the open draft was snapshotted from defaults after
  // a FAILED load: a later successful (re)load replaces that
  // draft with the real layout — the bogus draft must not
  // outlive the retry that fixes it.
  const draftFromErrorRef = useRef(false);

  const retryLoad = useCallback(() => {
    setLoadError(false);
    setLoadNonce((n) => n + 1);
  }, []);

  // Load the saved layout once per page/user (loadNonce re-runs
  // it for the retry affordance). The page must never BREAK
  // because an arrangement couldn't load — it renders defaults —
  // but the failure is reported via loadError, never silent.
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    loadedRef.current = false;
    setLoaded(false);
    api<StoredLayoutResponse>(`/core/layouts/${pageKey}`)
      .then((data) => {
        if (!live) return;
        const blocks = Array.isArray(data?.blocks)
          ? data.blocks.filter(
              (b): b is StoredBlockEntry =>
                typeof b?.key === "string" && typeof b?.visible === "boolean",
            )
          : [];
        // hidden_stats / order ride through untouched here —
        // resolution sanitizes them (resolvePageBlocks), the
        // store just keeps them. A page-supplied migration folds
        // retired block shapes into the current model on load.
        const migrated = migrateRef.current
          ? migrateRef.current(blocks)
          : blocks;
        setStored(migrated.length > 0 ? migrated : null);
        loadedRef.current = true;
        setLoaded(true);
        setLoadError(false);
        if (draftFromErrorRef.current) {
          draftFromErrorRef.current = false;
          const fresh = resolvePageBlocks(
            defsRef.current,
            migrated.length > 0 ? migrated : null,
            accountTypesRef.current,
          );
          setDraft(fresh.map(cloneBlockForDraft));
          const defKeys = new Set(defsRef.current.map((d) => d.key));
          setExtraDraft(
            migrated.filter((e) => !defKeys.has(e.key)).map((e) => ({ ...e })),
          );
        }
        if (pendingEditRef.current) {
          pendingEditRef.current = false;
          // Snapshot the FRESH layout — the whole point of the
          // queue: the draft is the user's saved arrangement,
          // never the pre-load defaults.
          const fresh = resolvePageBlocks(
            defsRef.current,
            migrated.length > 0 ? migrated : null,
            accountTypesRef.current,
          );
          setDraft(fresh.map(cloneBlockForDraft));
          const defKeys = new Set(defsRef.current.map((d) => d.key));
          setExtraDraft(
            migrated.filter((e) => !defKeys.has(e.key)).map((e) => ({ ...e })),
          );
        }
      })
      .catch(() => {
        if (!live) return;
        loadedRef.current = true;
        setLoaded(true);
        setLoadError(true);
        if (pendingEditRef.current) {
          pendingEditRef.current = false;
          // The edit still opens (the request was explicit),
          // on the defaults — with loadError raised so the page
          // shows the failure and a retry instead of pretending
          // these are the user's saved blocks.
          const defaults = resolvePageBlocks(
            defsRef.current,
            null,
            accountTypesRef.current,
          );
          draftFromErrorRef.current = true;
          setDraft(defaults.map(cloneBlockForDraft));
          setExtraDraft([]);
        }
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageKey, enabled, loadNonce]);

  // Resolve against the CURRENT defs every render (render closures
  // stay fresh); only the order/visibility computation is memoized.
  const defsKey = defs.map((d) => d.key).join(",");
  const typesKey = (accountTypes ?? []).join(",");
  const order = useMemo(
    () =>
      resolvePageBlocks(defs, stored, accountTypes).map(
        ({ key, visible, hiddenStats, statOrder, size, settings }) => ({
          key,
          visible,
          hiddenStats,
          statOrder,
          size,
          settings,
        }),
      ),
    // defs/accountTypes are captured via their key signatures: defs
    // are re-created per render by callers but are key-stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [defsKey, typesKey, stored],
  );
  const resolved: ResolvedBlock[] = order
    .map((entry) => {
      const def = defs.find((d) => d.key === entry.key);
      return def
        ? {
            ...def,
            visible: entry.visible,
            hiddenStats: entry.hiddenStats,
            statOrder: entry.statOrder,
            size: entry.size,
            settings: entry.settings,
          }
        : null;
    })
    .filter((b): b is ResolvedBlock => b !== null);
  const resolvedRef = useRef(resolved);
  resolvedRef.current = resolved;

  // Extra (non-block) stored entries: anything whose key is not a
  // currently-registered block def — pseudo-entries like Home's
  // "panel". They ride through load/save untouched except where
  // updateExtra patches them during an edit session.
  const defKeySet = new Set(defsKey ? defsKey.split(",") : []);
  const storedExtras: StoredBlockEntry[] = (stored ?? []).filter(
    (e) => !defKeySet.has(e.key),
  );
  const extrasRef = useRef(storedExtras);
  extrasRef.current = extraDraft ?? storedExtras;

  const beginEdit = useCallback(() => {
    if (!loadedRef.current) {
      // The saved layout hasn't landed yet: queue the edit —
      // the load's settle path snapshots the FRESH layout.
      // Snapshotting now would draft the pre-load defaults.
      pendingEditRef.current = true;
      return;
    }
    setDraft(resolvedRef.current.map(cloneBlockForDraft));
    setExtraDraft(extrasRef.current.map((e) => ({ ...e })));
  }, []);

  const cancelEdit = useCallback(() => {
    pendingEditRef.current = false;
    draftFromErrorRef.current = false;
    setDraft(null);
    setExtraDraft(null);
  }, []);

  const updateExtra = useCallback(
    (key: string, patch: Partial<StoredBlockEntry>) => {
      setExtraDraft((prev) => {
        const base = prev ?? extrasRef.current;
        const existing = base.find((e) => e.key === key);
        if (!existing) {
          return [...base, { key, visible: true, ...patch }];
        }
        return base.map((e) => (e.key === key ? { ...e, ...patch } : e));
      });
    },
    [],
  );

  const toggleBlock = useCallback((key: string) => {
    setDraft((d) =>
      d ? d.map((b) => (b.key === key ? { ...b, visible: !b.visible } : b)) : d,
    );
  }, []);

  const setBlockVisible = useCallback((key: string, visible: boolean) => {
    setDraft((d) =>
      d ? d.map((b) => (b.key === key ? { ...b, visible } : b)) : d,
    );
  }, []);

  const reorderBlocks = useCallback((keys: string[]) => {
    setDraft((d) => {
      if (!d) return d;
      const byKey = new Map(d.map((b) => [b.key, b]));
      const next: ResolvedBlock[] = [];
      for (const k of keys) {
        const b = byKey.get(k);
        if (b) {
          next.push(b);
          byKey.delete(k);
        }
      }
      for (const b of byKey.values()) next.push(b);
      return next;
    });
  }, []);

  const toggleStat = useCallback((blockKey: string, statKey: string) => {
    setDraft((d) =>
      d
        ? d.map((b) =>
            b.key === blockKey
              ? {
                  ...b,
                  hiddenStats: b.hiddenStats.includes(statKey)
                    ? b.hiddenStats.filter((k) => k !== statKey)
                    : [...b.hiddenStats, statKey],
                }
              : b,
          )
        : d,
    );
  }, []);

  const setStatOrder = useCallback((blockKey: string, statKeys: string[]) => {
    setDraft((d) =>
      d
        ? d.map((b) => (b.key === blockKey ? { ...b, statOrder: statKeys } : b))
        : d,
    );
  }, []);

  const setBlockSize = useCallback((key: string, size: BlockSize) => {
    setDraft((d) =>
      d ? d.map((b) => (b.key === key ? { ...b, size } : b)) : d,
    );
  }, []);

  const setBlockSetting = useCallback(
    (key: string, name: string, value: BlockSettingValue | undefined) => {
      setDraft((d) =>
        d
          ? d.map((b) => {
              if (b.key !== key) return b;
              const settings = { ...b.settings };
              if (value === undefined) delete settings[name];
              else settings[name] = value;
              return { ...b, settings };
            })
          : d,
      );
    },
    [],
  );

  const saveEdit = useCallback(async (): Promise<boolean> => {
    if (!draft) return false;
    setSaving(true);
    try {
      const blockEntries: StoredBlockEntry[] = draft.map(
        ({ key, visible, hiddenStats, statOrder, size, settings, defaultSize }) => {
          const entry: StoredBlockEntry = { key, visible };
          if (hiddenStats.length > 0) entry.hidden_stats = hiddenStats;
          if (statOrder.length > 0) entry.order = statOrder;
          // Framework extras (widget options Wave 1): the width
          // rides only when it differs from the block's
          // registered default — resetting to the default drops
          // the field, and the store's wholesale replace makes
          // that the saved state. Settings ride only when the
          // bundle is non-empty (absence = no options set).
          if (size !== (defaultSize ?? "full")) entry.size = size;
          if (settings && Object.keys(settings).length > 0) {
            entry.settings = settings;
          }
          return entry;
        },
      );
      // Extras ride along with the blocks; any extra whose key
      // collides with a real block is dropped so the payload never
      // carries a key twice.
      const extraEntries = (extraDraft ?? storedExtras)
        .filter((e) => !draft.some((b) => b.key === e.key))
        .map((e) => {
          const entry: StoredBlockEntry = { key: e.key, visible: e.visible };
          if (e.hidden_stats && e.hidden_stats.length > 0) entry.hidden_stats = e.hidden_stats;
          if (e.order && e.order.length > 0) entry.order = e.order;
          if (e.panel_hidden && e.panel_hidden.length > 0) entry.panel_hidden = e.panel_hidden;
          if (e.panel_order && e.panel_order.length > 0) entry.panel_order = e.panel_order;
          if (e.panel_stat_order !== undefined) entry.panel_stat_order = e.panel_stat_order;
          // Framework extras ride through too (widget options
          // Wave 1): an entry sitting in the extras because its
          // module is temporarily off must keep its width and
          // options bundle, or this save would silently strip
          // the customization for when the module returns.
          if (e.size === "half" || e.size === "full") entry.size = e.size;
          const extraSettings = sanitizeBlockSettings(e.settings);
          if (Object.keys(extraSettings).length > 0) {
            entry.settings = extraSettings;
          }
          return entry;
        });
      // ORDER PRESERVATION (per-user module switches, 2026-10-24):
      // the saved list walks the PREVIOUS stored order first,
      // substituting each stored entry's draft version (block or
      // extra) in its original slot; draft entries whose keys never
      // appeared in stored append after, in draft order. A block
      // whose module is temporarily absent (turned off → its def
      // isn't built → its stored entry rides as an "extra") thus
      // returns to its original slot when the module comes back,
      // instead of being re-appended at the end by this save.
      const draftByKey = new Map<string, StoredBlockEntry>();
      for (const e of blockEntries) draftByKey.set(e.key, e);
      for (const e of extraEntries) {
        if (!draftByKey.has(e.key)) draftByKey.set(e.key, e);
      }
      const entries: StoredBlockEntry[] = [];
      const placed = new Set<string>();
      for (const s of stored ?? []) {
        const sub = draftByKey.get(s.key);
        if (sub && !placed.has(s.key)) {
          entries.push(sub);
          placed.add(s.key);
        }
      }
      for (const e of [...blockEntries, ...extraEntries]) {
        if (!placed.has(e.key)) {
          entries.push(e);
          placed.add(e.key);
        }
      }
      const data = await api<StoredLayoutResponse>(`/core/layouts/${pageKey}`, {
        method: "PUT",
        body: JSON.stringify({ blocks: entries }),
      });
      setStored(Array.isArray(data?.blocks) ? data.blocks : entries);
      draftFromErrorRef.current = false;
      setDraft(null);
      setExtraDraft(null);
      return true;
    } catch {
      return false;
    } finally {
      setSaving(false);
    }
    // storedExtras is derived from `stored` + def keys each render;
    // the extrasRef above is the live source, so it is not a dep.
    // `stored` itself IS a dep: the order-preservation walk reads
    // the previous stored list directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, pageKey, extraDraft, stored]);

  return {
    blocks: draft ?? resolved,
    loaded,
    loadError,
    retryLoad,
    extras: extraDraft ?? storedExtras,
    updateExtra,
    editing: draft !== null,
    saving,
    beginEdit,
    cancelEdit,
    saveEdit,
    toggleBlock,
    setBlockVisible,
    reorderBlocks,
    toggleStat,
    setStatOrder,
    setBlockSize,
    setBlockSetting,
  };
}
