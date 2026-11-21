import { NavLink } from "react-router-dom";

import { useAuth } from "../../modules/core/AuthContext";
import { ADMIN_SECTIONS } from "../../modules/core/admin/AdminShell";
import { PanelUtility } from "./PanelUtility";

/**
 * The Admin panel (Rail Steel conversion, Phase 3) for /admin*.
 *
 * Admin now renders through the MAIN AppShell like every other
 * module: this panel carries the admin sections (the same
 * ADMIN_SECTIONS list AdminShell used to render as an in-content
 * nav row — Modules, Users, Promos, Bans, Settings, Audit,
 * Roadmap, Dealer directory, Insurer directory, plus the
 * Moderation cross-link, whose surface lives outside /admin).
 * Active state is URL-driven: NavLink marks the current section
 * (aria-current + the accent plate), so deep links into
 * /admin/users and friends light the right item.
 *
 * Gating mirrors the old shell exactly: the section list renders
 * ONLY for operator accounts (the same is_operator flag the rail's
 * Admin item and the admin API enforce). A non-operator who lands
 * on /admin directly gets the operators-only note here, and
 * AdminShell's guard renders the forbidden panel in the content —
 * no section names leak beyond what the guard already said.
 */
export function AdminPanel() {
  const { user } = useAuth();
  const isOperator = Boolean(user?.is_operator);
  /* Moderator admins (tier, 2026-10-31) hold user management
   * only: their section list is the Users entry — plus, since
   * the release machinery (2026-11-08), Announcements, whose API
   * gate is the same user-manager rung. The API enforces the
   * same split server-side. */
  const isModAdmin = !isOperator && user?.tier === "moderator_admin";
  const sections = isModAdmin
    ? ADMIN_SECTIONS.filter(
        (section) => section.id === "users" || section.id === "announcements",
      )
    : ADMIN_SECTIONS;
  return (
    <>
      <p className="tv-sp-kicker">Admin</p>
      <h2 className="tv-sp-title">Admin</h2>
      <PanelUtility />
      {isOperator || isModAdmin ? (
        <>
          <p className="tv-sp-group">Sections</p>
          <div className="tv-sp-list">
            {sections.map((section) => (
              <NavLink
                key={section.id}
                to={section.path}
                className={({ isActive }) =>
                  `tv-sp-item${isActive ? " is-active" : ""}`
                }
              >
                <span>{section.label}</span>
              </NavLink>
            ))}
          </div>
        </>
      ) : (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Operators only</p>
          <p>This area is restricted to operator accounts.</p>
        </div>
      )}
    </>
  );
}
