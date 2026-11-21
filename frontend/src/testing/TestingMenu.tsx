/**
 * The header "Testing" item (owner order, 2026-11-08) — what
 * remains of the landing testing program.
 *
 * While the tests ran, this was a dropdown of landing-page
 * options. The program ended with Option 1's promotion to
 * the official landing page, and the item is now a plain
 * LINK straight to the landing page (owner: "Make the test
 * link go to the landing page for now so i can view it when
 * i want to"). It stays in the header for future test
 * programs. Rendered by App.tsx ONLY for signed-in staff
 * accounts (and lazy-loaded, so a signed-out visitor never downloads
 * this tree).
 *
 * The link points at "/landing" — the landing page's own
 * seat — because at "/" a signed-in user gets their home,
 * not the landing. Signed out, the teaser wall still bounces
 * "/landing" to the teaser while the teaser is on, so the
 * landing stays hidden behind it.
 *
 * VISIBILITY (owner order, 2026-11-09): staff accounts only —
 * god, moderator_admin, moderator. App.tsx builds this node
 * solely when accountTypes.staffTier(user) holds; every other
 * account never sees the item at all (no greyed-out state).
 */

import { NavLink } from "react-router-dom";

import "./testing.css";

export default function TestingMenu() {
  return (
    <div className="lt-menu-wrap">
      <NavLink
        to="/landing"
        className={({ isActive }) =>
          `lt-menu-btn${isActive ? " is-active" : ""}`
        }
      >
        <span>Testing</span>
      </NavLink>
    </div>
  );
}
