import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import {
  BrowserRouter,
  Link,
  matchPath,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  AppShell,
  ErrorBoundary,
  PageSkeleton,
  PillTipHost,
  ToastProvider,
  UserMenu,
  type ShellNavItem,
} from "./components";
import { ArtIcon } from "./components/ArtIcon";
import { PageNavBar } from "./components/PageNavBar";
import { panelForRoute } from "./components/panels/registry";
import ScrollManager from "./components/ScrollManager";
import { NavTrailProvider } from "./lib/navTrail";
import { api, TOKEN_KEY } from "./lib/api";
import { useNavBadges } from "./lib/useNavBadges";
import { SIDE_PANEL_ENABLED } from "./lib/shellFlags";
import {
  accountTypeSummary,
  staffTier,
} from "./modules/core/accountTypes";
import { AuthProvider, useAuth } from "./modules/core/AuthContext";
import {
  groupLayerWaived,
  OnboardingProvider,
  useOnboarding,
} from "./modules/core/onboarding";
import {
  TeaserProvider,
  TeaserWall,
  useTeaserBareChrome,
} from "./modules/core/teaser";
import {
  ModuleGate,
  MyModulesProvider,
  useMyModules,
  UserOffGate,
} from "./modules/core/MyModules";
import {
  HeaderVariantProvider,
  useHeaderVariant,
} from "./theme/HeaderVariantContext";
import {
  settingsSectionsFor,
  type SettingsGroup,
} from "./modules/core/settingsMeta";
import { LayoutProvider, useLayout } from "./theme/LayoutContext";
import { ThemeProvider } from "./theme/ThemeContext";
import { MODULES } from "./modules/registry";
import { LocaleProvider, useNavLabel, useT } from "./i18n/LocaleContext";

/**
 * TESTING (owner order, 2026-11-08): the header Testing item
 * lives in src/testing and is LAZY, so a signed-out visitor
 * never downloads a byte of it (the item renders only for a
 * signed-in STAFF account — god / moderator_admin /
 * moderator, owner order 2026-11-09). It began as the landing-test options
 * dropdown; the tests ended with Option 1's promotion to the
 * official landing page, and the item is now a plain link
 * straight to the landing page ("/landing"), kept in the
 * header for future test programs. Delete this import, the
 * testingMenu node below, and the AppShell prop together if
 * the owner ever retires the item for good.
 */
const TestingMenu = lazy(() => import("./testing/TestingMenu"));

/**
 * The PUBLIC module family (per-user module switches, 2026-10-24):
 * registry routes that deliberately carry NO featureModule because
 * reading is public (signed-out visitors read the same pages), each
 * mapped to the feature module it belongs to. A signed-in user who
 * turned that module off loses it anyway: the nav item hides and
 * the route lands on the turned-off panel (UserOffGate). Routes
 * WITH a featureModule are not listed — ModuleGate + my-modules
 * already hide them end to end.
 */
const PUBLIC_FAMILY: Record<string, string> = {
  "parts-community": "parts",
  marketplace: "marketplace",
  "marketplace-listing": "marketplace",
  forum: "forum",
  "forum-category": "forum",
  "forum-thread": "forum",
  feedback: "feedback",
  "feedback-bugs": "feedback",
  "feedback-features": "feedback",
  "feedback-post": "feedback",
  "downloads-prints": "prints",
  "downloads-prints-detail": "prints",
  "dealers-find-agent": "dealers",
};

/** Header user menu, fed by auth state. Lives here (not in the shell)
 *  because it needs the auth + router context. Logging out navigates
 *  to /login explicitly: the login card must render cleanly every
 *  time, not depend on whichever protected page happens to redirect
 *  after the session is torn down. */
/* 3D print files (owner, 2026-11-08 21:03): the shelf's canonical
 * seat is the clean top-level /3dprints; a legacy file link under
 * /downloads/prints lands on the same record at its canonical
 * address. */
function PrintsLegacyDetailRedirect() {
  const { fileId } = useParams();
  return <Navigate to={`/3dprints/${fileId ?? ""}`} replace />;
}

function PrintsLegacyEditRedirect() {
  const { fileId } = useParams();
  return <Navigate to={`/3dprints/${fileId ?? ""}/edit`} replace />;
}

function HeaderUserMenu() {
  const t = useT();
  const { user, loading, logout } = useAuth();
  const { modules: effectiveModules } = useMyModules();
  const navigate = useNavigate();
  if (loading) return null;
  // Settings follow reach (2026-11-09): the account links are
  // the registry's sections filtered by the caller's effective
  // modules too — an unreached module's settings never appear
  // here, exactly as they don't appear as tabs on the page.
  const moduleIds: ReadonlySet<string> = new Set(
    (effectiveModules ?? []).map((m) => m.id),
  );
  return (
    <UserMenu
      user={
        user
          ? {
              name: user.name,
              email: user.email,
              accountNumber: user.account_number,
              /* The Home side panel's account box, relocated
               * into this menu (owner, 2026-11-01): the same
               * group summary and location the panel rendered
               * (public area label, else country), from the
               * same auth user the panel read. Permanent —
               * not tied to the side-panel flag. */
              group: accountTypeSummary(user.account_types),
              location: user.public_area_label || user.country || "",
            }
          : null
      }
      accountLinks={
        user
          ? settingsSectionsFor(
              "account",
              user.account_types,
              moduleIds,
              groupLayerWaived(user),
            ).map((s) => ({
              label: t(`settings.section.${s.id}` as never),
              path: `/settings/${s.id}`,
            }))
          : []
      }
      adminPath={
        user?.is_operator
          ? "/admin"
          : user?.tier === "moderator_admin"
            ? "/admin/users"
            : null
      }
      onLogout={() => {
        logout();
        navigate("/login", { replace: true });
      }}
    />
  );
}

/**
 * The completion gate: a signed-in account missing any of its bare
 * bones — an EMPTY group set (every social-login account, every
 * pre-group legacy account) or the signup BASICS (country unset:
 * social-login and pre-basics legacy accounts; owner directive
 * 2026-10-22) — is routed to the one-time completion screen before
 * any app page. Accounts that have everything are never
 * redirected — no loop. Signed-out visitors are untouched.
 *
 * A group-waived account (the downloads level) holds no group
 * set BY DESIGN, so its bare bones are the basics alone — the
 * gate never marches it to a picker it cannot use.
 */
function AccountTypeGate() {
  const { user, loading } = useAuth();
  const {
    plan,
    loading: planLoading,
  } = useOnboarding();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (loading || !user) return;
    const incomplete =
      (!groupLayerWaived(user) && user.account_types.length === 0) ||
      !user.country;
    if (!incomplete) return;
    // Onboarding (owner design 2026-10-31, built 2026-11-07): an
    // account born into the wizard is NEVER force-marched through
    // the classic completion page — it lands on the bare Home and
    // the setup banner walks it through instead. While the plan
    // is still loading, hold (no redirect either way). A failed
    // plan read (plan null once loading settles) falls back to
    // the classic gate, and pre-wizard (legacy) accounts keep it
    // exactly as before.
    if (plan?.flow === "wizard") return;
    if (planLoading && !plan) return;
    if (location.pathname !== "/choose-group") {
      navigate("/choose-group", { replace: true });
    }
  }, [user, loading, plan, planLoading, location.pathname, navigate]);
  return null;
}

/**
 * The SETTINGS TREE (owner directive 2026-10-22): raised in
 * place by the main menu's Settings switch, the ONE left menu
 * column belongs to Settings — never a second menu column
 * beside the main one. (Until 2026-11-03 it also raised on
 * /settings/* routes; the Settings page's own tabs carry
 * section navigation there now, by the owner's main-tab-layout
 * order, and the tree remains for the switch.) The tree is a back arrow
 * over two expandable groups — Site settings on TOP, Account
 * settings BELOW it (owner Phase C, 2026-10-24: his earlier spec,
 * finally switched) — whose headers drop down their section
 * links. The groups come from the same settings registry the
 * gear menu reads, so visibility (dealer/shop/insurer gates,
 * multi-group union) can never drift. Groups expand and collapse
 * independently.
 *
 * Arrival default (owner Phase C): every FRESH raise of the tree
 * starts with Site settings OPEN and Account settings CLOSED.
 * Two refinements ride along: arriving ON a section (a route)
 * opens that section's group instead, so the active leaf is
 * visible; and a user who rates only ONE group starts with that
 * sole group open. Flips the user makes while the tree stays
 * raised persist for that view; the tree unmounts when the panel
 * flips back to the main menu (or navigates away), so re-raising
 * it remounts fresh and the arrival default applies again.
 *
 * Menu-behavior rule (owner 2026-10-23): the tree is also raised
 * IN PLACE by the main menu's Settings switch, from any page, with
 * no navigation — Settings is a menu, not a page. The back arrow
 * is the same kind of control: it flips the column back to the
 * main menu in place (it used to link home, which teleported the
 * user off their settings page just to change menus). Only the
 * tree's leaf links ever navigate.
 *
 * Rail Steel Phase 3 (2026-10-23): the tree's markup classes are
 * unchanged in structure — the railsteel.css Phase 3 block skins
 * it in the panel language (Back as the top panel item, groups
 * as panel group headers, leaves as panel items with the active
 * leaf on the accent plate; NavLink supplies aria-current).
 * The preview's stacked label+hint leaves are NOT used: the
 * settings registry (settingsMeta) carries labels only, no
 * descriptive hint text, and none was invented.
 */
/**
 * RELEASE FIRST-ENTRY ROUTING (2026-11-09, point 7 of the open
 * signup model): when an admin's tier flip opens a module to an
 * account that didn't have it, the flip writes a pending
 * onboarding row for that module (module_release.py). The first
 * time the user then lands on a route that module owns, this
 * gate sends them through the setup wizard scoped to exactly
 * that module — /setup?step=module:<id>. A typeless account on
 * a group-layer rung meets the wizard's type lock there and is
 * routed through the account-type step first (the server-deep
 * rule stands); a group-waived account (the downloads level)
 * has no account-type step at all, so it lands on the module
 * step directly — that step is its whole wizard for the flip.
 * Once per session per module (sessionStorage), never when the
 * wizard was dismissed, and never from the setup/settings
 * surfaces themselves. The wizard is not rebuilt: this is a
 * router in front of the step the plan already carries.
 */
function ReleaseWizardGate() {
  const { user } = useAuth();
  const { plan } = useOnboarding();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (!user || !plan || plan.dismissed) return;
    const path = location.pathname;
    if (
      path.startsWith("/setup") ||
      path.startsWith("/settings") ||
      path.startsWith("/login") ||
      path.startsWith("/signup")
    ) {
      return;
    }
    const storageKey = `tv:release-routed:${user.id}`;
    let routed: string[] = [];
    try {
      routed = JSON.parse(sessionStorage.getItem(storageKey) ?? "[]");
    } catch {
      routed = [];
    }
    // Walk the plan's NEW module steps and ask whether the
    // current route belongs to one of them. Ownership comes
    // from the route's featureModule declaration — or, for the
    // public-reading family whose routes deliberately declare
    // none (the forum is the case), from the route's registry
    // name, which is the module's own key (forum, forum-*).
    for (const step of plan.steps) {
      if (step.kind !== "module" || !step.module_id) continue;
      if (!(step.new === true || step.status === "notified")) continue;
      if (step.status === "done" || step.status === "skipped") continue;
      const moduleId = step.module_id;
      if (routed.includes(moduleId)) continue;
      const owned = MODULES.some((m) => {
        if (!m.path) return false;
        const belongs =
          m.featureModule === moduleId ||
          (m.featureModuleAnyOf ?? []).includes(moduleId) ||
          m.name === moduleId ||
          m.name.startsWith(`${moduleId}-`);
        return belongs && matchPath({ path: m.path, end: true }, path);
      });
      if (!owned) continue;
      routed.push(moduleId);
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(routed));
      } catch {
        /* a full/blocked storage must not break navigation */
      }
      navigate(`/setup?step=module:${moduleId}`, { replace: true });
      return;
    }
  }, [user, plan, location.pathname, navigate]);

  return null;
}

function SettingsSidebarTree({
  userTypes,
  moduleIds,
  bareRung,
  onBackToMenu,
}: {
  userTypes: string[];
  moduleIds: ReadonlySet<string>;
  bareRung: boolean;
  onBackToMenu: () => void;
}): ReactNode {
  const t = useT();
  const location = useLocation();
  const activeId = location.pathname.split("/")[2] ?? "";
  // Site settings is the TOP group, Account settings below it
  // (owner Phase C arrival spec).
  const groups: { key: SettingsGroup; label: string }[] = [
    { key: "site", label: t("shell.siteSettings") },
    { key: "account", label: t("shell.accountSettings") },
  ];
  const permittedGroups = groups.filter(
    (g) => settingsSectionsFor(g.key, userTypes, moduleIds, bareRung).length > 0,
  );
  const activeGroup = groups.find((g) =>
    settingsSectionsFor(g.key, userTypes, moduleIds, bareRung).some(
      (s) => s.id === activeId,
    ),
  )?.key;
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  // Arriving on a section (a gear-menu deep link, a group switch)
  // opens its group — without closing one the user opened by hand.
  useEffect(() => {
    if (activeGroup) {
      setOpenGroups((g) => (g[activeGroup] ? g : { ...g, [activeGroup]: true }));
    }
  }, [activeGroup]);
  return (
    <>
      <button
        type="button"
        className="tv-nav-item tv-nav-back tv-nav-switch-btn tv-settings-back"
        aria-expanded={true}
        aria-controls="tv-panel"
        onClick={onBackToMenu}
      >
        <span aria-hidden="true">←</span>
        <span>{t("shell.backToMenu")}</span>
      </button>
      {groups.map((group) => {
        const sections = settingsSectionsFor(
          group.key,
          userTypes,
          moduleIds,
          bareRung,
        );
        if (sections.length === 0) return null;
        // Arrival default (owner Phase C): the active section's
        // group when arriving on a section; otherwise Site
        // settings open / Account settings closed — unless the
        // user rates only ONE permitted group, which starts open
        // (it is the whole tree). Explicit flips in openGroups
        // win over every default while this raise lasts.
        const open =
          openGroups[group.key] ??
          (activeGroup
            ? group.key === activeGroup
            : permittedGroups.length === 1
              ? true
              : group.key === "site");
        return (
          <div key={group.key} className="tv-nav-group">
            <button
              type="button"
              className={`tv-nav-item tv-nav-group-btn tv-settings-group-btn${open ? " is-open" : ""}`}
              aria-expanded={open}
              onClick={() =>
                setOpenGroups((g) => ({ ...g, [group.key]: !open }))
              }
            >
              <span>{group.label}</span>
              <span className="tv-nav-group-caret" aria-hidden="true">
                ▾
              </span>
            </button>
            {/* Always mounted: the wrap's 0fr/1fr grid track is
             * what animates the expand/collapse (surfaces.css
             * .tv-nav-sub-wrap); unmounting on close would snap
             * shut with no animation at all. aria-hidden follows
             * the open state, and the wrap's visibility transition
             * keeps a closed group's links out of the tab order. */}
            <div
              className={`tv-nav-sub-wrap${open ? " is-open" : ""}`}
              aria-hidden={!open}
            >
              <div className="tv-nav-sub">
                {sections.map((s) => (
                  <NavLink
                    key={s.id}
                    to={`/settings/${s.id}`}
                    className={({ isActive }) =>
                      `tv-nav-item tv-nav-item--sub tv-settings-leaf${isActive ? " is-active" : ""}`
                    }
                  >
                    <span>{t(`settings.section.${s.id}` as never)}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}

/**
 * App shell: theme tokens + module routes from the registry.
 * Nav is configuration-driven (blueprint Law 7) — MODULES order and
 * visibility decide the sidebar; the shell just renders it. Nav
 * entries also filter by the signed-in user's group set (UNION: an
 * entry shows when any of the user's groups is in its `groups`).
 * Signed-out visitors see NO nav at all (owner ruling 2026-10-17:
 * no menu items before sign-in) — the shell renders without a
 * sidebar and the content takes the full width. While a stored
 * token is still being validated the nav stays as it was, so a
 * returning user's shell doesn't flicker; the pages themselves
 * enforce sign-in either way.
 */
function Shell() {
  const { user, loading, refreshUser } = useAuth();
  const { plan: onboardingPlan } = useOnboarding();
  /* Pre-setup (sweep 10-F3): a wizard-flow account that has not
   * picked its type yet. The header cluster holds its bell and
   * search for exactly this state — both are inert until a type
   * exists (no records to search, an inbox empty by
   * construction) — and releases them the moment a type is
   * picked. Group-waived accounts (the downloads level) never
   * pick a type BY DESIGN and keep their full chrome: their
   * search and inbox serve the modules they do reach. While
   * the plan is unread the chrome renders as today, so a
   * settled account never flickers. */
  const preSetup =
    !!user &&
    onboardingPlan?.flow === "wizard" &&
    !groupLayerWaived(user) &&
    user.account_types.length === 0;
  const navLabel = useNavLabel();
  const t = useT();
  const location = useLocation();
  /* Sidebar menu mode (menu-behavior rule, owner 2026-10-23):
   * the column shows either the main menu or the settings tree.
   * The tree raises only when the user flips it in place with
   * the Settings switch (the side-panel arrangement); routes no
   * longer raise it — since the Settings page became a main tab
   * layout (owner order, 2026-11-03), its tabs carry section
   * navigation on /settings/* and the rail keeps the main menu
   * there, like every other page. The override is deliberately
   * shallow state: ANY real navigation (a leaf click, a
   * gear-menu deep link, the logo, browser back/forward)
   * settles on a new pathname and clears it, so menu and page
   * can never disagree after a navigation. The two switch
   * clicks are the only mode changes that do not navigate —
   * and the only ones that keep the override. */
  const [menuOverride, setMenuOverride] = useState<
    "main" | "settings" | null
  >(null);
  useEffect(() => {
    setMenuOverride(null);
  }, [location.pathname]);
  const { layout } = useLayout();
  const { headerVariant } = useHeaderVariant();
  const myModules = useMyModules();
  const hasSession =
    !!user || (loading && !!localStorage.getItem(TOKEN_KEY));
  // NEW badges (release machinery, 2026-11-08): the item keys
  // inside their first week, from the server registry — the
  // map below stamps the pill on any of them that renders.
  const newBadges = useNavBadges(hasSession);
  const userTypes = user?.account_types ?? [];
  const nav = !hasSession
    ? []
    : [...MODULES]
        .filter((m) => m.showInNav !== false)
        .filter(
          (m) =>
            userTypes.length === 0 || m.groups.some((g) => userTypes.includes(g)),
        )
        // Feature modules (module doctrine, owner 2026-10-18) show
        // only while effective for this user per /core/my-modules —
        // the operator's switches, server-resolved. While that loads
        // they stay hidden: never flash a menu the user can't use.
        .filter((m) => !m.featureModule || myModules.has(m.featureModule))
        // AnyOf-gated entries (Repairs & Maintenance merge,
        // 2026-11-05) show while ANY of their modules is
        // effective — the merged page's tabs gate individually.
        .filter(
          (m) =>
            !m.featureModuleAnyOf ||
            m.featureModuleAnyOf.some((id) => myModules.has(id)),
        )
        // Public-family routes (no featureModule) follow the same
        // standard as feature modules in the signed-in nav: the
        // family module must be EFFECTIVE for this user — operator
        // layer and user layer, server-resolved via my-modules
        // (hidden-modules directive, 2026-10-31: an operator-parked
        // module leaves no nav sign; a user who turned it off loses
        // it too, as before). Public reading itself lives on the
        // signed-out surfaces (the landing's free-access cards,
        // which follow the modules' usable-anywhere state), not in
        // a signed-in menu.
        .filter((m) => {
          const family = PUBLIC_FAMILY[m.name];
          return !family || myModules.has(family);
        })
        .sort((a, b) => a.navOrder - b.navOrder)
        .map(
          (m): ShellNavItem => ({
            name: m.name,
            label: navLabel(m.name, m.label),
            path: m.path,
            icon: m.icon,
            ...(newBadges.has(m.name)
              ? {
                  badge: t("shell.newBadge"),
                  badgeClassName: "tv-rail-badge--new",
                }
              : {}),
          }),
        );
  const onSettingsRoute =
    location.pathname === "/settings" ||
    location.pathname.startsWith("/settings/");
  const menuMode = menuOverride ?? "main";
  // Settings is a first-class main-menu item — but a MENU SWITCH,
  // not a link (menu-behavior rule, owner 2026-10-23): Settings is
  // not a page, so clicking it must not load one. It flips the
  // sidebar into the settings tree in place — same page, same
  // scroll — and only a tree leaf navigates. Its `path` survives
  // as the conceptual prefix (active state reads off the route),
  // never as a destination. (The ACCOUNT sections also live under
  // the user's name; see HeaderUserMenu.)
  if (hasSession) {
    if (SIDE_PANEL_ENABLED) {
      nav.push({
        name: "core-settings",
        label: t("shell.settings"),
        path: "/settings",
        icon: <ArtIcon name="settings" />,
        onSelect: () => setMenuOverride("settings"),
        panelExpanded: menuMode === "settings",
        forceActive: onSettingsRoute,
        ...(newBadges.has("core-settings")
          ? { badge: t("shell.newBadge"), badgeClassName: "tv-rail-badge--new" }
          : {}),
      });
    } else {
      /* Side panel removed (owner, 2026-11-01; lib/shellFlags):
       * there is no panel for the Settings switch to flip the
       * settings tree into, so the item is a plain link to
       * /settings — which lands on the first site section, as
       * before. NavLink's own matching keeps it lit on every
       * /settings/* route. Restoring the panel restores the
       * switch above with it. */
      nav.push({
        name: "core-settings",
        label: t("shell.settings"),
        path: "/settings",
        icon: <ArtIcon name="settings" />,
        ...(newBadges.has("core-settings")
          ? { badge: t("shell.newBadge"), badgeClassName: "tv-rail-badge--new" }
          : {}),
      });
    }
  }
  // (The Testing disclosure that used to sit here — the 2026-10-23
  // design-concept previews — was removed on the owner's word,
  // 2026-10-25: nav entry, panel, routes, and the whole
  // src/testing tree. The NEW Testing program (landing-page
  // tests, owner 2026-11-08) lives in the header bar instead —
  // see the testingMenu node below. Its variant routes retired
  // with the winner's promotion the same day; the /testing
  // paths now redirect to the landing page.)
  // In tree mode the ONE left column shows the settings tree
  // instead of the main nav (signed-in only — signed out there is
  // no sidebar at all). Tree mode is the Settings switch's
  // override (side-panel arrangement); /settings/* routes keep
  // the main menu since 2026-11-03 — the page's tabs navigate
  // the sections there.
  const sidebarContent =
    hasSession && user && menuMode === "settings" ? (
      <SettingsSidebarTree
        userTypes={userTypes}
        moduleIds={
          new Set((myModules.modules ?? []).map((m) => m.id))
        }
        bareRung={groupLayerWaived(user)}
        onBackToMenu={() => setMenuOverride("main")}
      />
    ) : undefined;
  // The route's panel (Rail Steel conversion): the registry
  // resolves by route prefix; settings mode overrides it via
  // sidebarContent (AppShell gives that slot precedence — the
  // old takeover).
  const resolvedPanel = hasSession ? panelForRoute(location.pathname) : null;
  // A module that isn't effective for this user leaves no sign:
  // its section panel hides too (hidden-modules directive,
  // 2026-10-31) — the page area shows the gate's panel instead.
  // A module the user merely turned off keeps today's behavior
  // (its gate panel explains that state itself).
  const routePanel =
    resolvedPanel?.module &&
    !myModules.has(resolvedPanel.module) &&
    !myModules.isUserOff(resolvedPanel.module)
      ? null
      : resolvedPanel;
  const panelContent = routePanel?.content;
  const panelLabel = routePanel?.label;
  /* Rail pin (widget options Wave 1, owner design 2026-11-02):
   * the choice lives with the ACCOUNT (/me rail_pinned), like
   * the appearance triple — set once, pinned on every device.
   * The toggle applies locally at once (the rail must answer
   * the tap), then saves through PATCH /me and resyncs from
   * the account; a failed save falls back to the account's
   * value. The local override clears whenever the account's
   * value moves, so the account stays the source of truth. */
  const [railPinLocal, setRailPinLocal] = useState<boolean | null>(null);
  useEffect(() => {
    setRailPinLocal(null);
  }, [user?.rail_pinned]);
  const railPinned = railPinLocal ?? (user?.rail_pinned ?? false);
  const toggleRailPin = () => {
    const next = !railPinned;
    setRailPinLocal(next);
    void api("/core/me", {
      method: "PATCH",
      body: JSON.stringify({ rail_pinned: next }),
    })
      .then(() => refreshUser())
      .catch(() => {
        setRailPinLocal(null);
        void refreshUser();
      });
  };
  /* The header gear's Site settings tree (owner, 2026-11-01):
   * the settings dropdown hangs off the header gear — its popup
   * carries one "Site settings" disclosure row whose leaves are
   * these links. Built from the SAME registry read the sidebar
   * settings tree used (settingsSectionsFor over settingsMeta),
   * so the leaves, their order, and their group gating are the
   * registry's own and can never drift from the settings pages.
   * Signed out there are no leaves and the row never renders. */
  const gearSiteSettingsLinks = user
    ? settingsSectionsFor(
        "site",
        userTypes,
        new Set((myModules.modules ?? []).map((m) => m.id)),
        groupLayerWaived(user),
      ).map((s) => ({
        label: t(`settings.section.${s.id}` as never),
        path: `/settings/${s.id}`,
      }))
    : [];
  /* TESTING (owner, 2026-11-08; staff-only 2026-11-09): the
   * header Testing link renders ONLY for staff accounts —
   * god, moderator_admin, moderator (accountTypes.staffTier).
   * Everyone else (normal, the downloads level, beta-flagged
   * accounts) and signed-out visitors never see it: the node
   * never exists for them and the lazy chunk is never
   * requested. The Suspense fallback is null (the cluster
   * simply gains the item when its small chunk lands). */
  const testingMenu = user && staffTier(user) ? (
    <Suspense fallback={null}>
      <TestingMenu />
    </Suspense>
  ) : null;
  /* DOWNLOADS (owner order, 2026-11-09): Downloads is a main
   * nav item — signed in, the RAIL carries it straight from
   * the registry (core-downloads). Signed out there is no
   * rail: the shell's slim strip is the only primary
   * navigation that renders, so the app hands the shell this
   * plain header link built from the SAME registry entry
   * (its path, its dictionary label) and the shell seats it
   * in the strip's right cluster, in the Testing family's
   * seat. The NEW-badge registry is session-scoped (GET
   * /core/nav-badges requires a session), so the badge rides
   * the rail item only; the strip link is plain. */
  const downloadsEntry = MODULES.find((m) => m.name === "core-downloads");
  const downloadsLink = downloadsEntry ? (
    <Link className="tv-hlink" to={downloadsEntry.path}>
      {navLabel(downloadsEntry.name, downloadsEntry.label)}
    </Link>
  ) : null;
  // The operator's door (module doctrine): visible ONLY to operator
  // accounts. Not a registry nav item — it follows the account flag,
  // not a group — and the admin API enforces the same flag.
  if (hasSession && user?.is_operator) {
    nav.push({ name: "core-admin", label: t("shell.admin"), path: "/admin", icon: undefined });
  }
  // No headerRight prop: the always-visible accent gear row is
  // retired (owner, 2026-10-19 20:45 — the hidden chooser). The
  // accent picker now lives behind the gear next to the user's
  // name, inside HeaderUserMenu.
  //
  /* Teaser front door (2026-10-26): bare chrome only while the
   * teaser is the signed-out "/" — see teaser.tsx. Every other
   * state passes false and the shell renders untouched. */
  const teaserBare = useTeaserBareChrome();
  /* Downloads (owner 2026-11-10 11:40) is a normal page of the
   * main site: it renders in the full shell like every other
   * route — rail and header signed in, the signed-out strip for
   * visitors. The 2026-10-30 bare-chrome exemption that stood
   * the page on its own branding is retired; the page keeps its
   * teaser-wall exemption (teaser.tsx), which is about who may
   * VIEW it, not about chrome. */
  return (
    <AppShell
      navItems={nav}
      sidebarContent={sidebarContent}
      layout={layout}
      headerVariant={headerVariant}

      panelContent={panelContent}
      panelLabel={panelLabel}
      userMenu={<HeaderUserMenu />}
      testingMenu={testingMenu}
      downloadsLink={downloadsLink}
      siteSettingsLinks={gearSiteSettingsLinks}
      railPinned={railPinned}
      onToggleRailPin={user ? toggleRailPin : undefined}
      preSetup={preSetup}
      bare={teaserBare}
    >
      <AccountTypeGate />
      <ReleaseWizardGate />
      <TeaserWall />
      <ScrollManager />
      {/* Page navigation bar (owner directive 2026-11-02): the
       * ‹ › arrows + link tree in the header zone of every
       * signed-in page. The provider mounts unconditionally (the
       * trail is just state); the BAR renders only for a real
       * session on a real app page — the one bare front door
       * (the signed-out teaser) stands on its own branding and
       * shows no bar. /downloads is a normal app page since
       * 2026-11-10 and carries the bar like any other. */}
      <NavTrailProvider>
        {hasSession && !teaserBare && <PageNavBar />}
      {/* Route content entrance (motion pass 2026-10-22): the
       * keyed wrapper sits INSIDE the stable Suspense boundary,
       * so a navigation keeps showing the current page while a
       * lazy chunk loads (the boundary never remounts, no spinner
       * flash), and the new page — wrapper and all — mounts with
       * the .tv-page-enter fade once it is ready. Query / hash
       * changes on the same page do not re-run it. */}
      <Suspense
        fallback={
          /* Deep audit F1-01: the fallback is a page-shaped
           * skeleton (title + panels at real geometry), not a
           * spinner on an empty page — a navigation paints the
           * shell and this frame immediately, and the real page
           * swaps in when its chunk lands. */
          <PageSkeleton />
        }
      >
        <div key={location.pathname} className="tv-page-enter">
        <Routes>
          {/* TESTING (owner, 2026-11-08): the landing-variant
              routes retired with the test pages' promotion —
              the winning page is the official landing now ("/"
              behind the teaser, and "/landing"). Stale test
              URLs land on the landing page itself, never a 404.
              Concrete paths outrank the registry's "*" catch-all. */}
          <Route
            path="/testing"
            element={<Navigate to="/landing" replace />}
          />
          <Route path="/testing/*" element={<Navigate to="/landing" replace />} />
          {/* 3D PRINT FILES (owner, 2026-11-08 21:03): the
              canonical seat moved from /downloads/prints to the
              clean top-level /3dprints. The original paths are
              doors only — they redirect to the canonical routes
              (the static upload segment outranks the :fileId
              parameter, as everywhere in the router). */}
          <Route
            path="/downloads/prints"
            element={<Navigate to="/3dprints" replace />}
          />
          <Route
            path="/downloads/prints/upload"
            element={<Navigate to="/3dprints/upload" replace />}
          />
          <Route
            path="/downloads/prints/:fileId"
            element={<PrintsLegacyDetailRedirect />}
          />
          <Route
            path="/downloads/prints/:fileId/edit"
            element={<PrintsLegacyEditRedirect />}
          />
          {MODULES.map((m) => {
            const El = m.element;
            const page = <El />;
            return (
              <Route
                key={m.name}
                path={m.path}
                element={
                  m.featureModule || m.featureModuleAnyOf ? (
                    <ModuleGate
                      module={m.featureModule ?? m.featureModuleAnyOf![0]!}
                      modules={m.featureModuleAnyOf}
                      moduleLabel={m.label}
                    >
                      {page}
                    </ModuleGate>
                  ) : PUBLIC_FAMILY[m.name] ? (
                    <UserOffGate
                      module={PUBLIC_FAMILY[m.name]!}
                      moduleLabel={m.label}
                    >
                      {page}
                    </UserOffGate>
                  ) : (
                    page
                  )
                }
              />
            );
          })}
        </Routes>
        </div>
      </Suspense>
      </NavTrailProvider>
    </AppShell>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <LayoutProvider>
        <HeaderVariantProvider>
        <ErrorBoundary>
          <AuthProvider>
            <TeaserProvider>
            <LocaleProvider>
            <OnboardingProvider>
            <MyModulesProvider>
              <ToastProvider>
                <BrowserRouter>
                  <Shell />
                </BrowserRouter>
                {/* The truncated-pill tooltip host (owner rule,
                    2026-11-05): one delegated listener set for
                    every pill on the site. */}
                <PillTipHost />
              </ToastProvider>
            </MyModulesProvider>
            </OnboardingProvider>
            </LocaleProvider>
            </TeaserProvider>
          </AuthProvider>
        </ErrorBoundary>
        </HeaderVariantProvider>
      </LayoutProvider>
    </ThemeProvider>
  );
}
