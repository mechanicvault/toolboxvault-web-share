import { Navigate } from "react-router-dom";

/**
 * The retired standalone routes. Repairs & Maintenance
 * merge (2026-11-05) first folded /claims and /maintenance
 * into the merged /repairs page; the Inventory consolidation
 * (owner, sheet row 136, 2026-11-18) retired that page too:
 * its claims half lives in the Inventory REPAIR CLAIMS tab
 * (Side List: New Repair / Open Repairs / History Repairs),
 * its maintenance half in the Inventory MAINTENANCE tab, and
 * its out-of-service board behind the Inventory list's Out
 * of Service link. Every old bookmark, emailed link and
 * in-app deep link lands on the tab that carries its
 * content. Claim DETAIL routes (/claims/:id) are untouched
 * and keep rendering as today.
 *
 * These redirects carry no module gate of their own: the
 * Inventory page's tabs gate individually from there.
 */

export function RepairsRedirect() {
  const hash = window.location.hash;
  const target =
    hash === "#repair-history"
      ? "/inventory?rcsec=history#repair-claims"
      : hash === "#tool-maintenance"
        ? "/inventory#maintenance"
        : hash === "#out-of-service"
          ? "/inventory"
          : "/inventory#repair-claims";
  return <Navigate to={target} replace />;
}

export function ClaimsRedirect() {
  // The old page's History view lived at /claims#history.
  const target =
    window.location.hash === "#history"
      ? "/inventory?rcsec=history#repair-claims"
      : "/inventory#repair-claims";
  return <Navigate to={target} replace />;
}

export function MaintenanceRedirect() {
  return <Navigate to="/inventory#maintenance" replace />;
}
