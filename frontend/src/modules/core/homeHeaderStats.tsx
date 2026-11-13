import { useEffect, useRef, useState } from "react";

import { OVERVIEW_STATS, type InventoryStats } from "../../components/OverviewRow";
import { SectionPageFactItem } from "../../components/SectionPageHeader";
import { api } from "../../lib/api";
import { formatMoney } from "../../lib/money";
import { getDealerListSettings, listCompanies, listPrivateAgents } from "../dealers/api";
import { getMine } from "../feedback/api";
import { flyerFeed } from "../flyers/api";
import { browsePrints, getMyPrints } from "../prints/api";
import { getStatusSummary } from "../truck-accounts/api";

/**
 * THE HOME HEADER-STATS CATALOG (dashboard Lane 3, owner design
 * 2026-11-10): the stats widget's content, moved into the Home
 * header. This table mirrors the SERVER catalog
 * (backend/app/modules/core/header_stats.py) key for key — the
 * server enumerates which keys a caller may pick from THEIR
 * effective reach (GET /api/core/header-stats), and a key the
 * server does not return is never rendered or offered here,
 * whatever this table says. This file owns only presentation:
 * the label (dict `stat.<key>`, English fallback here), the
 * door, and the value read — every read is the owning module's
 * own endpoint, the same read its pages use, so a header number
 * can never disagree with the module's own page.
 *
 * The first block of definitions is ADAPTED from the retired
 * overview registry (OVERVIEW_STATS): the same loads, the same
 * doors, the same warning/danger tones (a warning/danger stat
 * with a positive count glows warmer — Lane 1's rule). Three
 * seed stats gain the door the widget cards deliberately lacked
 * (support tickets → Help & Support, the dealer portal counts →
 * the Dealers page); unread messages keeps none (its module is
 * parked, and the panel rows carry its link when it returns).
 */

export const HEADER_STATS_KEY = "header_stats";
export const HEADER_STATS_PER_ROW = 6;
export const HEADER_STATS_MAX = 12;

export interface HeaderStatContext {
  /** Server-computed values (staff stats with no module read). */
  serverValues: Record<string, number>;
  /** Per-mount memo so stats sharing one endpoint read it once. */
  once: <T>(key: string, fn: () => Promise<T>) => Promise<T>;
}

export interface HeaderStatDef {
  key: string;
  /** Picker grouping id (a module id, or "downloads" / "account" / "admin"). */
  module: string;
  label: string;
  href?: string;
  /** Warning/danger family: the glow burns warmer while positive. */
  alertTone?: boolean;
  load: (ctx: HeaderStatContext) => Promise<string>;
}

const count = (n: number): string => n.toLocaleString("en-US");
const money = (decimal: string): string => formatMoney(decimal, null, true);

const inventoryStats = (ctx: HeaderStatContext): Promise<InventoryStats> =>
  ctx.once("inventory-stats", () => api<InventoryStats>("/inventory/stats"));

/** The seed definitions, adapted — same loads, same doors. */
const seedDefs: HeaderStatDef[] = OVERVIEW_STATS.map((def) => ({
  key: def.key,
  module: def.module,
  label: def.label,
  href:
    def.href ??
    (def.key === "support.open_tickets"
      ? "/help"
      : def.module === "dealers"
        ? "/dealers"
        : undefined),
  alertTone: def.tone === "warning" || def.tone === "danger",
  load: def.load
    ? () => def.load!()
    : async (ctx) => def.value!(await inventoryStats(ctx)),
}));

interface DownloadsCatalog {
  files: { download_count: number }[];
}
interface DownloadsWallpapers {
  wallpapers: { download_count: number }[];
}
const downloadsCatalog = (ctx: HeaderStatContext) =>
  ctx.once("downloads-catalog", () =>
    api<DownloadsCatalog>("/downloads/catalog"),
  );
const downloadsWallpapers = (ctx: HeaderStatContext) =>
  ctx.once("downloads-wallpapers", () =>
    api<DownloadsWallpapers>("/downloads/wallpapers"),
  );
const myPrintFiles = (ctx: HeaderStatContext) =>
  ctx.once("prints-mine", () => getMyPrints());
const liveMine = async (ctx: HeaderStatContext) =>
  (await myPrintFiles(ctx)).files.filter((f) => f.status === "live");

interface AdminHomeWidgets {
  site: {
    users_total: number;
    new_paid: number;
    paying_users: number;
    mrr: string;
    tools_total: number;
    tools_logged: number;
  };
  tickets: { open: number };
}
const adminWidgets = (ctx: HeaderStatContext) =>
  ctx.once("admin-home-widgets", () =>
    api<AdminHomeWidgets>("/admin/home-widgets"),
  );

const newDefs: HeaderStatDef[] = [
  {
    key: "inventory.total_quantity",
    module: "inventory",
    label: "Total quantity",
    href: "/inventory",
    load: async (ctx) => count((await inventoryStats(ctx)).total_quantity),
  },
  {
    key: "borrowing.borrowed_by_me",
    module: "borrowing",
    label: "Borrowed by me",
    href: "/borrowing",
    load: async (ctx) =>
      count(
        (await ctx.once("borrowing-stats", () =>
          api<{ borrowed_by_me_count: number }>("/borrowing/stats"),
        )).borrowed_by_me_count,
      ),
  },
  {
    key: "disaster_claims.open_claims",
    module: "disaster_claims",
    label: "Open disaster claims",
    href: "/disaster-claims",
    load: async () =>
      count(
        (await api<{ open_claims_count: number }>("/disaster-claims/stats"))
          .open_claims_count,
      ),
  },
  {
    // The truck module's own status-summary reading, exactly as
    // the Dealers header facts state it: open accounts are the
    // two sides' counts together; total owed is the customer
    // side, or the dealer side when the viewer holds no
    // customer-side accounts — the two sides are never summed.
    key: "truck_accounts.open_accounts",
    module: "truck_accounts",
    label: "Truck accounts",
    href: "/truck-accounts",
    load: async (ctx) => {
      const s = await ctx.once("truck-summary", () => getStatusSummary());
      return count(s.customer_open_accounts + s.dealer_open_accounts);
    },
  },
  {
    key: "truck_accounts.total_owed",
    module: "truck_accounts",
    label: "Total owed",
    href: "/truck-accounts",
    load: async (ctx) => {
      const s = await ctx.once("truck-summary", () => getStatusSummary());
      return money(
        s.customer_open_accounts > 0
          ? s.customer_total_balance
          : s.dealer_total_outstanding,
      );
    },
  },
  {
    key: "truck_accounts.payments_this_week",
    module: "truck_accounts",
    label: "Payments this week",
    href: "/truck-accounts",
    load: async (ctx) => {
      const s = await ctx.once("truck-summary", () => getStatusSummary());
      return money(s.payments_this_week);
    },
  },
  {
    // The Dealers page's own header facts, read the same way:
    // directory companies the viewer hasn't hidden, their own
    // companies, their unarchived agent records.
    key: "dealers.directory",
    module: "dealers",
    label: "Directory dealers",
    href: "/dealers",
    load: async (ctx) => {
      const [companies, settings] = await Promise.all([
        ctx.once("dealers-companies", () => listCompanies()),
        ctx.once("dealers-list-settings", () => getDealerListSettings()),
      ]);
      const hidden = new Set(
        settings.directory.filter((r) => r.hidden).map((r) => r.company.id),
      );
      return count(
        companies.filter((c) => c.is_directory && !hidden.has(c.id)).length,
      );
    },
  },
  {
    key: "dealers.my_companies",
    module: "dealers",
    label: "My companies",
    href: "/dealers",
    load: async (ctx) => {
      const companies = await ctx.once("dealers-companies", () =>
        listCompanies(),
      );
      return count(companies.filter((c) => !c.is_directory).length);
    },
  },
  {
    key: "dealers.my_agents",
    module: "dealers",
    label: "My agents",
    href: "/dealers",
    load: async (ctx) => {
      const agents = await ctx.once("dealers-agents", () =>
        listPrivateAgents(),
      );
      return count(agents.filter((a) => !a.archived).length);
    },
  },
  {
    key: "flyers.this_week",
    module: "flyers",
    label: "Flyers up this week",
    href: "/flyers",
    load: async () => count((await flyerFeed()).length),
  },
  {
    key: "feedback.my_posts",
    module: "feedback",
    label: "My feedback posts",
    href: "/feedback",
    load: async () => count((await getMine("")).length),
  },
  {
    key: "downloads.documents",
    module: "downloads",
    label: "Documents",
    href: "/downloads#documents",
    load: async (ctx) => count((await downloadsCatalog(ctx)).files.length),
  },
  {
    key: "downloads.wallpapers",
    module: "downloads",
    label: "Wallpapers",
    href: "/downloads#wallpapers",
    load: async (ctx) =>
      count((await downloadsWallpapers(ctx)).wallpapers.length),
  },
  {
    key: "downloads.total_downloads",
    module: "downloads",
    label: "Downloads",
    href: "/downloads",
    load: async (ctx) => {
      const [catalog, wallpapers] = await Promise.all([
        downloadsCatalog(ctx),
        downloadsWallpapers(ctx),
      ]);
      return count(
        catalog.files.reduce((sum, f) => sum + f.download_count, 0) +
          wallpapers.wallpapers.reduce((sum, w) => sum + w.download_count, 0),
      );
    },
  },
  {
    key: "prints.listings",
    module: "prints",
    label: "Print files",
    href: "/3dprints",
    load: async (ctx) =>
      count(
        (await ctx.once("prints-browse", () => browsePrints({}))).stats
          .listings,
      ),
  },
  {
    key: "prints.downloads",
    module: "prints",
    label: "Print file downloads",
    href: "/3dprints",
    load: async (ctx) =>
      count(
        (await ctx.once("prints-browse", () => browsePrints({}))).stats
          .downloads,
      ),
  },
  {
    key: "prints.my_uploads",
    module: "prints",
    label: "My uploads",
    href: "/3dprints#my",
    load: async (ctx) => count((await liveMine(ctx)).length),
  },
  {
    key: "prints.my_downloads",
    module: "prints",
    label: "Downloads of my files",
    href: "/3dprints#my",
    load: async (ctx) =>
      count((await liveMine(ctx)).reduce((sum, f) => sum + f.download_count, 0)),
  },
  {
    key: "account.plan_items",
    module: "account",
    label: "Plan items",
    href: "/settings/billing",
    load: async () =>
      count((await api<{ items_total: number }>("/billing/me")).items_total),
  },
  {
    key: "admin.members_total",
    module: "admin",
    label: "Members",
    href: "/admin",
    load: async (ctx) => count((await adminWidgets(ctx)).site.users_total),
  },
  {
    key: "admin.new_members_today",
    module: "admin",
    label: "New members today",
    href: "/admin",
    load: async (ctx) => count(ctx.serverValues["admin.new_members_today"] ?? 0),
  },
  {
    key: "admin.new_paid_today",
    module: "admin",
    label: "New paid today",
    href: "/admin",
    load: async (ctx) => count((await adminWidgets(ctx)).site.new_paid),
  },
  {
    key: "admin.paying_members",
    module: "admin",
    label: "Paying members",
    href: "/admin",
    load: async (ctx) => count((await adminWidgets(ctx)).site.paying_users),
  },
  {
    key: "admin.mrr",
    module: "admin",
    label: "Monthly recurring revenue",
    href: "/admin",
    load: async (ctx) => money((await adminWidgets(ctx)).site.mrr),
  },
  {
    key: "admin.tools_total",
    module: "admin",
    label: "Tools site-wide",
    href: "/admin",
    load: async (ctx) => count((await adminWidgets(ctx)).site.tools_total),
  },
  {
    key: "admin.tools_logged_today",
    module: "admin",
    label: "Tools logged today",
    href: "/admin",
    load: async (ctx) => count((await adminWidgets(ctx)).site.tools_logged),
  },
  {
    key: "admin.ai_actions_today",
    module: "admin",
    label: "AI actions today",
    href: "/admin",
    load: async (ctx) => count(ctx.serverValues["admin.ai_actions_today"] ?? 0),
  },
  {
    key: "admin.open_tickets",
    module: "admin",
    label: "Open tickets (site)",
    href: "/admin/support",
    load: async (ctx) => count((await adminWidgets(ctx)).tickets.open),
  },
];

/** The full catalog, in the server catalog's order (seed block
 *  first, harvested stats after — matching header_stats.py). */
export const HEADER_STAT_DEFS: HeaderStatDef[] = (() => {
  const byKey = new Map<string, HeaderStatDef>();
  for (const def of [...seedDefs, ...newDefs]) byKey.set(def.key, def);
  const order = [
    "inventory.total_items",
    "inventory.total_market_value",
    "inventory.total_quantity",
    "inventory.total_replacement_cost",
    "inventory.warranties_expiring_soon",
    "inventory.warranties_expired",
    "inventory.category_count",
    "borrowing.checked_out",
    "borrowing.borrowed_by_me",
    "claims.open_claims",
    "maintenance.maintenance_due",
    "maintenance.out_of_service",
    "disaster_claims.open_claims",
    "parts.used_parts",
    "truck_accounts.open_accounts",
    "truck_accounts.total_owed",
    "truck_accounts.payments_this_week",
    "dealers.directory",
    "dealers.my_companies",
    "dealers.my_agents",
    "dealers.preferred_by",
    "dealers.companies_represented",
    "dealers.profile_visibility",
    "flyers.this_week",
    "marketplace.active_listings",
    "wishlist.items",
    "messaging.unread",
    "support.open_tickets",
    "feedback.my_posts",
    "downloads.documents",
    "downloads.wallpapers",
    "downloads.total_downloads",
    "prints.listings",
    "prints.downloads",
    "prints.my_uploads",
    "prints.my_downloads",
    "account.plan_items",
    "admin.members_total",
    "admin.new_members_today",
    "admin.new_paid_today",
    "admin.paying_members",
    "admin.mrr",
    "admin.tools_total",
    "admin.tools_logged_today",
    "admin.ai_actions_today",
    "admin.open_tickets",
  ];
  return order
    .map((key) => byKey.get(key))
    .filter((d): d is HeaderStatDef => !!d);
})();

export const HEADER_STAT_BY_KEY = new Map(
  HEADER_STAT_DEFS.map((d) => [d.key, d]),
);

/** The default sets (design §6): the named six for full accounts,
 *  the rung's six for the downloads level — each reach-filtered
 *  against the server's available list, then filled from the
 *  catalog (in catalog order) when a seat's reach leaves fewer
 *  than a full row, so every seat lands on a full, honest row. */
export const DEFAULT_HEADER_PICKS = [
  "inventory.total_items",
  "inventory.total_market_value",
  "borrowing.checked_out",
  "claims.open_claims",
  "maintenance.maintenance_due",
  "support.open_tickets",
];
export const RUNG_HEADER_PICKS = [
  "prints.listings",
  "prints.my_uploads",
  "prints.my_downloads",
  "downloads.documents",
  "downloads.wallpapers",
  "downloads.total_downloads",
];

export function defaultHeaderPicks(
  available: readonly string[],
  rung: boolean,
): string[] {
  const avail = new Set(available);
  const named = (rung ? RUNG_HEADER_PICKS : DEFAULT_HEADER_PICKS).filter((k) =>
    avail.has(k),
  );
  const out = [...named];
  for (const key of available) {
    if (out.length >= HEADER_STATS_PER_ROW) break;
    if (!out.includes(key)) out.push(key);
  }
  return out.slice(0, HEADER_STATS_PER_ROW);
}

/** The header's stats row: the picks rendered as header FACTS
 *  at the top of the Home header (SectionPageHeader's facts
 *  seat, via `factsExtra`) — the same SectionPageFactItem and
 *  .tv-secpage-facts row every section header's facts use, so
 *  a Home stat and an Inventory fact are one treatment: bare
 *  label over value on the panel, a plain link when the stat
 *  has a door, no box around any of them (owner correction
 *  2026-11-10; Lane 3's lower-strip grid of ringed cells is
 *  retired). The Customize link does NOT ride this row: it
 *  sits in the header's top-right cluster, directly under
 *  the Add-a-widget button (owner placement, 2026-11-10;
 *  HomeShell renders it there). A stat's seat renders from
 *  the start in the facts register — label visible, value
 *  pending — and the value takes the seat when its read
 *  lands; the header never prints a number it doesn't hold
 *  (the Dealers facts' contract, sweep 10-F4). */
export function HomeHeaderStats({
  picks,
  available,
  serverValues,
  statLabel,
}: {
  picks: string[];
  available: readonly string[];
  serverValues: Record<string, number>;
  statLabel: (key: string, fallback: string) => string;
}) {
  const avail = new Set(available);
  const defs = picks
    .filter((k) => avail.has(k))
    .map((k) => HEADER_STAT_BY_KEY.get(k))
    .filter((d): d is HeaderStatDef => !!d)
    .slice(0, HEADER_STATS_MAX);
  const keys = defs.map((d) => d.key).join(",");
  const [values, setValues] = useState<Record<string, string>>({});
  const cacheRef = useRef(new Map<string, Promise<unknown>>());
  const serverRef = useRef(serverValues);
  serverRef.current = serverValues;

  useEffect(() => {
    let live = true;
    const ctx: HeaderStatContext = {
      serverValues: serverRef.current,
      once: (key, fn) => {
        const hit = cacheRef.current.get(key);
        if (hit) return hit as Promise<never>;
        const made = fn();
        cacheRef.current.set(key, made as Promise<unknown>);
        return made;
      },
    };
    for (const def of defs) {
      def
        .load(ctx)
        .then((value) => {
          if (live) {
            setValues((prev) =>
              prev[def.key] === value ? prev : { ...prev, [def.key]: value },
            );
          }
        })
        .catch(() => {
          /* a failed read simply never lands — no invented number */
        });
    }
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys]);

  return (
    <dl className="tv-secpage-facts tv-home-hstats">
      {defs.map((def) => {
        const value = values[def.key];
        /* Loading register (sweep 10-F4): a stat whose read has
         * not landed yet renders as the SAME fact it will
         * become — its label in the facts register, its value
         * seat held by a pending shimmer — never an unlabelled
         * slab and never a missing seat that makes the row
         * grow item by item. A FAILED read also stays pending
         * here: the header prints no number it doesn't hold,
         * and the seat keeps the row's shape honest while the
         * read is outstanding. The pending fact carries no
         * door (a link to a number that doesn't exist yet
         * would be a dead-feeling click); the door arrives
         * with the value. */
        if (value === undefined) {
          return (
            <SectionPageFactItem
              key={def.key}
              fact={{
                label: statLabel(def.key, def.label),
                value: (
                  <span className="tv-fact-pending" aria-hidden="true" />
                ),
              }}
            />
          );
        }
        const numeric = Number.parseFloat(value.replace(/[^0-9.]/g, ""));
        const alert =
          def.alertTone && Number.isFinite(numeric) && numeric > 0;
        return (
          <SectionPageFactItem
            key={def.key}
            fact={{
              label: statLabel(def.key, def.label),
              value,
              href: def.href,
              alert,
            }}
          />
        );
      })}
    </dl>
  );
}

