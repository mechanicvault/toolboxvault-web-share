import type { ReactNode } from "react";
import type { DictKey } from "../../i18n/dictionaries";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import { ArtIcon } from "../../components/ArtIcon";
import { BellIcon } from "../../components/icons";
import { sourceTitle, type FlyerSource } from "../flyers/types";
import { HOME_WIDGETS } from "./homeWidgets";

/**
 * THE ASPECT FRAMEWORK (dashboard redesign Lane 2, design
 * §3.6/§3.7). An ASPECT is a named slice of a module's existing
 * Home-visible content: the lines, rows, strips and buttons
 * its predefined widget already renders, each behind the
 * settings gates the loaders read (Lane 2 added the missing
 * gates at default-ON, so a predefined widget with no bundle
 * is byte-identical to before).
 *
 * A custom widget is stored as ONE layout entry whose key is
 * `custom:<id>` and whose settings bundle carries:
 *   cmodule   — the catalog module id below
 *   cname     — the user's name for the box (absent = the
 *               module's own localized title)
 *   caspects  — the picked aspect ids (string list)
 *   csources  — flyers only: the source keys known when the
 *               box was last configured (see deriveBodySettings)
 * plus the numeric choices under the loaders' own key names
 * (recentCount, rowsToShow, ...). The layout store's flat-leaf
 * bundle carries all of it — no second store, no new endpoint.
 *
 * Rendering a custom box derives, PER BODY, the bundle the
 * existing body renders with: every aspect of that body starts
 * from its OFF slice, picked aspects lay their ON slice over
 * it, and the stored numbers for picked aspects ride on top.
 * A body renders only while at least one of its aspects is
 * picked. Bodies are the existing renders themselves —
 * HomeWidget bodies in bare mode, the How-to Videos / Quick
 * Reports / Notifications blocks in bare mode, and the Dealer
 * Dashboard whole (its sections are the aspects).
 *
 * The predefined recipe (what the wizard pre-checks) is the
 * module's MAIN predefined widget: its default-on aspects are
 * the aspects whose loaders default on. Satellite widgets a
 * module also owns (Health checks due, Dealers near you,
 * Quick Add, How-to Videos, Quick Reports) start unchecked —
 * they already exist as their own predefined widgets.
 */

export const CUSTOM_PREFIX = "custom:";

export function isCustomKey(key: string): boolean {
  return key.startsWith(CUSTOM_PREFIX);
}

export function newCustomKey(): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${CUSTOM_PREFIX}${rand}`;
}

/** One numeric choice an aspect carries (how many rows, a
 *  radius): shown in the wizard's Configure step and in the
 *  box's options panel while the aspect is on. The value
 *  stores under the loader's own settings key. */
export interface AspectNumDef {
  name: string;
  labelKey: DictKey;
  dflt: number;
  min: number;
  max: number;
  /** An explicit choice set instead of the min..max sweep
   *  (the near-you radius, the notifications cap). */
  choices?: number[];
}

export interface AspectDef {
  /** Stable id, unique inside its module. Stored in caspects. */
  id: string;
  /** The body this aspect belongs to (CustomBodyDef.id). */
  body: string;
  labelKey: DictKey;
  /** Runtime label for data-driven aspects (flyer sources);
   *  wins over labelKey when set. */
  labelText?: string;
  descKey: DictKey;
  /** Pre-checked in the wizard (the predefined recipe). */
  defaultOn: boolean;
  /** Settings slice applied while the aspect is ON. */
  on: Record<string, BlockSettingValue>;
  /** Settings slice applied while the aspect is OFF — the
   *  force-off that keeps an unpicked slice out of the box
   *  even where the loader's own default is on. */
  off: Record<string, BlockSettingValue>;
  nums?: AspectNumDef[];
}

export type CustomBodyKind =
  | "widget"
  | "videos"
  | "quickReports"
  | "notifications"
  | "dealerDashboard";

export interface CustomBodyDef {
  id: string;
  kind: CustomBodyKind;
  /** HOME_WIDGETS id for kind "widget". */
  widgetId?: string;
}

export interface CustomModuleDef {
  /** Catalog id — stored as the entry's cmodule. */
  id: string;
  /** The predefined registry entry that hosts this module:
   *  the module is offered (and its custom boxes render) only
   *  while that entry is in the seat's eligible registry —
   *  reach and group gates ride Lane 1's own decisions. */
  hostKey: string;
  /** Where the box's title and Open button go. */
  door: string;
  icon: ReactNode;
  cta: "viewAll" | "open";
  bodies: CustomBodyDef[];
  aspects: AspectDef[];
  /** Flyers: the aspect list grows one aspect per flyer
   *  source the user follows (data-driven, resolved at
   *  configure time from the module's own source read). */
  dynamicFlyers?: boolean;
}

/** A boolean slice aspect: one loader switch, on/off. */
function boolAspect(
  id: string,
  body: string,
  labelKey: DictKey,
  descKey: DictKey,
  name: string,
  defaultOn: boolean,
  nums?: AspectNumDef[],
): AspectDef {
  return {
    id,
    body,
    labelKey,
    descKey,
    defaultOn,
    on: { [name]: true },
    off: { [name]: false },
    nums,
  };
}

/** A whole-body aspect: the body itself is the slice (a
 *  satellite widget folded into its module). Picking it is
 *  what seats the body in the box; its numbers configure it. */
function bodyAspect(
  id: string,
  body: string,
  labelKey: DictKey,
  descKey: DictKey,
  defaultOn: boolean,
  nums?: AspectNumDef[],
): AspectDef {
  return { id, body, labelKey, descKey, defaultOn, on: {}, off: {}, nums };
}

function num(
  name: string,
  labelKey: DictKey,
  dflt: number,
  min: number,
  max: number,
  choices?: number[],
): AspectNumDef {
  return { name, labelKey, dflt, min, max, choices };
}

const W = HOME_WIDGETS;

export const CUSTOM_MODULES: CustomModuleDef[] = [
  {
    id: "inventory",
    hostKey: "widget:inventory",
    door: "/inventory",
    icon: W.inventory.icon,
    cta: "open",
    bodies: [
      { id: "main", kind: "widget", widgetId: "inventory" },
      { id: "health", kind: "widget", widgetId: "health_checks_due" },
      { id: "quickadd", kind: "widget", widgetId: "quick_add" },
    ],
    aspects: [
      boolAspect("count", "main", "home.opt.inventory.countLine", "home.asp.inventory.count.d", "showCount", true),
      boolAspect("value", "main", "home.opt.inventory.valueLine", "home.asp.inventory.value.d", "showValue", true),
      boolAspect("recent", "main", "home.opt.inventory.latestLine", "home.asp.inventory.recent.d", "showLatest", true, [
        num("recentCount", "home.opt.inventory.recentCount", 1, 1, 5),
      ]),
      boolAspect("addbutton", "main", "home.opt.inventory.addButton", "home.asp.inventory.addbutton.d", "addButton", false),
      bodyAspect("health", "health", "home.widget.health.title", "home.asp.inventory.health.d", false, [
        num("rowsToShow", "home.opt.health.rows", 4, 2, 6),
      ]),
      bodyAspect("quickadd", "quickadd", "home.widget.quickAdd.title", "home.asp.inventory.quickadd.d", false),
    ],
  },
  {
    id: "dealers",
    hostKey: "widget:dealers",
    door: "/dealers",
    icon: W.dealers.icon,
    cta: "open",
    bodies: [
      { id: "main", kind: "widget", widgetId: "dealers" },
      { id: "nearyou", kind: "widget", widgetId: "dealers_near_you" },
    ],
    aspects: [
      boolAspect("count", "main", "home.opt.dealers.countLine", "home.asp.dealers.count.d", "showCount", true),
      boolAspect("tiles", "main", "home.asp.dealers.tiles", "home.asp.dealers.tiles.d", "showTiles", true, [
        num("tilesToShow", "home.opt.dealers.tiles", 8, 4, 16),
      ]),
      boolAspect("doors", "main", "home.asp.dealers.doors", "home.asp.dealers.doors.d", "showActions", true),
      bodyAspect("nearyou", "nearyou", "home.widget.dealersNear.title", "home.asp.dealers.nearyou.d", false, [
        num("radiusMiles", "home.opt.near.radius", 50, 10, 100, [10, 25, 50, 100]),
        num("rowsToShow", "home.opt.near.rows", 4, 2, 6),
      ]),
    ],
  },
  {
    id: "truck_accounts",
    hostKey: "widget:truck_accounts",
    door: "/truck-accounts",
    icon: W.truck_accounts.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "truck_accounts" }],
    aspects: [
      boolAspect("opencount", "main", "home.asp.truck.opencount", "home.asp.truck.opencount.d", "showOpenCount", true),
      boolAspect("duetotal", "main", "home.asp.truck.duetotal", "home.asp.truck.duetotal.d", "showDueTotal", true),
      boolAspect("owed", "main", "home.asp.truck.owed", "home.asp.truck.owed.d", "showOwed", true),
      boolAspect("rows", "main", "home.asp.truck.rows", "home.asp.truck.rows.d", "showRows", true, [
        num("rowsVisible", "home.opt.accountsBeforeScroll", 3, 2, 6),
      ]),
      boolAspect("quickentry", "main", "home.opt.truck.quickEntry", "home.asp.truck.quickentry.d", "quickEntry", true),
    ],
  },
  {
    id: "maintenance",
    hostKey: "widget:maintenance",
    door: "/repairs",
    icon: W.maintenance.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "maintenance" }],
    aspects: [
      boolAspect("due", "main", "home.opt.maintenance.dueLine", "home.asp.maintenance.due.d", "showDue", true),
      boolAspect("out", "main", "home.opt.maintenance.outLine", "home.asp.maintenance.out.d", "showOut", true),
      boolAspect("comingup", "main", "home.opt.maintenance.comingUp", "home.asp.maintenance.comingup.d", "comingUp", true, [
        num("visibleRows", "home.opt.rowsBeforeScroll", 3, 1, 5),
      ]),
      boolAspect("claimsline", "main", "home.opt.maintenance.openClaimsLine", "home.asp.maintenance.claimsline.d", "showClaimsLine", true),
      boolAspect("backordered", "main", "home.opt.maintenance.backorderedLine", "home.asp.maintenance.backordered.d", "showBackordered", true),
      boolAspect("claimslist", "main", "home.opt.maintenance.claimsList", "home.asp.maintenance.claimslist.d", "claimsList", true, [
        num("claimCount", "home.opt.claims.recentCount", 3, 1, 5),
      ]),
      boolAspect("claimbuttons", "main", "home.opt.maintenance.claimButtons", "home.asp.maintenance.claimbuttons.d", "showClaimButtons", true),
    ],
  },
  {
    id: "disaster_claims",
    hostKey: "widget:disaster_claims",
    door: "/disaster-claims",
    icon: W.disaster_claims.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "disaster_claims" }],
    aspects: [
      boolAspect("count", "main", "home.asp.disaster.count", "home.asp.disaster.count.d", "showCount", true),
      boolAspect("recent", "main", "home.asp.disaster.recent", "home.asp.disaster.recent.d", "showRows", true, [
        num("recentCount", "home.opt.disasterClaims.recentCount", 3, 1, 5),
      ]),
      boolAspect("buttons", "main", "home.opt.disasterClaims.showButtons", "home.asp.disaster.buttons.d", "showButtons", true),
    ],
  },
  {
    id: "borrowing",
    hostKey: "widget:borrowing",
    door: "/borrowing",
    icon: W.borrowing.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "borrowing" }],
    aspects: [
      boolAspect("counts", "main", "home.asp.borrowing.counts", "home.asp.borrowing.counts.d", "showCounts", true),
      boolAspect("lent", "main", "home.opt.borrowing.lentList", "home.asp.borrowing.lent.d", "lentList", true, [
        num("visibleRows", "home.opt.rowsBeforeScroll", 3, 2, 6),
      ]),
      boolAspect("borrowed", "main", "home.opt.borrowing.borrowedList", "home.asp.borrowing.borrowed.d", "borrowedList", false, [
        num("visibleRows", "home.opt.rowsBeforeScroll", 3, 2, 6),
      ]),
      boolAspect("overdue", "main", "home.opt.borrowing.overdueNames", "home.asp.borrowing.overdue.d", "overdueNames", false),
      boolAspect("requests", "main", "home.opt.borrowing.requestsLine", "home.asp.borrowing.requests.d", "requestsLine", true),
    ],
  },
  {
    id: "flyers",
    hostKey: "widget:flyers",
    door: "/flyers",
    icon: W.flyers.icon,
    cta: "viewAll",
    bodies: [{ id: "main", kind: "widget", widgetId: "flyers" }],
    dynamicFlyers: true,
    aspects: [
      boolAspect("count", "main", "home.asp.flyers.count", "home.asp.flyers.count.d", "showCount", true),
      boolAspect("rows", "main", "home.asp.flyers.rows", "home.asp.flyers.rows.d", "showRows", true),
    ],
  },
  {
    id: "downloads",
    hostKey: "widget:downloads",
    door: "/downloads",
    icon: W.downloads.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "downloads" }],
    aspects: [
      boolAspect("stats", "main", "home.opt.downloads.stats", "home.asp.downloads.stats.d", "showStats", true),
      boolAspect("weekly", "main", "home.opt.downloads.weekly", "home.asp.downloads.weekly.d", "showWeekly", true, [
        num("tilesToShow", "home.opt.downloads.tiles", 8, 4, 12),
      ]),
      boolAspect("door", "main", "home.asp.downloads.door", "home.asp.downloads.door.d", "showDoor", true),
    ],
  },
  {
    id: "prints",
    hostKey: "widget:prints",
    door: "/3dprints",
    icon: W.prints.icon,
    cta: "viewAll",
    bodies: [{ id: "main", kind: "widget", widgetId: "prints" }],
    aspects: [
      boolAspect("count", "main", "home.opt.prints.countLine", "home.asp.prints.count.d", "showCount", true),
      boolAspect("ratings", "main", "home.opt.prints.ratings", "home.asp.prints.ratings.d", "showRatings", true),
      boolAspect("newstrip", "main", "home.opt.prints.newStrip", "home.asp.prints.newstrip.d", "showNew", true, [
        num("tilesToShow", "home.opt.prints.tiles", 8, 4, 12),
      ]),
      boolAspect("topstrip", "main", "home.opt.prints.topStrip", "home.asp.prints.topstrip.d", "showTop", true),
      boolAspect("upload", "main", "home.opt.prints.uploadButton", "home.asp.prints.upload.d", "showUpload", true),
      boolAspect("mine", "main", "home.opt.prints.mineButton", "home.asp.prints.mine.d", "showMine", true),
      boolAspect("filesdoor", "main", "home.asp.prints.filesdoor", "home.asp.prints.filesdoor.d", "showFiles", true),
    ],
  },
  {
    id: "converter",
    hostKey: "widget:converter",
    door: "/downloads#documents",
    icon: W.converter.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "converter" }],
    aspects: [
      bodyAspect("self", "main", "home.asp.converter.self", "home.asp.converter.self.d", true),
    ],
  },
  {
    id: "feedback",
    hostKey: "widget:feedback",
    door: "/feedback",
    icon: W.feedback.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "feedback" }],
    aspects: [
      boolAspect("counts", "main", "home.opt.feedback.countLine", "home.asp.feedback.counts.d", "showCounts", true),
      boolAspect("bugrows", "main", "home.widget.feedbackBugs", "home.asp.feedback.bugrows.d", "showBugRows", true, [
        num("rowsPerBoard", "home.opt.feedback.rowsPerBoard", 3, 0, 3),
      ]),
      boolAspect("featrows", "main", "home.widget.feedbackFeatures", "home.asp.feedback.featrows.d", "showFeatureRows", true),
    ],
  },
  {
    id: "support",
    hostKey: "widget:support",
    door: "/help",
    icon: W.support.icon,
    cta: "open",
    bodies: [
      { id: "main", kind: "widget", widgetId: "support" },
      { id: "videos", kind: "videos" },
    ],
    aspects: [
      boolAspect("tickcount", "main", "home.opt.support.countLine", "home.asp.support.tickcount.d", "showCount", true),
      boolAspect("tickrows", "main", "home.asp.support.tickrows", "home.asp.support.tickrows.d", "showRows", true, [
        num("rowsToShow", "home.opt.support.rowsToShow", 3, 1, 5),
      ]),
      bodyAspect("videos", "videos", "help.tab.videos", "home.asp.support.videos.d", false),
    ],
  },
  {
    id: "shared_tools",
    hostKey: "widget:shared_tools",
    door: "/shared-tools",
    icon: W.shared_tools.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "shared_tools" }],
    aspects: [
      boolAspect("counts", "main", "home.opt.shared.countsLine", "home.asp.shared.counts.d", "showCounts", true),
      boolAspect("invites", "main", "home.opt.shared.invitesLine", "home.asp.shared.invites.d", "showInvites", true),
      boolAspect("withme", "main", "home.widget.sharedWithYou", "home.asp.shared.withme.d", "showWithMe", true),
      boolAspect("mine", "main", "home.widget.youShareWith", "home.asp.shared.mine.d", "showMine", true),
    ],
  },
  {
    id: "tool_expansion",
    hostKey: "widget:tool_expansion",
    door: "/tool-expansion",
    icon: W.tool_expansion.icon,
    cta: "viewAll",
    bodies: [{ id: "main", kind: "widget", widgetId: "tool_expansion" }],
    aspects: [
      boolAspect("count", "main", "home.opt.expansion.countLine", "home.asp.expansion.count.d", "showCount", true),
      boolAspect("suggestions", "main", "home.asp.expansion.suggestions", "home.asp.expansion.suggestions.d", "showRows", true, [
        num("rowsToShow", "home.opt.expansion.rowsToShow", 2, 2, 5),
      ]),
    ],
  },
  {
    id: "reports",
    hostKey: "widget:reports",
    door: "/reports",
    icon: W.reports.icon,
    cta: "open",
    bodies: [
      { id: "main", kind: "widget", widgetId: "reports" },
      { id: "quick", kind: "quickReports" },
    ],
    aspects: [
      boolAspect("count", "main", "home.asp.reports.count", "home.asp.reports.count.d", "showCount", true),
      boolAspect("templates", "main", "home.asp.reports.templates", "home.asp.reports.templates.d", "showRows", true, [
        num("rowsVisible", "home.opt.rowsBeforeScroll", 2, 2, 5),
      ]),
      bodyAspect("quick", "quick", "reports.page.quickTitle", "home.asp.reports.quick.d", false, [
        num("rowsToShow", "home.opt.qr.rowsToShow", 5, 1, 10),
      ]),
    ],
  },
  {
    id: "notifications",
    hostKey: "notifications",
    door: "/notifications",
    icon: <BellIcon size={24} />,
    cta: "open",
    bodies: [{ id: "main", kind: "notifications" }],
    aspects: [
      boolAspect("recent", "main", "home.asp.notifications.recent", "home.asp.notifications.recent.d", "showRows", true, [
        num("rowsBeforeScroll", "home.opt.rowsBeforeScroll", 5, 3, 8, [3, 5, 8]),
      ]),
      boolAspect("overdue", "main", "home.opt.notifications.overdueLine", "home.asp.notifications.overdue.d", "overdueLine", true),
      boolAspect("unread", "main", "home.opt.notifications.unreadOnly", "home.asp.notifications.unread.d", "unreadOnly", false),
    ],
  },
  {
    id: "account_plan",
    hostKey: "account_plan",
    door: "/settings/billing",
    icon: W.account_plan.icon,
    cta: "open",
    bodies: [{ id: "main", kind: "widget", widgetId: "account_plan" }],
    aspects: [
      {
        // The plan stat and (on the downloads level) the
        // account-number stat are one fact family.
        id: "plan",
        body: "main",
        labelKey: "home.widget.accountPlan.statPlan",
        descKey: "home.asp.account.plan.d",
        defaultOn: true,
        on: { showPlan: true, showAccount: true },
        off: { showPlan: false, showAccount: false },
      },
      boolAspect("items", "main", "home.widget.accountPlan.statItems", "home.asp.account.items.d", "showItems", true),
      boolAspect("renewal", "main", "home.asp.account.renewal", "home.asp.account.renewal.d", "showRenewal", true),
      boolAspect("source", "main", "home.asp.account.source", "home.asp.account.source.d", "showSource", true),
      boolAspect("manage", "main", "home.widget.accountPlan.manage", "home.asp.account.manage.d", "showManage", true),
      boolAspect("accountbtn", "main", "home.widget.accountPlan.accountSettings", "home.asp.account.accountbtn.d", "showAccountBtn", true),
    ],
  },
  {
    id: "dealer_dashboard",
    hostKey: "dealer_dashboard",
    door: "/dealers",
    icon: <ArtIcon name="dealers" size={24} />,
    cta: "open",
    bodies: [{ id: "main", kind: "dealerDashboard" }],
    aspects: [
      boolAspect("profile", "main", "home.opt.dealer.profile", "home.asp.dealer.profile.d", "showProfile", true),
      boolAspect("warrantyrequests", "main", "home.opt.dealer.warrantyRequests", "home.asp.dealer.warrantyrequests.d", "showWarrantyRequests", true),
      boolAspect("warrantyclaims", "main", "home.opt.dealer.warrantyClaims", "home.asp.dealer.warrantyclaims.d", "showWarrantyClaims", true),
      boolAspect("truckaccounts", "main", "home.opt.dealer.truckAccounts", "home.asp.dealer.truckaccounts.d", "showTruckAccounts", true),
      boolAspect("paymentsdue", "main", "home.opt.dealer.paymentsDue", "home.asp.dealer.paymentsdue.d", "showPaymentsDue", true),
      boolAspect("route", "main", "home.opt.dealer.route", "home.asp.dealer.route.d", "showRoute", true),
    ],
  },
];

export const CUSTOM_MODULE_BY_ID: Record<string, CustomModuleDef> = Object.fromEntries(
  CUSTOM_MODULES.map((m) => [m.id, m]),
);

/** The flyer-source aspects for a seat: one per source the
 *  module's own source read returns (the FlyersOptions
 *  pattern). A source aspect's label is the source's own
 *  title — data, not dictionary. */
export function flyerSourceAspects(sources: FlyerSource[]): AspectDef[] {
  return sources.map((source) => ({
    id: `src:${source.key}`,
    body: "main",
    labelKey: "home.asp.flyers.src",
    labelText: sourceTitle(source),
    descKey: "home.asp.flyers.src.d",
    defaultOn: true,
    on: {},
    off: {},
  }));
}

/** Every aspect a module offers a seat: the static list plus,
 *  for flyers, the seat's source aspects. */
export function aspectsForModule(
  mod: CustomModuleDef,
  flyerSources: FlyerSource[] | null,
): AspectDef[] {
  if (mod.dynamicFlyers && flyerSources) {
    return [...mod.aspects, ...flyerSourceAspects(flyerSources)];
  }
  return mod.aspects;
}

/** The predefined recipe: the aspects a fresh wizard visit
 *  pre-checks for this module. */
export function defaultPicks(
  mod: CustomModuleDef,
  flyerSources: FlyerSource[] | null,
): Set<string> {
  return new Set(
    aspectsForModule(mod, flyerSources)
      .filter((a) => a.defaultOn)
      .map((a) => a.id),
  );
}

/** What a stored custom entry says: its module, its name
 *  (absent = the module's title), and its picked aspects.
 *  Returns null when the bundle isn't a custom-widget bundle
 *  (or names a module the catalog no longer holds). */
export function parseCustomSettings(
  settings: Record<string, BlockSettingValue>,
): { moduleId: string; name: string | null; picks: Set<string> } | null {
  const moduleId = settings.cmodule;
  if (typeof moduleId !== "string" || !CUSTOM_MODULE_BY_ID[moduleId]) {
    return null;
  }
  const raw = settings.caspects;
  const picks = new Set(
    Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [],
  );
  const name =
    typeof settings.cname === "string" && settings.cname.trim()
      ? settings.cname
      : null;
  return { moduleId, name, picks };
}

/** Derive ONE body's render bundle from a custom entry's
 *  stored settings: off slices for every aspect of the body,
 *  on slices for the picked ones, then the stored numbers of
 *  picked aspects. Flyers translate source picks into the
 *  loader's hiddenSources against the source keys captured
 *  when the box was last configured (csources) — a source
 *  that appears later is simply not in the captured list, so
 *  it shows, exactly like the predefined widget's rule. */
export function deriveBodySettings(
  mod: CustomModuleDef,
  bodyId: string,
  picks: Set<string>,
  stored: Record<string, BlockSettingValue>,
  flyerSources: FlyerSource[] | null,
): Record<string, BlockSettingValue> {
  const out: Record<string, BlockSettingValue> = {};
  const aspects = aspectsForModule(mod, flyerSources).filter(
    (a) => a.body === bodyId,
  );
  for (const aspect of aspects) {
    Object.assign(out, picks.has(aspect.id) ? aspect.on : aspect.off);
  }
  for (const aspect of aspects) {
    if (!picks.has(aspect.id)) continue;
    for (const n of aspect.nums ?? []) {
      const v = stored[n.name];
      if (typeof v === "number" && Number.isFinite(v)) out[n.name] = v;
    }
  }
  if (mod.dynamicFlyers) {
    const known = Array.isArray(stored.csources)
      ? stored.csources.filter((x): x is string => typeof x === "string")
      : [];
    const hidden = known.filter((k) => !picks.has(`src:${k}`));
    if (hidden.length > 0) out.hiddenSources = hidden;
    // Picking any source aspect implies the rows it feeds:
    // a box that chose sources but not "rows" still shows
    // those sources' rows (the count line stays its own
    // aspect). The predefined widget's absence rule agrees.
    if (known.some((k) => picks.has(`src:${k}`))) out.showRows = true;
  }
  return out;
}

/** The bodies a custom box renders: those with at least one
 *  picked aspect, in catalog order. Flyer-source picks count
 *  toward their body even when the caller holds no source
 *  list (the render path derives from csources, not from a
 *  live enumeration). */
export function pickedBodies(
  mod: CustomModuleDef,
  picks: Set<string>,
  flyerSources: FlyerSource[] | null,
): CustomBodyDef[] {
  const aspects = aspectsForModule(mod, flyerSources);
  return mod.bodies.filter(
    (b) =>
      aspects.some((a) => a.body === b.id && picks.has(a.id)) ||
      (mod.dynamicFlyers &&
        b.id === "main" &&
        [...picks].some((id) => id.startsWith("src:"))),
  );
}
