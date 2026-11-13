import { useEffect, useState } from "react";
import {
  Navigate,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { Button, Modal, Panel, Spinner, Tabs } from "../../components";
import type { TabItem } from "../../components/Tabs";
import { useT } from "../../i18n/LocaleContext";
import { usePageCrumbs } from "../../lib/navTrail";
import { accountTypeSummary, groupLayerWaived } from "./accountTypes";
import { useAuth } from "./AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import {
  LEGACY_SECTION_ANCHORS,
  SETTINGS_SECTIONS,
  settingsSectionsFor,
} from "./settingsMeta";
import { useMyModules } from "./MyModules";
import {
  settingsSectionById,
  type SettingsSection,
} from "./settingsRegistry";
import {
  SettingsActionsMenu,
  type SettingsActionEntry,
} from "./SettingsActionsMenu";
import "./settings.css";

/**
 * Settings — ONE page in the MAIN TAB LAYOUT (owner order,
 * 2026-11-03: "the setting menu on the left should open a page
 * with the main tab layout design with each tab for the
 * different settings"). The header zone carries the settings
 * thumbnail top-left (click for the larger view), the title and
 * the account's identifying facts beside it (name, account
 * number, group — the facts the user menu's account plate
 * shows), and ONE Actions dropdown at the top-right whose
 * entries jump to each tab in place. Below, real tabs: EVERY
 * section from the one registry (settingsMeta/settingsRegistry)
 * is a tab — SITE sections first in registry order, then
 * ACCOUNT sections — gated exactly as the registry gates them
 * (dealer/shop/insurer sections exist only for the groups that
 * hold them). Each tab renders that section's EXISTING component
 * inside the same .tv-settings-content wrapper the old shell
 * used, so per-section styling and behavior carry over
 * untouched. There is no status strip: Settings has no live
 * state to show, and none is fabricated.
 *
 * Routes (unchanged): /settings/:section renders this page with
 * that section's tab raised — bookmarks, the gear-menu Site
 * settings tree, and the user menu's account links all keep
 * landing on the right tab. Bare /settings keeps the arrival
 * default (the first SITE section). An unknown segment, or a
 * section this account doesn't hold, lands on Profile — the
 * account's front door — exactly as the old shell did. Legacy
 * hash anchors (#billing / #custom-fields, incl. Stripe's old
 * #billing?checkout=… return) redirect to the section route
 * with any query outcome preserved; a plain #<section-id> hash
 * on bare /settings names its tab the same way. Tab clicks
 * switch in place (URL unchanged), per the shared Tabs
 * behavior; the link tree follows the active tab.
 *
 * The rail's settings tree no longer raises on these routes
 * (App.tsx): the tabs replaced it on this page. The gear tree
 * is unchanged.
 */

function SettingsShell() {
  const { user } = useAuth();
  const t = useT();
  const { section } = useParams<{ section?: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [thumbOpen, setThumbOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<string>(section ?? "");
  // Settings follow reach (2026-11-09): module-owned sections
  // exist only while their module is effective for this
  // account — the same my-modules set the nav reads. While that
  // read is in flight the set is empty, so a reach-gated tab
  // never flashes for an account that can't use it (the nav's
  // own loading posture). The bounce guards below also read
  // `modulesLoading`: whether a module-owned section is held
  // cannot be decided until this read lands.
  const { modules: effectiveModules, loading: modulesLoading } =
    useMyModules();
  const moduleIds: ReadonlySet<string> = new Set(
    (effectiveModules ?? []).map((m) => m.id),
  );
  // A group-waived (bare-minimum) account's Settings carry the
  // bare sections only — the same gate the header user menu
  // reads (chrome reach audit, 2026-11-09), so a deep link to
  // a non-bare section bounces to Profile below like any other
  // unheld section.
  const bareRung = user ? groupLayerWaived(user) : false;

  // The tab set: SITE sections in registry order, then ACCOUNT
  // sections — the registry's own gating decides which exist
  // for this account (multi-group accounts get the union).
  const ordered: SettingsSection[] = user
    ? (["site", "account"] as const)
        .flatMap((g) =>
          settingsSectionsFor(g, user.account_types, moduleIds, bareRung),
        )
        .map((m) => settingsSectionById(user, m.id, moduleIds, bareRung))
        .filter((s): s is SettingsSection => !!s)
    : [];

  // Arriving on a section route (a gear-tree leaf, the user
  // menu's account links, browser back/forward) raises that
  // section's tab. In-place tab clicks are plain state below.
  useEffect(() => {
    if (section && ordered.some((s) => s.id === section)) {
      setActiveTab(section);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  const effectiveTab = ordered.some((s) => s.id === activeTab)
    ? activeTab
    : (section ?? ordered[0]?.id ?? "");
  const activeSection = ordered.find((s) => s.id === effectiveTab);

  // The link tree follows the active tab — the same shape the
  // route-derived trail used (Settings › section), kept truthful
  // across in-place tab switches.
  usePageCrumbs(
    user && activeSection
      ? [
          { label: t("shell.settings"), to: "/settings" },
          {
            label: t(`settings.section.${activeSection.id}` as never),
          },
        ]
      : null,
  );

  if (!user) return null;

  // Legacy hash anchors → section routes (render-level, so the
  // outcome is deterministic): the hash form rides in on old
  // bookmarks, in-app links that predate the routes, and
  // Stripe's former return URL; the ?outcome inside it
  // (checkout result) is preserved as the target's query string.
  if (location.hash) {
    const raw = location.hash.slice(1);
    const [anchor, query] = raw.split("?", 2);
    const target = anchor ? LEGACY_SECTION_ANCHORS[anchor] : undefined;
    if (target && (target !== section || query)) {
      return (
        <Navigate
          to={`/settings/${target}${query ? `?${query}` : ""}`}
          replace
        />
      );
    }
  }

  // The hold rendered while the read that DECIDES a bounce is
  // still in flight (cold-load race, found by Lane 1 and fixed
  // here, 2026-11-10): on a cold direct load of a module-owned
  // section (e.g. /settings/sharing from Inventory's Actions
  // menu), the my-modules read has not landed on first render,
  // so the section is absent from `ordered` even for an account
  // that holds it — bouncing then strands a valid deep link on
  // Profile. While the read is in flight, a module-owned target
  // waits here; the moment it resolves, the section renders (or
  // the bounce below fires, unchanged). Sections whose absence
  // is decidable synchronously (unknown ids, group/bare gates)
  // never wait.
  const sectionHold = (
    <div className="tv-stack">
      <Panel>
        <p className="tv-settings-loading">
          <Spinner size="sm" /> Loading…
        </p>
      </Panel>
    </div>
  );
  const awaitingModules = (id: string) =>
    modulesLoading &&
    SETTINGS_SECTIONS.find((s) => s.id === id)?.module !== undefined;

  const routeSection = section
    ? ordered.find((s) => s.id === section)
    : undefined;
  if (section && !routeSection) {
    if (awaitingModules(section)) return sectionHold;
    // An unknown segment, or a section this account doesn't
    // hold (dealer profile without the group): land on the
    // account's front door instead of a dead page.
    return <Navigate to="/settings/profile" replace />;
  }
  if (!section) {
    // A plain #<section-id> hash on bare /settings names its
    // tab (the legacy anchors were handled above).
    const hashId = location.hash ? location.hash.slice(1).split("?", 2)[0] : "";
    if (hashId && ordered.some((s) => s.id === hashId)) {
      return <Navigate to={`/settings/${hashId}`} replace />;
    }
    if (hashId && awaitingModules(hashId)) return sectionHold;
    // Bare /settings — the ARRIVAL default (owner spec, Deep
    // Audit Round 2 A-14): fresh arrival lands on the first
    // SITE section (Modules), as it did under the old shell.
    const firstSite = settingsSectionsFor(
      "site",
      user.account_types,
      moduleIds,
      bareRung,
    )[0];
    return (
      <Navigate
        to={`/settings/${firstSite ? firstSite.id : "profile"}`}
        replace
      />
    );
  }

  const sectionLabel = (s: SettingsSection) =>
    t(`settings.section.${s.id}` as never);

  const tabs: TabItem[] = ordered.map((s) => ({
    id: s.id,
    label: sectionLabel(s),
    content: (
      <div className="tv-settings-content" data-settings-section={s.id}>
        {s.render(user)}
      </div>
    ),
  }));

  const actionEntries: SettingsActionEntry[] = ordered.map((s) => ({
    key: s.id,
    label: sectionLabel(s),
    run: () => setActiveTab(s.id),
  }));

  return (
    <div className="tv-stack">
      <Panel>
        <div className="tv-settings-head">
          <div className="tv-settings-thumb">
            <button
              type="button"
              className="tv-settings-thumb-btn"
              onClick={() => setThumbOpen(true)}
              aria-label={t("settings.viewLarger")}
            >
              <img src="/brand/settings.webp" alt={t("settings.thumbAlt")} />
            </button>
          </div>
          <div className="tv-settings-head-main">
            <h1 className="tv-settings-title">{t("shell.settings")}</h1>
            <p className="tv-settings-subtitle">{user.name}</p>
            <dl className="tv-settings-facts">
              <div className="tv-settings-fact">
                <dt>{t("settings.accountNumber")}</dt>
                <dd>{user.account_number}</dd>
              </div>
              <div className="tv-settings-fact">
                <dt>{t("home.panel.group")}</dt>
                <dd>{accountTypeSummary(user.account_types)}</dd>
              </div>
            </dl>
          </div>
          <div className="tv-settings-head-actions">
            <SettingsActionsMenu
              ariaLabel={t("shell.settings")}
              buttonLabel={t("settings.actions")}
              entries={actionEntries}
              currentKey={effectiveTab}
            />
            {/* The Admin door (owner order, 2026-11-07): a
                second button directly UNDER Actions, admin
                seats only — operators land on the Admin page's
                first tab, moderator admins on Users, the one
                section their tier holds (the user menu's door
                splits the same way). Other seats never see it. */}
            {(user.is_operator || user.tier === "moderator_admin") && (
              <Button
                onClick={() =>
                  navigate(user.is_operator ? "/admin" : "/admin/users")
                }
              >
                {t("shell.admin")}
              </Button>
            )}
          </div>
        </div>
      </Panel>

      <Tabs tabs={tabs} activeId={effectiveTab} onChange={setActiveTab} />

      <Modal
        open={thumbOpen}
        onClose={() => setThumbOpen(false)}
        title={t("shell.settings")}
        size="lg"
      >
        <div className="tv-settings-thumb-large">
          <img src="/brand/settings.webp" alt={t("settings.thumbAlt")} />
        </div>
      </Modal>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <RequireAuth>
      <SettingsShell />
    </RequireAuth>
  );
}
