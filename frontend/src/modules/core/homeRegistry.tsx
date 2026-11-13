import { Suspense, lazy, type ReactNode } from "react";
import { MODULES } from "../registry";
import type { DictKey } from "../../i18n/dictionaries";
import { useNavLabel, useT } from "../../i18n/LocaleContext";
import { ArtIcon } from "../../components/ArtIcon";
import { BellIcon } from "../../components/icons";
import type {
  BlockSettingValue,
  BlockSize,
  StoredBlockEntry,
} from "../../lib/usePageLayout";
import { CustomWidgetBody } from "./CustomWidgetBody";
import {
  CUSTOM_MODULE_BY_ID,
  isCustomKey,
  parseCustomSettings,
} from "./homeAspects";
import { ALL_ACCOUNT_TYPES, type AccountType } from "./accountTypes";
import {
  HOME_WIDGET_ORDER,
  HOME_WIDGETS,
  HomeWidget,
} from "./homeWidgets";
import { HowToVideosBlock } from "./HowToVideosBlock";
import { QuickReportsBlock } from "./QuickReportsBlock";
import { NotificationsBlock } from "./NotificationsBlock";
import { HomeBoardWidget } from "../feedback/HomeBoardWidget";
import {
  AdminBoardWidget,
  AdminForumModeratorWidget,
  AdminSiteStatsWidget,
  AdminTicketsWidget,
} from "./AdminWidgets";
import type { EffectiveModule } from "./MyModules";

/**
 * THE HOME REGISTRY (dashboard redesign, owner-approved design
 * 2026-11-10, Lane 1 — the shell). ONE list of every box that can
 * live on Home, built per seat from the same gates the old
 * CorePage assembly applied inline: Home renders from it, the Add
 * gallery reads it, and the Settings page's old hand-mirrored
 * lists (HOME_BLOCKS / WIDGET_BLOCK_DEFAULTS / RUNG_HOME_DEFAULTS)
 * are gone — this file is the single source the whole system
 * agrees on.
 *
 * An entry's `key` is the STABLE stored-layout key (never
 * rename: saved arrangements, the one-time stats reset, and the
 * panel pseudo-entry all speak these keys). `render` draws the
 * box's body inside the shell's chrome; bodies are the same
 * components Home has always rendered, in their live (never
 * "editing") mode — the shell's chrome never flips a body into a
 * dead state, so a box's links and actions work at all times.
 */

/** A registry box resolved against the user's stored entry:
 *  the width and options bundle the body renders with (the
 *  hiddenStats/statOrder fields are the retired stats widget's
 *  stored extras, carried for shape compatibility). Mirrors the
 *  layout store's ResolvedBlock field-for-field, minus the def
 *  itself. */
export interface ResolvedHomeEntry {
  key: string;
  visible: boolean;
  size: BlockSize;
  settings: Record<string, BlockSettingValue>;
  hiddenStats: string[];
  statOrder: string[];
}

/** What a body render may read about its own stored entry.
 *  The shell owns the layout state; renders stay pure reads.
 *  (Lane 3 retired the stats widget — its two writers went with
 *  it; the header stats' writers live in the shell now.) */
export interface HomeBoxAccess {
  entryFor: (key: string) => ResolvedHomeEntry | undefined;
}

export interface HomeRegistryEntry {
  /** Stable stored-layout key. Never rename. */
  key: string;
  /** Localized display title (gallery card + control names). */
  title: string;
  /** Gallery icon. */
  icon: ReactNode;
  /** Gallery group id (the account group first, admin last). */
  group: string;
  /** Localized gallery group label. */
  groupLabel: string;
  /** Gallery one-line description (dictionary key). */
  descKey: DictKey;
  /** Registered default width until the user chooses otherwise. */
  defaultSize: BlockSize;
  /** Account groups this box serves (union rule; the downloads
   *  rung's assembly is level-scoped and skips this filter). */
  groups: AccountType[];
  /** ISO date the widget joined the registry — inside its first
   *  week the gallery card wears NEW and the Add button a dot
   *  (§3.11 of the design). */
  newSince?: string;
  render: (access: HomeBoxAccess) => ReactNode;
}

/** The seat facts the registry build reads. Structural on
 *  purpose: AuthContext's user satisfies it as-is. */
export interface HomeSeatUser {
  tier?: string | null;
  account_types: AccountType[];
  is_operator?: boolean | null;
}

export interface HomeRegistryArgs {
  user: HomeSeatUser | null;
  modules: EffectiveModule[] | null;
  access: HomeBoxAccess;
}

/** The dealer dashboard lives in the dealers module and is
 *  lazy-loaded so non-dealer accounts never pay for it (and the
 *  module stays removable from core's side of the fence). */
const DealerDashboardLazy = lazy(() => import("../dealers/DealerDashboard"));

/** Gallery description keys for the module widgets, by module id. */
const MODULE_DESC_KEYS: Record<string, DictKey> = {
  inventory: "home.gallery.desc.inventory",
  marketplace: "home.gallery.desc.marketplace",
  borrowing: "home.gallery.desc.borrowing",
  maintenance: "home.gallery.desc.maintenance",
  disaster_claims: "home.gallery.desc.disasterClaims",
  messaging: "home.gallery.desc.messaging",
  parts: "home.gallery.desc.parts",
  shared_tools: "home.gallery.desc.sharedTools",
  dealers: "home.gallery.desc.dealers",
  flyers: "home.gallery.desc.flyers",
  reports: "home.gallery.desc.reports",
  forum: "home.gallery.desc.forum",
  wishlist: "home.gallery.desc.wishlist",
  tool_expansion: "home.gallery.desc.toolExpansion",
  truck_accounts: "home.gallery.desc.truckAccounts",
  feedback: "home.gallery.desc.feedback",
  support: "home.gallery.desc.support",
  prints: "home.gallery.desc.prints",
};

/**
 * Build the seat's registry: every box this user may see, add, or
 * hold — already reach-gated. Assembly order is the historical
 * CorePage order (it is also the gallery's group order and the
 * order unstored boxes would seat in).
 */
export function buildHomeRegistry({
  user,
  modules,
  access,
}: HomeRegistryArgs): HomeRegistryEntry[] {
  const t = useT();
  const navLabel = useNavLabel();
  const moduleById = new Map<string, EffectiveModule>(
    (modules ?? []).map((m) => [m.id, m]),
  );
  const widgetTitle = (m: EffectiveModule): string => {
    if (!m.nav) {
      // No nav door of its own (support): the widget borrows the
      // Help & Support page's identity via the def's path.
      const door = HOME_WIDGETS[m.id]?.path;
      const reg = door ? MODULES.find((r) => r.path === door) : undefined;
      return reg ? navLabel(reg.name, t("help.title")) : m.name;
    }
    const reg = MODULES.find((r) => r.path === m.nav!.path);
    return reg ? navLabel(reg.name, m.nav.label) : m.nav.label;
  };
  const widgetGroups = (m: EffectiveModule): AccountType[] => {
    const door = m.nav?.path ?? HOME_WIDGETS[m.id]?.path;
    if (!door) return ALL_ACCOUNT_TYPES;
    const reg = MODULES.find((r) => r.path === door);
    return reg ? reg.groups : ALL_ACCOUNT_TYPES;
  };
  const moduleGroupLabel = (id: string, fallback: string): string => {
    const m = moduleById.get(id);
    return m ? widgetTitle(m) : fallback;
  };

  const isDownloadsLevel = user?.tier === "downloads";

  const accountPlanEntry: HomeRegistryEntry = {
    key: "account_plan",
    title: t("home.widget.accountPlan.title"),
    icon: HOME_WIDGETS["account_plan"]?.icon,
    group: "account",
    groupLabel: t("home.gallery.group.account"),
    descKey: "home.gallery.desc.accountPlan",
    defaultSize: "half",
    groups: ALL_ACCOUNT_TYPES,
    render: () => (
      <HomeWidget
        moduleId="account_plan"
        title={t("home.widget.accountPlan.title")}
        path={
          user?.tier === "downloads" ? "/settings/profile" : "/settings/billing"
        }
        editing={false}
        size={access.entryFor("account_plan")?.size ?? "half"}
        settings={access.entryFor("account_plan")?.settings}
      />
    ),
  };

  const converterEntry: HomeRegistryEntry = {
    key: "widget:converter",
    title: t("downloads.conv.title"),
    icon: HOME_WIDGETS["converter"]?.icon,
    group: "downloads",
    groupLabel: t("downloads.title"),
    descKey: "home.gallery.desc.converter",
    defaultSize: "half",
    groups: ALL_ACCOUNT_TYPES,
    render: () => (
      <HomeWidget
        moduleId="converter"
        title={t("downloads.conv.title")}
        path="/downloads#documents"
        editing={false}
        size={access.entryFor("widget:converter")?.size ?? "half"}
        settings={access.entryFor("widget:converter")?.settings}
      />
    ),
  };

  const downloadsEntry: HomeRegistryEntry = {
    key: "widget:downloads",
    title: t("downloads.title"),
    icon: HOME_WIDGETS["downloads"]?.icon,
    group: "downloads",
    groupLabel: t("downloads.title"),
    descKey: "home.gallery.desc.downloads",
    defaultSize: "half",
    groups: ALL_ACCOUNT_TYPES,
    render: () => (
      <HomeWidget
        moduleId="downloads"
        title={t("downloads.title")}
        path="/downloads"
        editing={false}
        size={access.entryFor("widget:downloads")?.size ?? "half"}
        settings={access.entryFor("widget:downloads")?.settings}
      />
    ),
  };

  if (isDownloadsLevel) {
    // The downloads level's registry (open signup model): its
    // whole world is the Downloads shelf, 3D Print Files, the
    // Converter, and Account & Plan — the level's reach, nothing
    // beyond it. (Its stats live in the header now, like every
    // seat's — Lane 3 retired the stats widget for all levels.)
    return [
      downloadsEntry,
      {
        key: "widget:prints",
        title: t("prints.title"),
        icon: HOME_WIDGETS["prints"]?.icon,
        group: "prints",
        groupLabel: t("prints.title"),
        descKey: "home.gallery.desc.prints",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <HomeWidget
            moduleId="prints"
            title={t("prints.title")}
            path="/3dprints"
            editing={false}
            size={access.entryFor("widget:prints")?.size ?? "half"}
            settings={access.entryFor("widget:prints")?.settings}
          />
        ),
      },
      converterEntry,
      accountPlanEntry,
    ];
  }

  const entries: HomeRegistryEntry[] = [];

  // How-to videos: gated on the support module, the videos' own
  // module (the same gate as the Help page's videos tab).
  if (moduleById.has("support")) {
    entries.push({
      key: "howto_videos",
      title: t("help.tab.videos"),
      icon: <ArtIcon name="videos" size={22} />,
      group: "support",
      groupLabel: moduleGroupLabel("support", t("help.title")),
      descKey: "home.gallery.desc.howto",
      defaultSize: "full",
      groups: ALL_ACCOUNT_TYPES,
      render: () => <HowToVideosBlock editing={false} />,
    });
  }

  // Dealer dashboard: dealer-group only; multi-group accounts
  // see it alongside everything else (group gate applied by the
  // shell's resolution, as before).
  entries.push({
    key: "dealer_dashboard",
    title: "Dealer dashboard",
    icon: <ArtIcon name="dealers" size={22} />,
    group: "dealers",
    groupLabel: moduleGroupLabel("dealers", t("nav.dealers")),
    descKey: "home.gallery.desc.dealerDashboard",
    defaultSize: "full",
    groups: ["tool_dealer"],
    render: () => (
      <Suspense fallback={null}>
        <DealerDashboardLazy
          settings={access.entryFor("dealer_dashboard")?.settings ?? {}}
        />
      </Suspense>
    ),
  });

  entries.push({
    key: "notifications",
    title: t("home.notifications"),
    icon: <BellIcon size={20} />,
    group: "account",
    groupLabel: t("home.gallery.group.account"),
    descKey: "home.gallery.desc.notifications",
    defaultSize: "full",
    groups: ALL_ACCOUNT_TYPES,
    render: () => (
      <NotificationsBlock
        editing={false}
        settings={access.entryFor("notifications")?.settings}
      />
    ),
  });

  // The two board widgets, gated on the feedback module — the
  // same module that gates the boards themselves.
  if (moduleById.has("feedback")) {
    entries.push(
      {
        key: "bug_reports",
        title: t("home.widget.boardBugs"),
        icon: <ArtIcon name="warning" size={22} />,
        group: "feedback",
        groupLabel: moduleGroupLabel("feedback", t("nav.feedback")),
        descKey: "home.gallery.desc.bugReports",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => <HomeBoardWidget board="bug" editing={false} />,
      },
      {
        key: "feature_requests",
        title: t("home.widget.boardFeatures"),
        // Sweep B1 (01-F9): each board wears its OWN rendered icon —
        // Feature Requests takes the lightbulb (the admin board's
        // artwork), not the ladybug the Feedback widget already wears.
        icon: <ArtIcon name="adminFeature" size={22} />,
        group: "feedback",
        groupLabel: moduleGroupLabel("feedback", t("nav.feedback")),
        descKey: "home.gallery.desc.featureRequests",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => <HomeBoardWidget board="feature" editing={false} />,
      },
    );
  }

  // Quick Reports, gated on the reports module — reach is
  // whoever can reach Reports.
  if (moduleById.has("reports")) {
    entries.push({
      key: "quick_reports",
      title: t("reports.page.quickTitle"),
      icon: <ArtIcon name="reports" size={22} />,
      group: "reports",
      groupLabel: moduleGroupLabel("reports", t("reports.page.title")),
      descKey: "home.gallery.desc.quickReports",
      defaultSize: "half",
      groups: ALL_ACCOUNT_TYPES,
      render: () => (
        <QuickReportsBlock
          editing={false}
          settings={access.entryFor("quick_reports")?.settings ?? {}}
        />
      ),
    });
  }

  // HomeWidget-frame specials, each gated on its own module
  // exactly as the old assembly gated them.
  const homeWidgetSpecial = (
    key: string,
    moduleId: string,
    gateModule: string,
    title: string,
    path: string,
    group: string,
    groupFallback: string,
    descKey: DictKey,
  ): HomeRegistryEntry => ({
    key,
    title,
    icon: HOME_WIDGETS[moduleId]?.icon,
    group,
    groupLabel: moduleGroupLabel(gateModule, groupFallback),
    descKey,
    defaultSize: "half",
    groups: ALL_ACCOUNT_TYPES,
    render: () => (
      <HomeWidget
        moduleId={moduleId}
        title={title}
        path={path}
        editing={false}
        size={access.entryFor(key)?.size ?? "half"}
        settings={access.entryFor(key)?.settings}
      />
    ),
  });
  if (moduleById.has("dealers")) {
    entries.push(
      homeWidgetSpecial(
        "dealers_near_you",
        "dealers_near_you",
        "dealers",
        t("home.widget.dealersNear.title"),
        "/dealers/find-agent",
        "dealers",
        t("nav.dealers"),
        "home.gallery.desc.dealersNearYou",
      ),
    );
  }
  if (moduleById.has("inventory")) {
    entries.push(
      homeWidgetSpecial(
        "health_checks_due",
        "health_checks_due",
        "inventory",
        t("home.widget.health.title"),
        "/inventory/health",
        "inventory",
        t("nav.inventory"),
        "home.gallery.desc.healthChecksDue",
      ),
      homeWidgetSpecial(
        "quick_add",
        "quick_add",
        "inventory",
        t("home.widget.quickAdd.title"),
        "/inventory/new",
        "inventory",
        t("nav.inventory"),
        "home.gallery.desc.quickAdd",
      ),
    );
  }

  entries.push(accountPlanEntry, converterEntry, downloadsEntry);

  // The five ADMIN widgets: god + moderator_admin seats ONLY —
  // the entries are assembled only when the seat passes, so the
  // boxes never exist for lower tiers anywhere: not on the page,
  // not in the gallery. Their data endpoints refuse lower tiers
  // too (defense in depth).
  const isAdminSeat = Boolean(
    user &&
      (user.is_operator || user.tier === "god" || user.tier === "moderator_admin"),
  );
  if (isAdminSeat) {
    const adminGroup = {
      group: "admin",
      groupLabel: t("home.gallery.group.admin"),
    };
    entries.push(
      {
        key: "admin_tickets",
        title: t("home.widget.adminTickets"),
        icon: <ArtIcon name="adminTickets" size={22} />,
        ...adminGroup,
        descKey: "home.gallery.desc.adminTickets",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <AdminTicketsWidget
            editing={false}
            settings={access.entryFor("admin_tickets")?.settings}
          />
        ),
      },
      {
        key: "admin_bug_reports",
        title: t("home.widget.adminBugReports"),
        icon: <ArtIcon name="adminBug" size={22} />,
        ...adminGroup,
        descKey: "home.gallery.desc.adminBugReports",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <AdminBoardWidget
            board="bug"
            editing={false}
            settings={access.entryFor("admin_bug_reports")?.settings}
          />
        ),
      },
      {
        key: "admin_feature_requests",
        title: t("home.widget.adminFeatureRequests"),
        icon: <ArtIcon name="adminFeature" size={22} />,
        ...adminGroup,
        descKey: "home.gallery.desc.adminFeatureRequests",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <AdminBoardWidget
            board="feature"
            editing={false}
            settings={access.entryFor("admin_feature_requests")?.settings}
          />
        ),
      },
      {
        key: "admin_forum_moderator",
        title: t("home.widget.adminForumModerator"),
        icon: <ArtIcon name="adminForum" size={22} />,
        ...adminGroup,
        descKey: "home.gallery.desc.adminForumModerator",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <AdminForumModeratorWidget
            editing={false}
            settings={access.entryFor("admin_forum_moderator")?.settings}
          />
        ),
      },
      {
        key: "admin_site_stats",
        title: t("home.widget.adminSiteStats"),
        icon: <ArtIcon name="adminStats" size={22} />,
        ...adminGroup,
        descKey: "home.gallery.desc.adminSiteStats",
        defaultSize: "half",
        groups: ALL_ACCOUNT_TYPES,
        render: () => (
          <AdminSiteStatsWidget
            editing={false}
            settings={access.entryFor("admin_site_stats")?.settings}
          />
        ),
      },
    );
  }

  // One LIVE WIDGET block per effective module, in the standing
  // order — the same filter the old assembly applied (a def-path
  // module must not slip through on its path alone during the
  // modules loading window: moduleById is empty then, and this
  // whole list is rebuilt when the modules land).
  for (const id of HOME_WIDGET_ORDER) {
    const def = HOME_WIDGETS[id];
    const m = moduleById.get(id);
    if (!def || !m) continue;
    if (!(m.nav || (moduleById.has(id) && def.path))) continue;
    const door = m.nav?.path ?? def.path!;
    const title = widgetTitle(m);
    entries.push({
      key: `widget:${id}`,
      title,
      icon: def.icon,
      group: id,
      groupLabel: title,
      descKey: MODULE_DESC_KEYS[id] ?? "home.gallery.desc.stats",
      defaultSize: "half",
      groups: widgetGroups(m),
      render: () => (
        <HomeWidget
          moduleId={id}
          title={title}
          path={door}
          editing={false}
          size={access.entryFor(`widget:${id}`)?.size ?? "half"}
          settings={access.entryFor(`widget:${id}`)?.settings}
        />
      ),
    });
  }

  return entries;
}

/** Re-exported for the shell's save composition: the raw stored
 *  entry shape the layout store speaks. */
export type { StoredBlockEntry };

/**
 * CUSTOM BOX ENTRIES (Lane 2, design §3.6). A stored
 * `custom:<id>` entry becomes a registry entry of its own —
 * built from its settings bundle, not from the predefined
 * catalog. The module must still be in the seat's reach: its
 * HOST predefined entry must be among the eligible keys, the
 * same gate the predefined box itself obeys, so a box whose
 * module leaves the seat's reach stops rendering while its
 * stored entry rides through saves untouched (Lane 1's rule
 * for every box). The display name is the user's own name
 * when they set one, else the host entry's localized title —
 * so an unnamed box follows the seat's language.
 */
export function buildCustomEntries(args: {
  stored: StoredBlockEntry[];
  eligibleKeys: Set<string>;
  access: HomeBoxAccess;
  host: (hostKey: string) =>
    | { title: string; defaultSize: BlockSize; groupLabel: string }
    | undefined;
}): HomeRegistryEntry[] {
  const { stored, eligibleKeys, access, host } = args;
  const out: HomeRegistryEntry[] = [];
  for (const block of stored) {
    if (!isCustomKey(block.key)) continue;
    // The wire shape stores settings opaquely; the parsers
    // below validate every leaf they consume.
    const settings = (block.settings ?? {}) as Record<
      string,
      BlockSettingValue
    >;
    const parsed = parseCustomSettings(settings);
    if (!parsed) continue;
    const mod = CUSTOM_MODULE_BY_ID[parsed.moduleId];
    if (!mod || !eligibleKeys.has(mod.hostKey)) continue;
    const hostEntry = host(mod.hostKey);
    const key = block.key;
    const title = parsed.name ?? hostEntry?.title ?? mod.id;
    out.push({
      key,
      title,
      descKey: "home.custom.desc",
      icon: mod.icon,
      group: "widgets",
      groupLabel: hostEntry?.groupLabel ?? "",
      defaultSize: hostEntry?.defaultSize ?? "full",
      groups: ALL_ACCOUNT_TYPES,
      render: () => (
        <CustomWidgetBody
          moduleId={parsed.moduleId}
          name={title}
          picks={parsed.picks}
          stored={settings}
          size={access.entryFor(key)?.size ?? "full"}
        />
      ),
    });
  }
  return out;
}
