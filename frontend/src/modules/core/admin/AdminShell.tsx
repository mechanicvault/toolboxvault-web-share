import { createContext, useContext, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { EmptyState, Panel, Spinner } from "../../../components";
import { useAuth } from "../AuthContext";

/**
 * The Admin area (owner doctrine, 2026-10-18): ONE shell for every
 * operator surface, grown section by section. Sections register in
 * ADMIN_SECTIONS and add a route; the shell, the guard, and the
 * chrome never change. Sections today: Modules (the module control
 * system), Users, Promos, Bans, Settings, Audit (Phase A2).
 *
 * The guard lives here so no section can forget it: operators only.
 * The API enforces the same flag server-side — this is the visible
 * half. Non-operators never see the nav item that leads here; a
 * direct visit lands on the forbidden panel below.
 *
 * Rail Steel Phase 3 (2026-10-23): admin pages now render through
 * the main AppShell with a dedicated AdminPanel carrying the
 * section list (components/panels/AdminPanel.tsx, registered for
 * the /admin prefix) — there is ONE site chrome, no admin fork.
 * This shell is therefore a PASS-THROUGH: it keeps the guard
 * (loading / operators-only) and the area title, and renders the
 * section page. Its old in-content section nav row is retired —
 * the panel owns section navigation now, URL-driven like every
 * other module panel. Every /admin/* route and deep link is
 * unchanged; each section page still wraps itself in this shell,
 * so no page can lose the guard.
 *
 * Admin door (2026-11-07): the /admin/* routes now render the
 * tabbed AdminPage, which mounts each section as a tab under
 * AdminTabbedContext — inside it, this shell is guard-only (see
 * the context below). The guard itself is unchanged, and the
 * API enforces the same split server-side: hiding a tab is
 * presentation, never the permission.
 */
/**
 * Embedded mode (admin door, 2026-11-07): the Admin page is a
 * main tab layout whose tabs mount the section pages. A section
 * mounted inside that page renders under this context — its
 * AdminShell keeps the GUARD (loading / operators-only /
 * moderator-admin-users-only, exactly as everywhere) but drops
 * its own header chrome, because the tabbed page already
 * carries the area's title. Outside the context nothing
 * changes: the shell renders as it always has.
 */
export const AdminTabbedContext = createContext(false);

export interface AdminSection {
  id: string;
  label: string;
  path: string;
}

export const ADMIN_SECTIONS: AdminSection[] = [
  { id: "modules", label: "Modules", path: "/admin/modules" },
  // Site pulse (sweep D4, owner idea 5): the operator's morning
  // glance. Operator-only like the sections around it — the tab
  // filters in AdminPage/AdminPanel admit it for operators
  // alone, and the API (require_operator) refuses everyone else.
  { id: "site-pulse", label: "Site pulse", path: "/admin/site-pulse" },
  { id: "users", label: "Users", path: "/admin/users" },
  // Conversion requests (tier conversion, 2026-11-10): the god
  // queue for Downloads-level accounts asking for full access.
  // GOD ONLY — narrower than every other section's seat: the
  // tab filters in AdminPage/AdminPanel admit it for the god
  // account alone, and the API refuses everyone else anyway.
  { id: "conversion-requests", label: "Conversion requests", path: "/admin/conversion-requests" },
  { id: "promos", label: "Promos", path: "/admin/promos" },
  { id: "bans", label: "Bans", path: "/admin/bans" },
  { id: "settings", label: "Settings", path: "/admin/settings" },
  { id: "audit", label: "Audit", path: "/admin/audit" },
  { id: "support", label: "Support tickets", path: "/admin/support" },
  { id: "roadmap", label: "Roadmap", path: "/admin/roadmap" },
  // Announcements (release machinery, 2026-11-08): the feature
  // announcement composer + history. Its seat is god + moderator
  // admin (the API's user-manager gate) — wider than the other
  // sections' operator-only seat, so the tab filters in
  // AdminPage/AdminPanel name it explicitly beside Users.
  { id: "announcements", label: "Announcements", path: "/admin/announcements" },
  { id: "dealer-directory", label: "Dealer directory", path: "/admin/dealer-directory" },
  { id: "insurer-directory", label: "Insurer directory", path: "/admin/insurer-directory" },
  // The moderation queue lives OUTSIDE /admin (it's the community
  // role ladder's surface, not an operator-only one) — this entry
  // is a cross-link so operators can find it from here too.
  { id: "moderation", label: "Moderation queue", path: "/moderation" },
];

export function AdminShell({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const { pathname } = useLocation();
  const embedded = useContext(AdminTabbedContext);

  if (loading) {
    return (
      <p
        style={{
          color: "var(--text-muted)",
          display: "flex",
          gap: "var(--space-2)",
          alignItems: "center",
        }}
      >
        <Spinner size="sm" /> Loading…
      </p>
    );
  }

  /* Moderator admins (tier, 2026-10-31) hold USER MANAGEMENT
   * only: the shell admits them on the users section and nowhere
   * else. Every other section stays operators-only, exactly as
   * the API enforces it. Release machinery (2026-11-08) adds ONE
   * more seat: Announcements, whose API gate is the same
   * user-manager rung (god + moderator admin) — the shell admits
   * them there too, and nowhere else new. */
  const isModAdminUsers =
    !user?.is_operator &&
    user?.tier === "moderator_admin" &&
    (pathname.startsWith("/admin/users") ||
      pathname.startsWith("/admin/announcements"));

  if (!user?.is_operator && !isModAdminUsers) {
    return (
      <Panel>
        <EmptyState
          title="Operators only"
          description="This area is restricted to operator accounts. If you reached this page from a link, the link was wrong — there's nothing here for regular accounts."
        />
      </Panel>
    );
  }

  if (embedded) {
    // Inside the tabbed Admin page: the guard above has run;
    // the page's own header carries the area title, so the
    // section renders bare.
    return <>{children}</>;
  }

  return (
    <div className="tv-admin-content" style={{ display: "grid", gap: "var(--spacing)" }}>
      <div>
        <h1 style={{ margin: "0 0 var(--space-1)" }}>Admin</h1>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {isModAdminUsers
            ? "User management. Changes apply immediately."
            : "Operator controls for the whole site. Changes apply immediately."}
        </p>
      </div>
      {children}
    </div>
  );
}
