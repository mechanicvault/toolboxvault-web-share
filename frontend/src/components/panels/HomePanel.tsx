import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api } from "../../lib/api";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import {
  PANEL_SECTIONS,
  resolvePanelOrder,
  useHomePanelEdit,
} from "../../lib/homePanelEdit";
import { formatMoney } from "../../lib/money";
import { useAuth } from "../../modules/core/AuthContext";
import { accountTypeSummary } from "../../modules/core/accountTypes";
import { AddBlockMenu } from "../AddBlockMenu";
import { Alert } from "../Alert";
import type { InventoryStats } from "../OverviewRow";
import { PanelUtility } from "./PanelUtility";

type AccountType =
  | "mechanic_technician"
  | "shop_company"
  | "tool_dealer"
  | "insurance";

const ALL_GROUPS: AccountType[] = [
  "mechanic_technician",
  "shop_company",
  "tool_dealer",
  "insurance",
];
const MECHANIC_SHOP: AccountType[] = ["mechanic_technician", "shop_company"];

const count = (n: number): string => n.toLocaleString("en-US");
const money = (v: string): string => formatMoney(v, null, true);

/**
 * THE PANEL STAT CATALOG (Phase 3, owner 2026-10-24, item 10):
 * every count the system can truthfully compute for the
 * signed-in user, as a pickable panel row. Each source feeds one
 * module's stats endpoint; the stat is AVAILABLE only when the
 * user's groups cover the source AND the endpoint answers —
 * the endpoint is the module entitlement + per-user module
 * switch gate (require_module answers 403 while a module is
 * off or unentitled), so a switched-off module's rows vanish
 * from the panel and its Add menu alike, and return when the
 * module returns. Labels ride the stat.* dictionary family,
 * shared with the Overview registry.
 */
interface StatSource {
  groups: AccountType[];
  run: () => Promise<[string, string][]>;
}

const STAT_SOURCES: StatSource[] = [
  {
    groups: ALL_GROUPS,
    run: () =>
      api<InventoryStats>("/inventory/stats").then((s) => [
        ["inventory.total_items", count(s.total_items)],
        ["inventory.total_market_value", money(s.total_value)],
        ["inventory.total_replacement_cost", money(s.total_replacement_cost)],
        ["inventory.warranties_expiring_soon", count(s.warranties_expiring_soon)],
        ["inventory.warranties_expired", count(s.warranties_expired)],
        ["inventory.category_count", count(s.category_count)],
      ] as [string, string][]),
  },
  {
    groups: MECHANIC_SHOP,
    run: () =>
      api<{ checked_out_count: number; borrowed_by_me_count: number }>(
        "/borrowing/stats",
      ).then((s) => [
        ["borrowing.checked_out", count(s.checked_out_count)],
        ["borrowing.borrowed_by_me", count(s.borrowed_by_me_count)],
      ] as [string, string][]),
  },
  {
    groups: MECHANIC_SHOP,
    run: () =>
      api<{ open_claims_count: number }>("/claims/stats").then((s) => [
        ["claims.open_claims", count(s.open_claims_count)],
      ] as [string, string][]),
  },
  {
    groups: MECHANIC_SHOP,
    run: () =>
      api<{ maintenance_due_count: number; out_of_service_count: number }>(
        "/maintenance/stats",
      ).then((s) => [
        ["maintenance.maintenance_due", count(s.maintenance_due_count)],
        ["maintenance.out_of_service", count(s.out_of_service_count)],
      ] as [string, string][]),
  },
  {
    groups: MECHANIC_SHOP,
    run: () =>
      api<{ parts_count: number }>("/parts/stats").then((s) => [
        ["parts.used_parts", count(s.parts_count)],
      ] as [string, string][]),
  },
  {
    groups: ["tool_dealer"],
    run: () =>
      api<{
        preferred_by_count: number;
        companies_represented_count: number;
        profile_visibility: string;
      }>("/dealers/stats").then((s) => [
        ["dealers.preferred_by", count(s.preferred_by_count)],
        ["dealers.companies_represented", count(s.companies_represented_count)],
        ["dealers.profile_visibility", s.profile_visibility],
      ] as [string, string][]),
  },
  {
    groups: ALL_GROUPS,
    run: () =>
      api<{ active_listings_count: number }>("/marketplace/stats").then((s) => [
        ["marketplace.active_listings", count(s.active_listings_count)],
      ] as [string, string][]),
  },
  {
    groups: MECHANIC_SHOP,
    run: () =>
      api<{ items_count: number }>("/wishlist/stats").then((s) => [
        ["wishlist.items", count(s.items_count)],
      ] as [string, string][]),
  },
  {
    groups: ALL_GROUPS,
    run: () =>
      api<{ inbox_unread: number }>("/messaging/unread").then((s) => [
        ["messaging.unread", count(s.inbox_unread)],
      ] as [string, string][]),
  },
  {
    groups: ALL_GROUPS,
    run: () =>
      api<{ open_tickets_count: number }>("/support/stats").then((s) => [
        ["support.open_tickets", count(s.open_tickets_count)],
      ] as [string, string][]),
  },
];

/** Catalog order — the Add menu's order and the order unpicked
 *  stats sort by. Mirrors the Overview registry's order, with
 *  the panel-only stats beside their module siblings. */
const CATALOG_ORDER: string[] = [
  "inventory.total_items",
  "inventory.total_market_value",
  "inventory.total_replacement_cost",
  "inventory.warranties_expiring_soon",
  "inventory.warranties_expired",
  "inventory.category_count",
  "borrowing.checked_out",
  "borrowing.borrowed_by_me",
  "claims.open_claims",
  "maintenance.maintenance_due",
  "maintenance.out_of_service",
  "parts.used_parts",
  "dealers.preferred_by",
  "dealers.companies_represented",
  "dealers.profile_visibility",
  "marketplace.active_listings",
  "wishlist.items",
  "messaging.unread",
  "support.open_tickets",
];

/**
 * STAT → DESTINATION (Phase 2, owner 2026-10-24): outside Edit
 * view every panel stat row is ONE link to the page that shows
 * the data behind the number, riding the house URL-filter
 * pattern wherever a filtered view exists. Notes on the
 * non-obvious picks:
 * - Warranties ride Inventory's existing ?warranty= filter (the
 *   same param Home's warranty counters have always used), with
 *   soonest-end-first sort.
 * - Out of service lands on Maintenance, NOT a filtered
 *   Inventory: the count is the maintenance board's list
 *   (repair-state axis — tools, batteries AND set pieces whose
 *   repair state left in-service), and no Inventory filter
 *   reproduces that set (Inventory's standing column is a
 *   different axis: lost/stolen/sold live there, not repair).
 *   The Maintenance page renders that exact board.
 * - The dealer rows point at the surface that shows/controls
 *   the fact: preferred-by at the directory (the listing that
 *   earns the preferences; no page names the preferring
 *   mechanics), companies-represented and profile-visibility at
 *   the dealer profile settings (the represented-companies
 *   editor and the "List me publicly" switch live there).
 * - Open tickets lands on Help & Support — the USER's own
 *   ticket list, matching what the stat counts, even for
 *   operators.
 * Edit view renders its own branch (grip + red X rows), so rows
 * in Edit view never navigate.
 */
const STAT_LINKS: Record<string, string> = {
  "inventory.total_items": "/inventory",
  "inventory.total_market_value": "/inventory",
  "inventory.total_replacement_cost": "/inventory",
  "inventory.warranties_expiring_soon":
    "/inventory?warranty=expiring_soon&sort=warranty_end",
  "inventory.warranties_expired": "/inventory?warranty=expired&sort=warranty_end",
  "inventory.category_count": "/inventory/categories",
  "borrowing.checked_out": "/borrowing",
  "borrowing.borrowed_by_me": "/borrowing",
  "claims.open_claims": "/repairs#repair-claims",
  "maintenance.maintenance_due": "/repairs#tool-maintenance",
  "maintenance.out_of_service": "/repairs#out-of-service",
  "parts.used_parts": "/parts",
  "dealers.preferred_by": "/dealers",
  "dealers.companies_represented": "/settings/dealer-profile",
  "dealers.profile_visibility": "/settings/dealer-profile",
  "marketplace.active_listings": "/marketplace/mine",
  "wishlist.items": "/wishlist",
  "messaging.unread": "/messages",
  "support.open_tickets": "/help",
};

/** The rows a never-customized panel shows — exactly the rows
 *  the fixed list showed before Phase 3, in its order. */
const DEFAULT_PANEL_STATS: string[] = [
  "inventory.total_items",
  "inventory.total_market_value",
  "borrowing.checked_out",
  "claims.open_claims",
  "maintenance.maintenance_due",
  "inventory.warranties_expiring_soon",
];

/**
 * The Home panel — preview-exact order (MAPPING §3): kicker
 * "Overview", title, the account plate card (account #, group,
 * location — all from the auth user), the stats list, then the
 * utility block (search well + latest-notification note) under
 * it. Home + Header program (2026-10-24): the wordmark plate that
 * sat inside the account card is REMOVED (the owner's words — the
 * brand plate lives in the header now).
 *
 * Phase C (2026-10-24): the panel's three sections — "account"
 * (the account plate), "stats" (the stats list), "utility"
 * (PanelUtility) — are customizable entries in the SAME Edit
 * view session as the Home blocks (see lib/homePanelEdit for the
 * bridge): while editing, each section wears a mini chrome
 * (grip + title + red X), drag reorders them, and hidden
 * sections wait in an Add dropdown at the panel top. The choices
 * ride the home layout payload as the {key:"panel"} pseudo-entry
 * (panel_hidden / panel_order). All three sections are eligible
 * for every account group.
 *
 * Phase 3 (2026-10-24): the stats list's ROWS are the user's own
 * picks too — independent of the Overview block's stat picks
 * (the two lists parted ways here; before Phase 3 the panel
 * mirrored the Overview entry). The picks ride the same panel
 * pseudo-entry as `panel_stat_order` (a pick list: absent =
 * DEFAULT_PANEL_STATS above, so existing users see no change).
 * In Edit view each row wears a grip + red X, drag reorders,
 * and unpicked available stats wait in the stats section's own
 * Add menu. A picked stat whose module is off keeps its slot
 * and returns with the module (see the catalog note).
 *
 * The auth user carries no plan field (plan lives behind the
 * billing endpoints), so the plate's third row is the account
 * GROUP — recorded as a deviation in the conversion INDEX. The
 * preview's next-maintenance NOTE needs a next-due item, which
 * /maintenance/stats does not carry (counts only), so the note is
 * omitted rather than invented.
 */
export function HomePanel() {
  const { user } = useAuth();
  const t = useT();
  // The catalog's live values for THIS user: stat key -> rendered
  // value. A stat is present only while its source's groups
  // cover the user AND its endpoint answered.
  const [values, setValues] = useState<Record<string, string>>({});
  // The panel's own saved section layout (Phase C) + stat picks
  // (Phase 3): from the layout's "panel" pseudo-entry. Refetched
  // whenever an edit session ends (Save or Cancel) so the panel
  // settles on what is actually stored.
  const [panelSaved, setPanelSaved] = useState<{
    hidden: string[];
    order: string[];
  }>({ hidden: [], order: [] });
  const [savedStatOrder, setSavedStatOrder] = useState<string[] | null>(null);
  // The panel's own layout read can fail like the page's can:
  // surface it (owner bug report, 2026-10-24) — the default
  // sections must not silently pose as the saved ones here
  // either. The retry button lives on CorePage's alert (one
  // button for the page); it broadcasts tv:layout-retry and
  // this read refires on it. While editing, CorePage's session
  // (and its own error surface) governs, so this note stands
  // down.
  const [panelLoadError, setPanelLoadError] = useState(false);
  const [panelLoadNonce, setPanelLoadNonce] = useState(0);
  const edit = useHomePanelEdit();
  const editing = edit.editing;

  // One retry heals the whole page: CorePage's layout alert
  // carries the single Try again button and broadcasts
  // tv:layout-retry; this panel's read refires on it.
  useEffect(() => {
    const heal = () => setPanelLoadNonce((n) => n + 1);
    window.addEventListener("tv:layout-retry", heal);
    return () => window.removeEventListener("tv:layout-retry", heal);
  }, []);

  useEffect(() => {
    if (editing) return;
    let live = true;
    api<{
      blocks: {
        key: string;
        panel_hidden?: string[];
        panel_order?: string[];
        panel_stat_order?: string[];
      }[];
    }>("/core/layouts/home")
      .then((data) => {
        if (!live) return;
        const panel = data.blocks?.find((b) => b.key === "panel");
        setPanelSaved({
          hidden: panel?.panel_hidden ?? [],
          order: panel?.panel_order ?? [],
        });
        setSavedStatOrder(panel?.panel_stat_order ?? null);
        setPanelLoadError(false);
      })
      .catch(() => {
        if (live) setPanelLoadError(true);
      });
    return () => {
      live = false;
    };
  }, [editing, panelLoadNonce]);

  const userId = user?.id;
  const userGroups = user?.account_types ?? [];
  useEffect(() => {
    if (!userId) return;
    let live = true;
    const found: Record<string, string> = {};
    const jobs = STAT_SOURCES.filter((src) =>
      src.groups.some((g) => userGroups.includes(g)),
    ).map((src) =>
      src
        .run()
        .then((pairs) => {
          for (const [k, v] of pairs) found[k] = v;
        })
        .catch(() => undefined),
    );
    void Promise.all(jobs).then(() => {
      if (live) setValues(found);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const [dragKey, setDragKey] = useState<string | null>(null);
  const [statDragKey, setStatDragKey] = useState<string | null>(null);

  if (!user) return null;
  const location = user.public_area_label || user.country || "";

  // -- panel stat picks (Phase 3) --------------------------------
  const draftStatOrder = editing ? edit.statOrder : savedStatOrder;
  const basePicks = draftStatOrder ?? DEFAULT_PANEL_STATS;
  const shownRows = basePicks
    .filter((k) => values[k] !== undefined)
    .map((k) => ({ key: k, label: t(`stat.${k}` as DictKey), value: values[k] }));
  const addableKeys = CATALOG_ORDER.filter(
    (k) => values[k] !== undefined && !basePicks.includes(k),
  );
  const applyStatPicks = (next: string[]) => edit.setStatOrder(next);
  const hideStat = (key: string) =>
    applyStatPicks(basePicks.filter((k) => k !== key));
  const addStat = (key: string) => applyStatPicks([...basePicks, key]);
  const dropStatOn = (targetKey: string) => {
    if (!statDragKey || statDragKey === targetKey) return;
    const keys = [...basePicks];
    const from = keys.indexOf(statDragKey);
    const to = keys.indexOf(targetKey);
    if (from < 0 || to < 0) return;
    keys.splice(from, 1);
    keys.splice(to, 0, statDragKey);
    applyStatPicks(keys);
    setStatDragKey(null);
  };

  const statsContent = editing ? (
    <div>
      {shownRows.length > 0 && (
        <ul className="tv-sp-stats">
          {shownRows.map((row) => (
            <li
              key={row.key}
              className="tv-sp-stat-row"
              data-dragging={statDragKey === row.key || undefined}
              draggable
              onDragStart={(e) => {
                e.stopPropagation();
                setStatDragKey(row.key);
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                dropStatOn(row.key);
              }}
              onDragEnd={() => setStatDragKey(null)}
            >
              <span className="tv-sp-stat-name">
                <span className="tv-block-grip" aria-hidden="true" title="Drag to rearrange">
                  ⠿
                </span>
                {row.label}
              </span>
              <span className="tv-sp-stat-end">
                <strong>{row.value}</strong>
                <button
                  type="button"
                  className="tv-box-x"
                  aria-label={`Remove: ${row.label}`}
                  title="Remove"
                  onClick={() => hideStat(row.key)}
                >
                  −
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {addableKeys.length > 0 && (
        <div className="tv-panel-addrow">
          <AddBlockMenu
            items={addableKeys.map((k) => ({ key: k, title: t(`stat.${k}` as DictKey) }))}
            onAdd={addStat}
          />
        </div>
      )}
    </div>
  ) : shownRows.length > 0 ? (
    <ul className="tv-sp-stats">
      {shownRows.map((row) => {
        const to = STAT_LINKS[row.key];
        return to ? (
          <li key={row.key} className="tv-sp-stat-linked">
            <Link className="tv-sp-stat-link" to={to}>
              <span>{row.label}</span>
              <strong>{row.value}</strong>
            </Link>
          </li>
        ) : (
          <li key={row.key}>
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </li>
        );
      })}
    </ul>
  ) : null;

  const sectionContent: Record<string, ReactNode> = {
    account: (
      <div className="tv-sp-acct">
        <dl className="tv-sp-dl">
          <div>
            <dt>{t("home.panel.account")}</dt>
            <dd>{user.account_number}</dd>
          </div>
          <div>
            <dt>{t("home.panel.group")}</dt>
            <dd>{accountTypeSummary(user.account_types)}</dd>
          </div>
          {location && (
            <div>
              <dt>{t("home.panel.location")}</dt>
              <dd>{location}</dd>
            </div>
          )}
        </dl>
      </div>
    ),
    stats: statsContent,
    utility: <PanelUtility />,
  };

  const effectiveHidden = editing ? edit.hidden : panelSaved.hidden;
  const effectiveOrder = editing ? edit.order : panelSaved.order;
  const orderedKeys = resolvePanelOrder(effectiveOrder);
  const shownKeys = orderedKeys.filter((k) => !effectiveHidden.includes(k));
  const hiddenKeys = orderedKeys.filter((k) => effectiveHidden.includes(k));
  const titleOf = (key: string) =>
    PANEL_SECTIONS.find((s) => s.key === key)?.title ?? key;

  const dropOn = (targetKey: string) => {
    if (!dragKey || dragKey === targetKey) return;
    const keys = [...orderedKeys];
    const from = keys.indexOf(dragKey);
    const to = keys.indexOf(targetKey);
    if (from < 0 || to < 0) return;
    keys.splice(from, 1);
    keys.splice(to, 0, dragKey);
    edit.reorder(keys);
    setDragKey(null);
  };

  return (
    <>
      {editing && hiddenKeys.length > 0 && (
        <div className="tv-panel-addrow">
          <AddBlockMenu
            items={hiddenKeys.map((k) => ({ key: k, title: titleOf(k) }))}
            onAdd={(key) => edit.show(key)}
          />
        </div>
      )}
      <p className="tv-sp-kicker">{t("home.overview")}</p>
      <h2 className="tv-sp-title">{user.name}</h2>
      {panelLoadError && !editing && (
        <Alert tone="danger">
          <span>{t("home.layoutLoadFailed")}</span>
        </Alert>
      )}
      {shownKeys.map((key) =>
        editing ? (
          <div
            key={key}
            className="tv-panel-section"
            data-panel-key={key}
            data-dragging={dragKey === key || undefined}
            draggable
            onDragStart={(e) => {
              if (
                (e.target as HTMLElement).closest(
                  "a, button, input, select, textarea, [contenteditable]",
                ) &&
                !(e.target as HTMLElement).closest(".tv-panel-section-bar")
              ) {
                e.preventDefault();
                return;
              }
              setDragKey(key);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              dropOn(key);
            }}
            onDragEnd={() => setDragKey(null)}
          >
            <div className="tv-panel-section-bar">
              <span className="tv-block-grip" aria-hidden="true" title="Drag to rearrange">
                ⠿
              </span>
              <strong>{titleOf(key)}</strong>
              <span className="tv-block-spacer" />
              <button
                type="button"
                className="tv-box-x"
                aria-label={`Remove: ${titleOf(key)}`}
                title="Remove"
                onClick={() => edit.hide(key)}
              >
                −
              </button>
            </div>
            <div>{sectionContent[key]}</div>
          </div>
        ) : (
          <div key={key} className="tv-panel-section-plain" data-panel-key={key}>
            {sectionContent[key]}
          </div>
        ),
      )}
    </>
  );
}
