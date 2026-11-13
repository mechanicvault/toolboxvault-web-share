import { useEffect, useState, type ReactNode } from "react";
import { DICTIONARIES, type DictKey } from "../i18n/dictionaries";
import { useLocale } from "../i18n/LocaleContext";

import { api } from "../lib/api";
import { formatMoney as formatMoneyLib } from "../lib/money";
import type { AccountType } from "../modules/core/accountTypes";
import { ArtIcon } from "./ArtIcon";
import { BrandIcon } from "./BrandIcon";
import { Panel } from "./Panel";
import { SectionHeader } from "./SectionHeader";
import { StatCard } from "./StatCard";

/** Shape of GET /api/inventory/stats (semantics: backend schemas.InventoryStats).
 *  Money arrives as decimal strings, exactly like tool cost fields. */
export interface InventoryStats {
  total_items: number;
  /** SUM of quantity over the population total_items counts
   *  (top-level tools + batteries) — the physical unit count
   *  beside the item count (2026-11-10). */
  total_quantity: number;
  /** SUM of msrp (today's list price); unset tools contribute 0. */
  total_market_value: string;
  /** The REPORTS-basis value (deep audit F1-03): SUM of
   *  purchase_price x quantity + priced set addon pieces — the
   *  grand "Total value" the Reports page prints. The Home stat
   *  of the same name reads THIS, never the msrp sum: owners
   *  record what they paid, so the msrp sum read $0 on real
   *  vaults while Reports totalled them for real. */
  total_value: string;
  /** SUM of replacement_cost; unset tools contribute 0. */
  total_replacement_cost: string;
  /** Distinct non-empty categories. */
  category_count: number;
  /** Assets whose computed warranty ends today or within 30 days. */
  warranties_expiring_soon: number;
  /** Assets whose computed warranty has already ended. */
  warranties_expired: number;
}

/**
 * One registered stat. CONFIG-REGISTRATION: the overview row renders
 * exactly this array, so a future module adds its stat by appending
 * an entry (calibration → "Maintenance due", dealers → "Dealer
 * accounts", wanted board → "Wishlist") — no restructuring of the
 * row, the grid, or the page. `groups` declares which account
 * groups the stat serves: it shows when ANY of the signed-in
 * user's groups is in the list (groups are multi-select, so
 * visibility is a union; duplicates by `key` are rendered once).
 *
 * Two value sources: `value` selects and formats out of the shared
 * inventory-stats payload (the original four), or `load` fetches
 * the stat from its OWN module's stats endpoint — the pattern for
 * every module that owns a number (borrowing's Checked Out was the
 * first, 2026-10-18). A stat declares exactly one of the two.
 */
/** Icon ink for a stat tile (Home + Header program, owner
 *  2026-10-24: "not all orange" — the icon colors vary on
 *  purpose, tastefully). Every tone is a token in the theme
 *  layer; the accent hero tile keeps the accent plate instead. */
export type StatTone =
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "violet"
  | "teal"
  | "slate";

export interface StatDefinition {
  /** Stable id: "<module>.<field>". */
  key: string;
  /** The feature module that owns this stat (module doctrine,
   *  owner 2026-10-18). The stat renders only while its module is
   *  effective for the user — see the `enabledModules` prop. */
  module: string;
  label: string;
  icon: ReactNode;
  tone?: StatTone;
  groups: AccountType[];
  value?: (stats: InventoryStats) => string;
  load?: () => Promise<string>;
  /** Rail Steel Phase 2c: render as the row's ONE accent hero
   *  tile (accent plate). Exactly one definition carries it —
   *  the maintenance-due stat, the preview hero's counterpart
   *  ("Next maintenance due"). Visibility/order are untouched:
   *  the flag only changes the tile's skin when it renders. */
  accent?: boolean;
  /** Owner 2026-11-03: an optional condition on the accent skin,
   *  read against the card's current display value. The hero
   *  treatment is an alarm, and an alarm over a zero count cries
   *  wolf — so the maintenance-due tile wears the accent plate
   *  ONLY while its count is positive, and renders as a normal
   *  tile (icon chip and all) at zero. The loading em dash parses
   *  to no count, so a still-loading tile renders plain and skins
   *  up only on a real positive number. Absent = the static
   *  `accent` flag decides alone. */
  accentWhen?: (valueText: string) => boolean;
  /** F5-01: the card's natural destination. */
  href?: string;
}

const formatCount = (n: number): string => n.toLocaleString("en-US");

/** Stat-card money: whole units, the viewer's currency (wave 3 —
 *  the one formatter, lib/money). */
const formatMoney = (decimal: string): string => formatMoneyLib(decimal, null, true);

/** The stats that exist TODAY. No placeholder cards for unbuilt
 *  modules; they register here when they ship. */
export const OVERVIEW_STATS: StatDefinition[] = [
  {
    key: "inventory.total_items",
    href: "/inventory",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Total items",
    tone: "slate",
    icon: <ArtIcon name="inventory" size={24} />,
    value: (s) => formatCount(s.total_items),
  },
  {
    key: "inventory.total_market_value",
    href: "/reports",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Total value",
    tone: "success",
    icon: <ArtIcon name="money" size={24} />,
    value: (s) => formatMoney(s.total_value),
  },
  {
    key: "inventory.total_replacement_cost",
    href: "/reports",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Replacement cost",
    tone: "info",
    icon: <ArtIcon name="tag" size={24} />,
    value: (s) => formatMoney(s.total_replacement_cost),
  },
  {
    // Warranty counters (audit A6): computed by the backend with
    // the same warranty_status_of the item pages show — expiring
    // within 30 days, and already expired. Tools + batteries.
    key: "inventory.warranties_expiring_soon",
    href: "/inventory?warranty=due&sort=warranty_end",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Warranties expiring",
    tone: "warning",
    icon: <ArtIcon name="warning" size={24} />,
    value: (s) => formatCount(s.warranties_expiring_soon),
  },
  {
    key: "inventory.warranties_expired",
    href: "/inventory?warranty=due&sort=warranty_end",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Warranties expired",
    tone: "danger",
    icon: <ArtIcon name="warning" size={24} />,
    value: (s) => formatCount(s.warranties_expired),
  },
  {
    key: "inventory.category_count",
    href: "/inventory",
    module: "inventory",
    groups: ["mechanic_technician"],
    label: "Categories",
    tone: "violet",
    icon: <ArtIcon name="categories" size={24} />,
    value: (s) => formatCount(s.category_count),
  },
  {
    // The borrowing module's stat (2026-10-18): how many of MY
    // items are checked out right now, from the module's own
    // stats endpoint. Mechanic + shop — borrowing's groups.
    key: "borrowing.checked_out",
    href: "/borrowing",
    module: "borrowing",
    groups: ["mechanic_technician", "shop_company"],
    label: "Checked out",
    tone: "teal",
    icon: <ArtIcon name="borrowing" size={24} />,
    load: async () => {
      const s = await api<{ checked_out_count: number }>("/borrowing/stats");
      return formatCount(s.checked_out_count);
    },
  },
  {
    // The maintenance module's stats (2026-10-19): schedules due
    // within a week (or overdue), and items currently out of
    // service — the owner's long-standing example stats. Both read
    // the module's one stats endpoint; mechanic + shop.
    key: "maintenance.maintenance_due",
    href: "/repairs#tool-maintenance",
    accent: true,
    // The hero skin is earned, not permanent (owner 2026-11-03):
    // it lands only while the count is positive. At zero the card
    // is a normal tile wearing the maintenance module's own icon
    // + tone — the RefreshIcon / warning pair its Home widget
    // carries — in the chip the accent skin hides.
    accentWhen: (text) => {
      const n = Number.parseInt(text.replace(/[^0-9]/g, ""), 10);
      return Number.isFinite(n) && n > 0;
    },
    module: "maintenance",
    groups: ["mechanic_technician", "shop_company"],
    label: "Maintenance due",
    tone: "warning",
    icon: <ArtIcon name="repairs" size={24} />,
    load: async () => {
      const s = await api<{ maintenance_due_count: number }>("/maintenance/stats");
      return formatCount(s.maintenance_due_count);
    },
  },
  {
    key: "maintenance.out_of_service",
    href: "/repairs#out-of-service",
    module: "maintenance",
    groups: ["mechanic_technician", "shop_company"],
    label: "Out of service",
    tone: "danger",
    icon: <ArtIcon name="warning" size={24} />,
    load: async () => {
      const s = await api<{ out_of_service_count: number }>("/maintenance/stats");
      return formatCount(s.out_of_service_count);
    },
  },
  {
    // The claims module's stat (2026-10-19): claims still in
    // flight for the owner — drafts included (deep audit F1-23:
    // the Claims page lists drafts as live work, so a count that
    // excluded them read 0 mid-claim); settled claims don't
    // count. Mechanic + shop, module-gated.
    key: "claims.open_claims",
    href: "/repairs#repair-claims",
    module: "claims",
    groups: ["mechanic_technician", "shop_company"],
    label: "Repair claims",
    tone: "violet",
    icon: <ArtIcon name="claims" size={24} />,
    load: async () => {
      const s = await api<{ open_claims_count: number }>("/claims/stats");
      return formatCount(s.open_claims_count);
    },
  },
  {
    // The dealer portal's stats (2026-10-19): dealer-group users
    // get their agent-side numbers. "Preferred by" is an AGGREGATE
    // COUNT ONLY — the backend never returns who prefers an agent.
    key: "dealers.preferred_by",
    module: "dealers",
    groups: ["tool_dealer"],
    label: "Preferred by",
    tone: "info",
    icon: <ArtIcon name="people" size={24} />,
    load: async () => {
      const s = await api<{ preferred_by_count: number }>("/dealers/stats");
      return formatCount(s.preferred_by_count);
    },
  },
  {
    key: "dealers.companies_represented",
    module: "dealers",
    groups: ["tool_dealer"],
    label: "Companies represented",
    tone: "teal",
    icon: <ArtIcon name="dealers" size={24} />,
    load: async () => {
      const s = await api<{ companies_represented_count: number }>("/dealers/stats");
      return formatCount(s.companies_represented_count);
    },
  },
  {
    key: "dealers.profile_visibility",
    module: "dealers",
    groups: ["tool_dealer"],
    label: "Profile",
    tone: "slate",
    icon: <ArtIcon name="people" size={24} />,
    load: async () => {
      const s = await api<{ profile_visibility: string }>("/dealers/stats");
      return s.profile_visibility;
    },
  },
  {
    // Used Parts (2026-10-19): how many distinct spares sit on the
    // shelf. Parts never count toward the entitlement item cap —
    // this stat is the shelf's own number.
    key: "parts.used_parts",
    href: "/parts",
    module: "parts",
    groups: ["mechanic_technician", "shop_company"],
    label: "My parts",
    tone: "success",
    icon: <ArtIcon name="parts" size={24} />,
    load: async () => {
      const s = await api<{ parts_count: number }>("/parts/stats");
      return formatCount(s.parts_count);
    },
  },
  {
    // Unread messages + open tickets (owner spec 2026-10-25):
    // the Home panel's two rows, now also able to show as
    // Overview block cards. SAME definitions as the panel —
    // the messaging module's own unread count and the support
    // module's own not-closed count, read from the same
    // endpoints, under the same stat.* labels. Both modules
    // serve all four groups (the panel offers both rows to
    // ALL_GROUPS); support is always-on core, messaging hides
    // with its module switch — the registry's module gate does
    // both. Deliberately NO href: the panel rows carry the
    // links (owner's Phase-2 pass); block cards for these two
    // were not part of it.
    key: "messaging.unread",
    module: "messaging",
    groups: [
      "mechanic_technician",
      "shop_company",
      "tool_dealer",
      "insurance",
    ],
    label: "Unread messages",
    tone: "info",
    icon: <ArtIcon name="messages" size={24} />,
    load: async () => {
      const s = await api<{ inbox_unread: number }>("/messaging/unread");
      return formatCount(s.inbox_unread);
    },
  },
  {
    key: "support.open_tickets",
    module: "support",
    groups: [
      "mechanic_technician",
      "shop_company",
      "tool_dealer",
      "insurance",
    ],
    label: "Open tickets",
    tone: "warning",
    icon: <ArtIcon name="support" size={24} />,
    load: async () => {
      const s = await api<{ open_tickets_count: number }>("/support/stats");
      return formatCount(s.open_tickets_count);
    },
  },
];

export interface OverviewRowProps {
  title?: string;
  /**
   * Whether the section header (title + rule) renders. Home
   * passes false (Home + Header program, owner 2026-10-24: the
   * "Shop overview" heading AND its rule disappear entirely);
   * the title still names the section for assistive tech.
   */
  heading?: boolean;
  /** Defaults to OVERVIEW_STATS; override only to register more stats. */
  definitions?: StatDefinition[];
  /**
   * The user's stat display order (stat keys, Home + Header
   * program): keys listed here lead, in this order; the rest
   * follow in registry order. Rides the overview block's layout
   * entry (`order` extra) and is edited by dragging in customize
   * mode.
   */
  statOrder?: readonly string[];
  /**
   * Customize mode (Home + Header program; Phase C 2026-10-24):
   * cards stop being links and wear the arrange chrome — a red X
   * to remove the box and drag-to-rearrange. Drag is the only
   * reorder path (the old up/down arrow buttons are removed,
   * owner's order). The callbacks write the home layout draft.
   */
  editing?: boolean;
  onRemoveStat?: (statKey: string) => void;
  onReorderStats?: (statKeys: string[]) => void;
  /**
   * The signed-in user's group set. Stats render when ANY of the
   * user's groups is in the stat's `groups` (union — groups are
   * multi-select). Omit only outside the signed-in app (style guide),
   * where every registered stat shows.
   */
  accountTypes?: AccountType[];
  /**
   * The user's effective feature modules (module doctrine): a stat
   * renders only when its owning module is in this set. Pass the
   * set from /core/my-modules once loaded. Omit ONLY outside the
   * signed-in app (style guide), where module gating doesn't apply
   * and every registered stat shows.
   */
  enabledModules?: ReadonlySet<string>;
  /**
   * Stat keys the user hid (owner review round 1, 2026-10-19):
   * applied AFTER the group + module gates — a hidden stat simply
   * doesn't render, and its loader never fires. Stored in the home
   * page layout (the overview block's entry), edited from home's
   * Customize view and Settings → Page customization alike.
   */
  hiddenStats?: readonly string[];
  /**
   * The new Home stats widget's glow mode (design 2026-11-10,
   * §3.8): every card that is a door glows softly in the
   * viewer's accent color, and a warning/danger card holding a
   * real count glows warmer (data-alert). Only the stats
   * widget's seat (HomeShell) turns this on — every other
   * OverviewRow consumer renders exactly as before.
   */
  glow?: boolean;
}

/** Honest "nothing here yet" lines for groups whose stats don't exist
 *  yet — no fake numbers, ever. One line per such group in the set. */
const PENDING_GROUP_LINES: Partial<Record<AccountType, string>> = {
  shop_company:
    "Your shop overview — checked-out tools, employees, and shop activity — will appear here as the shop modules ship.",
  tool_dealer:
    "Your dealer profile, companies represented, and how many users prefer you will appear here while the Dealers module is enabled for your account. Truck accounts and balances arrive with dealer portal stage 2.",
  insurance:
    "The claims you handle will appear here when the insurance portal ships.",
};

/**
 * "SHOP OVERVIEW" — section header + the registered stat plates for
 * the signed-in user's groups. Fetches the owner's vault stats; while
 * loading (or if the fetch fails) the cards hold an em dash so the
 * row is always composed. An empty vault shows real zeros from the
 * endpoint. A user whose groups have no stats yet (dealer, insurance)
 * gets an honest empty state instead of invented numbers.
 */
export function OverviewRow({
  title,
  heading = true,
  definitions = OVERVIEW_STATS,
  accountTypes,
  enabledModules,
  hiddenStats,
  statOrder,
  editing = false,
  onRemoveStat,
  onReorderStats,
  glow = false,
}: OverviewRowProps) {
  const { locale, t } = useLocale();
  const sectionTitle = title ?? t("home.shopOverview");
  const header = heading ? <SectionHeader title={sectionTitle} /> : null;
  const statLabel = (def: StatDefinition): string =>
    (DICTIONARIES[locale] as Record<string, string>)[
      `stat.${def.key}` as DictKey
    ] ?? def.label;
  const [stats, setStats] = useState<InventoryStats | null>(null);
  /** Display strings for `load`-sourced stats, by stat key. */
  const [loaded, setLoaded] = useState<Record<string, string>>({});

  // Union visibility + dedupe by key (first registration wins).
  const seen = new Set<string>();
  const gated = definitions.filter((def) => {
    if (seen.has(def.key)) return false;
    seen.add(def.key);
    return (
      (accountTypes === undefined ||
        def.groups.some((g) => accountTypes.includes(g))) &&
      (enabledModules === undefined || enabledModules.has(def.module))
    );
  });
  // The user's own show/hide choices apply last.
  const visible = gated.filter(
    (def) => !(hiddenStats ?? []).includes(def.key),
  );
  // Then the user's drag order (Home + Header program): saved
  // keys lead in saved order; anything new keeps registry order
  // behind them.
  const orderPos = new Map((statOrder ?? []).map((k, i) => [k, i] as const));
  const orderedVisible = visible
    .map((def, i) => ({ def, i }))
    .sort((a, b) => {
      const pa = orderPos.get(a.def.key) ?? Number.MAX_SAFE_INTEGER;
      const pb = orderPos.get(b.def.key) ?? Number.MAX_SAFE_INTEGER;
      return pa - pb || a.i - b.i;
    })
    .map(({ def }) => def);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const dropOn = (targetKey: string) => {
    if (!dragKey || dragKey === targetKey) return;
    const keys = orderedVisible.map((d) => d.key);
    const from = keys.indexOf(dragKey);
    const to = keys.indexOf(targetKey);
    if (from < 0 || to < 0) return;
    keys.splice(from, 1);
    keys.splice(to, 0, dragKey);
    onReorderStats?.(keys);
    setDragKey(null);
  };

  useEffect(() => {
    if (orderedVisible.length === 0) return;
    let live = true;
    // The shared inventory payload — fetched only when a visible
    // stat reads from it (a shop user with just the borrowing stat
    // never triggers an inventory call they can't use).
    if (orderedVisible.some((d) => d.value)) {
      api<InventoryStats>("/inventory/stats")
        .then((data) => {
          if (live) setStats(data);
        })
        .catch(() => {
          /* keep the composed em-dash state */
        });
    }
    // Each load-sourced stat fetches its own module's endpoint; a
    // failure leaves that one card on the em dash.
    for (const def of orderedVisible) {
      if (!def.load) continue;
      def
        .load()
        .then((text) => {
          if (live) setLoaded((m) => ({ ...m, [def.key]: text }));
        })
        .catch(() => {
          /* keep the composed em-dash state */
        });
    }
    return () => {
      live = false;
    };
    // Re-run only when the visible key set changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderedVisible.map((d) => d.key).join(",")]);

  if (visible.length === 0 && gated.length > 0) {
    // Stats exist for this user and every one is hidden BY CHOICE:
    // say so (and where to undo it) instead of the "not shipped
    // yet" lines below, which would be a lie. In customize mode
    // the ADD control (rendered by the page) is the undo — the
    // section just holds its (empty) ground.
    if (editing) {
      return (
        <section aria-label={sectionTitle}>
          {header}
          <div className="tv-overview-grid" />
        </section>
      );
    }
    return (
      <section aria-label={sectionTitle}>
        {header}
        <Panel>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("home.stats.allHidden")}
          </p>
        </Panel>
      </section>
    );
  }

  if (visible.length === 0) {
    const lines = (accountTypes ?? [])
      .map((t) => PENDING_GROUP_LINES[t])
      .filter((line): line is string => Boolean(line));
    return (
      <section aria-label={sectionTitle}>
        {header}
        <Panel>
          <div style={{ display: "grid", gap: "var(--space-2)", justifyItems: "start" }}>
            <BrandIcon name="chart-up" size={44} />
            {(lines.length > 0
              ? lines
              : ["Your overview stats will appear here as modules for your groups ship."]
            ).map((line) => (
              <p key={line} style={{ color: "var(--text-muted)", margin: 0 }}>
                {line}
              </p>
            ))}
          </div>
        </Panel>
      </section>
    );
  }

  const cardValue = (def: StatDefinition): string =>
    def.load
      ? (loaded[def.key] ?? "—")
      : stats && def.value
        ? def.value(stats)
        : "—";

  /** Whether THIS render of the card wears the accent hero skin:
   *  the static flag, gated by the definition's value condition
   *  when it declares one (maintenance due: count > 0 only). */
  const cardAccent = (def: StatDefinition): boolean =>
    Boolean(def.accent) &&
    (def.accentWhen === undefined || def.accentWhen(cardValue(def)));

  /** Glow mode's warm state (§3.8): a warning/danger fact with a
   *  real count on it wants eyes — the loading em dash parses to
   *  no count, so a still-loading card stays at the resting glow
   *  and warms up only on a real positive number. */
  const cardAlert = (def: StatDefinition): boolean => {
    if (!glow || (def.tone !== "warning" && def.tone !== "danger")) {
      return false;
    }
    const n = Number.parseInt(cardValue(def).replace(/[^0-9]/g, ""), 10);
    return Number.isFinite(n) && n > 0;
  };

  return (
    <section aria-label={sectionTitle}>
      {header}
      <div className={`tv-overview-grid${glow ? " tv-overview-grid--glow" : ""}`}>
        {orderedVisible.map((def) =>
          editing ? (
            <div
              key={def.key}
              className="tv-stat-slot"
              data-dragging={dragKey === def.key || undefined}
              draggable
              onDragStart={(e) => {
                setDragKey(def.key);
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                dropOn(def.key);
              }}
              onDragEnd={() => setDragKey(null)}
            >
              <StatCard
                accent={cardAccent(def)}
                tone={def.tone}
                label={statLabel(def)}
                icon={def.icon}
                value={cardValue(def)}
              />
              <span className="tv-box-tools">
                <button
                  type="button"
                  className="tv-box-x"
                  aria-label={`${t("home.remove")}: ${statLabel(def)}`}
                  title={t("home.remove")}
                  onClick={() => onRemoveStat?.(def.key)}
                >
                  −
                </button>
              </span>
            </div>
          ) : (
            <StatCard
              key={def.key}
              href={def.href}
              accent={cardAccent(def)}
              tone={def.tone}
              label={statLabel(def)}
              icon={def.icon}
              value={cardValue(def)}
              alert={cardAlert(def)}
            />
          ),
        )}
      </div>
    </section>
  );
}
