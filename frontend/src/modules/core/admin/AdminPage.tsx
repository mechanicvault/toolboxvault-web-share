import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { EmptyState, Panel, Tabs } from "../../../components";
import type { TabItem } from "../../../components/Tabs";
import { ArtIcon } from "../../../components/ArtIcon";
import { useT } from "../../../i18n/LocaleContext";
import { usePageCrumbs } from "../../../lib/navTrail";
import { useAuth } from "../AuthContext";
import { RequireAuth } from "../auth/RequireAuth";
import { ADMIN_SECTIONS, AdminTabbedContext } from "./AdminShell";
import AdminAnnouncementsPage from "./AdminAnnouncementsPage";
import AdminAuditPage from "./AdminAuditPage";
import AdminBansPage from "./AdminBansPage";
import AdminConversionRequestsPage from "./AdminConversionRequestsPage";
import AdminDealerDirectoryPage from "./AdminDealerDirectoryPage";
import AdminInsurerDirectoryPage from "./AdminInsurerDirectoryPage";
import AdminModulesPage from "./AdminModulesPage";
import AdminPromosPage from "./AdminPromosPage";
import AdminRoadmapPage from "./AdminRoadmapPage";
import AdminSettingsPage from "./AdminSettingsPage";
import AdminSitePulsePage from "./AdminSitePulsePage";
import AdminSupportPage from "./AdminSupportPage";
import AdminUsersPage from "./AdminUsersPage";
import "./admin.css";

/**
 * Admin — ONE page in the MAIN TAB LAYOUT (owner order,
 * 2026-11-07: the "Admin" button under Settings' Actions loads
 * "the admin settings in a main tab layout format"). The
 * /settings conversion (2026-11-03) is the precedent, followed
 * the same way: a header zone (art tile top-left, the title and
 * the signed-in admin's identifying facts beside it), then real
 * tabs — ONE per admin section — rendered by the shared Tabs
 * component, whose strip scrolls sideways only (owner's choice,
 * 2026-11-07: scrollable over a second row). Each tab mounts
 * that section's EXISTING page under AdminTabbedContext: the
 * section's own AdminShell keeps its guard and drops its header
 * chrome. This page is a re-homing, not a rebuild — and hiding
 * is presentation only: a section a seat cannot use never
 * renders as a tab for that seat, and the API still refuses
 * that seat independently (the modules matrix is operator-only
 * server-side, tab or no tab).
 *
 * Seats: operators (the god seat) see every section. Moderator
 * admins hold USER MANAGEMENT only — the one tab their tier may
 * use, exactly as the shell and the API have always split it.
 * Everyone else gets the operators-only refusal panel, the same
 * one the old shell rendered; signed-out visitors go through
 * RequireAuth to sign-in first, as before.
 *
 * Routes (unchanged): /admin/<section> renders this page with
 * that section's tab raised — the user menu's Admin door, the
 * rail item, and every in-app /admin/* link keep landing on the
 * right tab. Bare /admin lands on the seat's first section
 * (Modules for operators, Users for moderator admins); a plain
 * #<section-id> hash on bare /admin names its tab the same way
 * (the /settings hash discipline). Tab clicks switch IN PLACE
 * (URL unchanged), per the shared Tabs behavior. The one
 * exception is the Moderation queue entry: its surface lives
 * outside /admin (the community role ladder's page), so its
 * "tab" is a door — clicking it navigates there and it never
 * becomes the active tab (the Help page's videos-door pattern).
 * There is no Actions dropdown: on a page whose only actions
 * would be jumps to the tabs below, the dropdown is the clutter
 * the owner removed from Help — the tabs are the navigation.
 */

const SECTION_CONTENT: Record<string, ReactNode> = {
  modules: <AdminModulesPage />,
  "site-pulse": <AdminSitePulsePage />,
  users: <AdminUsersPage />,
  "conversion-requests": <AdminConversionRequestsPage />,
  promos: <AdminPromosPage />,
  bans: <AdminBansPage />,
  settings: <AdminSettingsPage />,
  audit: <AdminAuditPage />,
  support: <AdminSupportPage />,
  roadmap: <AdminRoadmapPage />,
  announcements: <AdminAnnouncementsPage />,
  "dealer-directory": <AdminDealerDirectoryPage />,
  "insurer-directory": <AdminInsurerDirectoryPage />,
};

function AdminTabbedPage() {
  const { user } = useAuth();
  const t = useT();
  const location = useLocation();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("");

  const isOperator = Boolean(user?.is_operator);
  const isModAdmin = !isOperator && user?.tier === "moderator_admin";
  const isAdminSeat = isOperator || isModAdmin;

  // The sections THIS seat may use: operators get the whole
  // list; a moderator admin gets the Users entry plus
  // Announcements (release machinery, 2026-11-08 — its API gate
  // is the user-manager rung, god + moderator admin; the
  // AdminPanel's split, matched). The Moderation cross-link
  // rides the operator list only, as it always has.
  // Conversion requests is the one GOD-ONLY tab (2026-11-10):
  // even among operators it renders only for the god account —
  // the operator flag derives the god rung in core/tiers, so
  // this is belt-and-braces on the same fact the API enforces.
  const visible = ADMIN_SECTIONS.filter(
    (s) =>
      (isOperator && (s.id !== "conversion-requests" || user?.tier === "god")) ||
      s.id === "users" ||
      s.id === "announcements",
  );
  const contentSections = visible.filter((s) => s.id !== "moderation");
  const first = contentSections[0];

  const segment =
    location.pathname.replace(/^\/admin\/?/, "").split("/")[0] ?? "";
  const routeSection = contentSections.find((s) => s.id === segment);

  // Arriving on a section route raises that section's tab;
  // in-place tab clicks are plain state below.
  useEffect(() => {
    if (segment && contentSections.some((s) => s.id === segment)) {
      setActiveTab(segment);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment]);

  const effectiveTab = contentSections.some((s) => s.id === activeTab)
    ? activeTab
    : (routeSection?.id ?? first?.id ?? "");
  const activeSection = contentSections.find((s) => s.id === effectiveTab);

  usePageCrumbs(
    user && isAdminSeat && activeSection
      ? [
          { label: t("shell.admin"), to: "/admin" },
          { label: activeSection.label },
        ]
      : null,
  );

  if (!user) return null;

  if (!isAdminSeat) {
    // The refusal the old shell rendered, word for word.
    return (
      <Panel>
        <EmptyState
          title="Operators only"
          description="This area is restricted to operator accounts. If you reached this page from a link, the link was wrong — there's nothing here for regular accounts."
        />
      </Panel>
    );
  }

  if (!segment) {
    // Bare /admin: a plain #<section-id> hash names its tab
    // (the /settings discipline); otherwise the seat's front
    // door — its first section.
    const hashId = location.hash ? location.hash.slice(1).split("?", 2)[0] : "";
    if (hashId === "moderation" && visible.some((s) => s.id === "moderation")) {
      return <Navigate to="/moderation" replace />;
    }
    if (hashId && contentSections.some((s) => s.id === hashId)) {
      return <Navigate to={`/admin/${hashId}`} replace />;
    }
    if (first) return <Navigate to={first.path} replace />;
    return null;
  }

  if (!routeSection) {
    // A section this seat cannot use (a moderator admin on
    // /admin/modules): land on the seat's front door instead
    // of a dead page — the arrival the old index gave them.
    if (first) return <Navigate to={first.path} replace />;
    return null;
  }

  const tabs: TabItem[] = visible.map((s) => ({
    id: s.id,
    label: s.label,
    content: s.id === "moderation" ? null : SECTION_CONTENT[s.id],
  }));

  function onTabChange(id: string) {
    if (id === "moderation") {
      // A door, not a tab: the queue lives outside /admin.
      navigate("/moderation");
      return;
    }
    setActiveTab(id);
  }

  return (
    <div className="tv-stack">
      <Panel>
        <div className="tv-admin-head">
          <div className="tv-admin-thumb" aria-hidden="true">
            <ArtIcon name="badge" size={96} />
          </div>
          <div className="tv-admin-head-main">
            <h1 className="tv-admin-title">{t("shell.admin")}</h1>
            <p className="tv-admin-subtitle">{user.name}</p>
            <dl className="tv-admin-facts">
              <div className="tv-admin-fact">
                <dt>{t("settings.accountNumber")}</dt>
                <dd>{user.account_number}</dd>
              </div>
              <div className="tv-admin-fact">
                <dt>Role</dt>
                <dd>{isOperator ? "Operator" : "Moderator admin"}</dd>
              </div>
            </dl>
          </div>
        </div>
      </Panel>

      <AdminTabbedContext.Provider value>
        <Tabs tabs={tabs} activeId={effectiveTab} onChange={onTabChange} />
      </AdminTabbedContext.Provider>
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth>
      <AdminTabbedPage />
    </RequireAuth>
  );
}
