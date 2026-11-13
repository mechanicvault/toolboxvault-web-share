import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import { SIDE_PANEL_ENABLED } from "../lib/shellFlags";
import {
  AccentGearChooser,
  type GearSiteSettingsLink,
} from "../theme/AccentDots";
import type { HeaderVariantName } from "../theme/HeaderVariantContext";
import type { LayoutName } from "../theme/LayoutContext";
import { AppStoreBar } from "./AppStoreBar";
import { ConstructionBanner } from "./ConstructionBanner";
import { HeaderCluster } from "./HeaderCluster";
import { LayersIcon } from "./icons";
import { SocialLinks } from "./SocialLinks";
import { SpinningEmblem } from "./SpinningEmblem";

export interface ShellNavItem {
  name: string;
  label: string;
  path: string;
  /** Optional leading icon (module-supplied). */
  icon?: ReactNode;
  /** Optional trailing badge (counts, status). */
  badge?: ReactNode;
  /**
   * Optional modifier class for the badge seat. The NEW badge
   * (release machinery, 2026-11-08) passes "tv-rail-badge--new":
   * unlike count badges — which rest hidden until the rail is
   * hovered/pinned — a NEW pill must be VISIBLE for its whole
   * first week, so its class keeps it shown (as a compact but
   * legible NEW pill at rail rest and on the phone strip,
   * where badges hide by design — sweep 10-F15).
   */
  badgeClassName?: string;
  /**
   * Optional accordion children: retained for compatibility with
   * earlier grouped items. In the Rail Steel shell a grouped item
   * should prefer `onSelect` (flip the panel in place); children
   * without an onSelect render as a plain link to the first child.
   */
  children?: { name: string; label: string; path: string }[];
  /**
   * Optional in-place ACTIVATE behavior (menu-behavior rule,
   * owner 2026-10-23): when present the item is a DISCLOSURE
   * SWITCH, not a link — clicking it runs this callback and never
   * navigates. A parent that owns a submenu must not teleport the
   * user to another page just to show its children; only real
   * destination items navigate. (Settings flips the panel to the
   * settings tree.)
   */
  onSelect?: () => void;
  /**
   * Whether this disclosure switch's panel is currently showing.
   * The app owns panel state, so it supplies the verdict for
   * aria-expanded; switches leave it undefined only when the
   * sidebarContent slot alone decides (legacy settings switch).
   */
  panelExpanded?: boolean;
  /**
   * Active styling for a switch item, derived by the app: a
   * switch has no route of its own for NavLink to match, so the
   * app supplies the "active" verdict (Settings reads active
   * while the browser is anywhere under /settings).
   */
  forceActive?: boolean;
}

interface AppShellProps {
  /** Config-driven nav (blueprint Law 7): the app passes registry items. */
  navItems: ShellNavItem[];
  /**
   * Sidebar TAKEOVER content (settings mode): when provided, the
   * panel renders this instead of `panelContent`. Semantics are
   * unchanged from the pre-conversion shell — the app raises it
   * from /settings/* routes or IN PLACE via the rail's Settings
   * switch, with no navigation either way.
   */
  sidebarContent?: ReactNode;
  /**
   * The route's panel content (Rail Steel conversion): computed
   * by the app from the panel registry and rendered in the panel
   * beside the rail. Ignored while sidebarContent is present.
   */
  panelContent?: ReactNode;
  /** Aria-label for the panel region; follows its content. */
  panelLabel?: string;
  /**
   * Legacy shell-structure props (owner layouts / header variants,
   * pre-conversion): the Rail Steel shell IGNORES them for
   * signed-in users — one rail + panel frame for everyone — and
   * the signed-out path renders one slim strip regardless. The
   * contexts stay mounted in App.tsx and keep passing them;
   * harmless. (Phone update, A-01: the panel now starts
   * collapsed on phones and opens in place from a toggle in
   * the rail strip — see the phonePanelOpen state below.)
   */
  layout?: LayoutName;
  headerVariant?: HeaderVariantName;
  /** Right side of the signed-out strip: theme controls, etc. */
  headerRight?: ReactNode;
  /** Legacy header-center slot: unused by the Rail Steel shell
   *  (search + notifications live in the panel now). Kept in the
   *  props so existing callers compile; App.tsx no longer passes it. */
  headerCenter?: ReactNode;
  /** User menu element (app constructs it from auth state).
   * Signed in it renders inside the header cluster (its person
   * icon beside the Help ? — owner, 2026-11-03); signed out it
   * renders in the slim strip, where it is the login/signup
   * cluster. */
  userMenu?: ReactNode;
  /**
   * TESTING (owner order, 2026-11-08): the header Testing item.
   * The app builds it (lazy, from src/testing) ONLY for
   * signed-in users and the shell seats it at the left of the
   * header bar's right cluster in both full layouts. The bare
   * front doors render no header bar at all, so it never
   * appears there. It began as the landing-test options
   * dropdown; since the winner's promotion it is a plain link
   * straight to the landing page, kept for future test
   * programs. Delete this prop, the two render sites, and
   * src/testing together if the owner retires the item.
   */
  testingMenu?: ReactNode;
  /**
   * DOWNLOADS (owner order, 2026-11-09): the plain header
   * link form of the registry's Downloads item, built by the
   * app from that entry. Signed in, the rail carries the item
   * itself and this node never renders; signed out there is no
   * rail, so the slim strip seats this link at the left of its
   * right cluster — the Testing family's seat — and Downloads
   * stays in the primary navigation for everyone.
   */
  downloadsLink?: ReactNode;
  /** The header gear popup's Site settings tree leaves (owner,
   * 2026-11-01): the app builds them from the settings registry
   * and the shell only forwards them to the gear chooser, in the
   * topbar cluster and the no-nav strip alike. Empty signed out. */
  siteSettingsLinks?: GearSiteSettingsLink[];
  /**
   * Rail pin (widget options Wave 1, owner design 2026-11-02;
   * MOVED 2026-11-05): whether the account keeps the rail
   * open, and its toggle. The toggle's control no longer sits
   * in the rail — on the owner's word it rests in the header
   * GEAR POPUP, directly above the Site settings row, so the
   * shell forwards both props to the header cluster and the
   * popup row renders only when a toggle is supplied (a
   * signed-in session — signed out there is no rail to pin).
   * The state still rides the nav element as data-pinned,
   * which the theme layer turns into the held-open geometry.
   * On phone widths the popup row hides (the theme's call —
   * the rail is a top strip there and pinning does nothing).
   */
  railPinned?: boolean;
  onToggleRailPin?: () => void;
  /** Pre-setup (sweep 10-F3): forwarded to the header cluster,
   * which holds its inert-until-setup controls (bell, search)
   * from the frame while the account has no type yet. */
  preSetup?: boolean;
  /**
   * Bare front door (teaser mode, 2026-10-26): render the page
   * with no app chrome — no app-store bar, no construction
   * banner, no brand strip, no header or rail. The app passes
   * this for the signed-out teaser at "/" only; /downloads wore
   * it too until 2026-11-10, when the owner made that page a
   * normal part of the main site. Every other route and state
   * leaves it off and renders exactly as before. The one piece
   * of chrome the bare door DOES carry is the shared site
   * footer: the footer-unification order (owner, 2026-11-07)
   * gives the teaser the same footer as the rest of the
   * website, so the bare branch below closes the page with the
   * very same footer element the two full layouts render —
   * one component, every surface.
   */
  bare?: boolean;
  /** Optional extra content under the rail nav. */
  sidebarFooter?: ReactNode;
  brandLabel?: string;
  footerNote?: ReactNode;
  children: ReactNode;
}

/**
 * The app layout shell — Rail Steel conversion (Phase 1).
 *
 * Signed in: ConstructionBanner → the FRAME: a flex row whose
 * first column is the icon RAIL (62px, expanding to 204px on
 * hover/focus-within; a top strip on phones) starting at the
 * very top of the frame and running the full height (owner
 * 2026-10-24 — the header must not shove the menubar down), whose
 * second column is the per-module PANEL (222px, sticky, own
 * scroll) ALSO starting at the very top of the frame and running
 * the full height (owner Phase C, 2026-10-24 — site-wide: the
 * settings takeover aside gets the same geometry), and whose
 * third column stacks the persistent header bar (brand plate at
 * the FAR LEFT of the bar, against the content column's edge —
 * owner Phase E, 2026-10-24, superseding the centered plate;
 * gear · bell · ? · person · Edit view · search at the right)
 * over the content column (main + footer). The rail leads with
 * the nav itself — Home is its first item (owner, 2026-11-03:
 * the user block that Phase E seated at the rail's top is gone;
 * the account menu's door is the person icon in the header
 * cluster now, and the header brand plate is the brand). Pages with no
 * panel render no aside, so no gap is left. The old
 * sidebar/topbar/rail presentations, variant headers, and the
 * mobile drawer retired with the old markup: the panel never
 * becomes an overlay in this design (on phones it collapses
 * behind the rail-strip panel toggle, A-01), so
 * there is no drawer left to make inert and no scrim.
 *
 * Signed out (no nav items): one slim metal strip — brand left,
 * headerRight + userMenu right — on the new tokens. Phase 4
 * polishes the signed-out surfaces; this path just has to work.
 */
export function AppShell({
  navItems,
  sidebarContent,
  panelContent,
  panelLabel,
  headerRight,
  userMenu,
  testingMenu,
  downloadsLink,
  siteSettingsLinks = [],
  railPinned,
  onToggleRailPin,
  preSetup,
  bare,
  sidebarFooter,
  brandLabel = "Toolbox Vault",
  footerNote,
  children,
}: AppShellProps) {
  const t = useT();
  const location = useLocation();
  const hasNav = navItems.length > 0;
  /* Side panel removal (owner, 2026-11-01): while
   * SIDE_PANEL_ENABLED is false (lib/shellFlags — the one
   * switch, with the restore step documented there) the panel
   * column never renders: neither the route's section panel nor
   * the settings-tree takeover, so the phone panel toggle (which
   * keys off effectivePanel below) disappears with it and the
   * content column takes the full width beside the rail. The
   * panel components and every user's saved panel layout stay
   * untouched behind the flag. */
  const effectivePanel = SIDE_PANEL_ENABLED
    ? (sidebarContent ?? panelContent)
    : undefined;
  const effectivePanelLabel = sidebarContent
    ? "Settings"
    : (panelLabel ?? "Main navigation");

  /* Phone panel state (A-01, Deep Audit Round 2): at phone
   * widths the section panel used to stack IN FULL above the
   * content — the first tool tile landed ~1,680px down. Now the
   * panel starts COLLAPSED on phones and opens in place from a
   * toggle in the rail strip (the rail is the phone menubar);
   * opening/closing never navigates and never touches the
   * page's scroll. Desktop ignores the state entirely (the
   * toggle is display:none and the panel always shows). Two
   * arrivals open it without a tap: the settings tree — the
   * rail's Settings switch flips the panel to the tree in place
   * (menu-behavior law), and the user must SEE that flip — and
   * landing on a /settings route itself. Any other navigation
   * re-collapses it, so a module page always leads with its own
   * content. */
  const settingsPanelRaised = !!sidebarContent;
  const [phonePanelOpen, setPhonePanelOpen] = useState(false);
  useEffect(() => {
    setPhonePanelOpen(settingsPanelRaised);
  }, [location.pathname, settingsPanelRaised]);

  const wordmark = (
    <img
      className="tv-wordmark-img"
      src="/brand/wordmark-512.webp"
      alt="Toolbox Vault"
      width={512}
      height={76}
    />
  );

  /* The brand plate (Home + Header program, owner 2026-10-24;
   * Phase E same day): the spinning-logo plate + logo text from
   * the past layout, at the FAR LEFT of the header bar on every
   * page — signed in and signed out alike (Phase E supersedes
   * the centered seat). The rail's own compact brand row is
   * retired, and this plate is the brand. */
  const brandPlate = (
    <Link to="/" className="tv-brandplate" aria-label={`${brandLabel} — home`}>
      <span className="tv-brandplate-mark" aria-hidden="true">
        <SpinningEmblem />
      </span>
      {wordmark}
    </Link>
  );

  /* The footer is ONE component for every surface the shell
   * renders — both full layouts AND the bare front doors — so
   * the social row (owner, 2026-11-07 — components/
   * SocialLinks.tsx) added here stands at the bottom of every
   * page the shell closes, signed in and signed out alike:
   * the teaser door and /downloads included, since the
   * footer-unification order (owner, 2026-11-07) retired the
   * bare door's footer exemption. */
  const footer = (
    <footer className="tv-footer">
      <div className="tv-footer-inner">
        <span>{brandLabel} — designed by a mechanic, for mechanics.</span>
        {footerNote ?? <span>Organize. Protect. Recover.</span>}
      </div>
      <SocialLinks />
    </footer>
  );

  /* Bare front door: the page is the whole surface — its own
   * branding replaces the banner, and the brand strip /
   * app-store bar would only repeat or leak what the page
   * deliberately withholds. The page still closes with the
   * SHARED site footer (footer unification, owner 2026-11-07):
   * the teaser door ends with the identical footer — brand
   * line, slogan, social row — that closes every other page.
   * Used by the teaser front door (signed out, teaser mode);
   * /downloads rendered here too until 2026-11-10, when it
   * became a normal in-shell page on the owner's order. */
  if (bare) {
    return (
      <div className="tv-shell tv-shell--bare">
        <main className="tv-main tv-main--bare">{children}</main>
        {footer}
      </div>
    );
  }

  if (!hasNav) {
    return (
      <div className="tv-shell">
        <AppStoreBar />
        <ConstructionBanner />
        <header className="tv-header tv-header--strip tv-topbar">
          <div className="tv-topbar-inner">
            {brandPlate}
            <div className="tv-topbar-right">
              {downloadsLink}
              {testingMenu}
              <AccentGearChooser siteSettingsLinks={siteSettingsLinks} />
              {headerRight}
              {userMenu}
            </div>
          </div>
        </header>
        <div className="tv-content-col">
          <main className="tv-main">
            <div className="tv-main-inner">{children}</div>
          </main>
          {footer}
        </div>
      </div>
    );
  }

  return (
    <div className="tv-shell">
      <AppStoreBar />
      <ConstructionBanner />
      {/* Shell geometry (owner 2026-10-24; Phase C same day):
       * the RAIL is the frame's first column and the PANEL its
       * second — both start at the very top of the frame and run
       * the full height; the header bar no longer spans the page
       * and shoves everything down. The header keeps its exact
       * height, contents, and order, but lives in the main column
       * to the panel's right; its brand plate sits at the bar's
       * far left, against that column's edge (Phase E). On
       * phones the frame stacks in visual order: menubar strip
       * first, then the header, then panel, then content (the
       * phone media query re-orders the flex children — see
       * railsteel.css). */}
      <div className="tv-frame">
        <nav
          className="tv-rail"
          aria-label="Main navigation"
          data-pinned={railPinned || undefined}
        >
          {/* The nav leads the rail — Home is the first item
           * (owner, 2026-11-03). The user block that Phase E
           * seated here (avatar + identity + the account menu
           * trigger) is removed on the owner's word: the account
           * menu's door is the person icon in the header cluster
           * now, beside the Help ?. Nothing else takes this
           * slot — no gap, no dead zone. */}
          <div className="tv-rail-nav">
            {navItems.map((item) => {
              const icon = (
                <span className="tv-rail-ico" aria-hidden="true">
                  {item.icon ?? item.label.slice(0, 1)}
                </span>
              );
              const label = <span className="tv-rail-label">{item.label}</span>;
              const badge = item.badge ? (
                <span
                  className={`tv-rail-badge${item.badgeClassName ? ` ${item.badgeClassName}` : ""}`}
                >
                  {item.badge}
                </span>
              ) : null;
              if (item.onSelect) {
                /* Disclosure switch (menu-behavior rule): a button
                 * that flips the PANEL in place — never a link,
                 * never a navigation, no scroll jump. */
                return (
                  <button
                    key={item.name}
                    type="button"
                    className={`tv-rail-btn${item.forceActive ? " is-active" : ""}`}
                    aria-expanded={item.panelExpanded ?? !!sidebarContent}
                    aria-controls="tv-panel"
                    onClick={item.onSelect}
                  >
                    {icon}
                    {label}
                    {badge}
                  </button>
                );
              }
              const to = item.children?.[0]?.path ?? item.path;
              return (
                <NavLink
                  key={item.name}
                  to={to}
                  end={item.path === "/"}
                  className={({ isActive }) =>
                    `tv-rail-btn${isActive ? " is-active" : ""}`
                  }
                >
                  {icon}
                  {label}
                  {badge}
                </NavLink>
              );
            })}
            {sidebarFooter}
          </div>
          {/* Phone panel toggle (A-01): lives at the rail nav's
           * end — on phones the rail is the top strip, so the
           * toggle rides the strip with the other rail controls;
           * on desktop it is display:none and the panel is always
           * open. A disclosure control: it flips the panel in
           * place, never navigates (menu-behavior law). */}
          {effectivePanel && (
            <button
              type="button"
              className="tv-rail-btn tv-panel-toggle"
              aria-expanded={phonePanelOpen}
              aria-controls="tv-panel"
              aria-label={`${t("shell.sectionPanel")} — ${effectivePanelLabel}`}
              title={t("shell.sectionPanel")}
              onClick={() => setPhonePanelOpen((v) => !v)}
            >
              <span className="tv-rail-ico" aria-hidden="true">
                <LayersIcon />
              </span>
              <span className="tv-rail-label">{t("shell.sectionPanel")}</span>
            </button>
          )}
          {/* The rail's bottom stays empty (Phase E): the nav
           * column flexes (flex: 1 1 auto) to fill the rail.
           * The push-pin toggle that sat here (widget options
           * Wave 1) moved into the header gear popup on the
           * owner's word (2026-11-05) — it rests there directly
           * above the Site settings line, writing the same
           * account rail_pinned through the same toggle the app
           * passes down; only the state attribute above still
           * rides this element. */}
        </nav>
        {effectivePanel && (
          <aside
            id="tv-panel"
            className="tv-panel tv-shell-panel"
            data-phone-open={phonePanelOpen || undefined}
            aria-label={effectivePanelLabel}
          >
            {effectivePanel}
          </aside>
        )}
        <div className="tv-main-col">
          <header className="tv-topbar">
            <div className="tv-topbar-inner">
              {brandPlate}
              <div className="tv-topbar-right">
                {testingMenu}
                <HeaderCluster
                  siteSettingsLinks={siteSettingsLinks}
                  railPinned={railPinned}
                  preSetup={preSetup}
                  onToggleRailPin={onToggleRailPin}
                  userMenu={userMenu}
                />
              </div>
            </div>
          </header>
          <div className="tv-body tv-body--rail">
            <div className="tv-content-col">
              <main className="tv-main">
                <div className="tv-main-inner">{children}</div>
              </main>
              {footer}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
