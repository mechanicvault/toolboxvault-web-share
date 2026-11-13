import { Navigate } from "react-router-dom";

/**
 * The retired standalone routes (Repairs & Maintenance merge,
 * 2026-11-05): /claims and /maintenance no longer render pages
 * of their own — they land on the merged page at the tab that
 * carries their content, so every old bookmark, emailed link
 * and in-app deep link keeps working. Claim DETAIL routes
 * (/claims/:id) are untouched and keep rendering as today.
 *
 * These redirects carry no module gate of their own: the
 * merged page's own gate decides who gets in (either module),
 * and its tabs gate individually from there.
 */

export function ClaimsRedirect() {
  // The old page's History view lived at /claims#history.
  const target =
    window.location.hash === "#history"
      ? "/repairs#repair-history"
      : "/repairs#repair-claims";
  return <Navigate to={target} replace />;
}

export function MaintenanceRedirect() {
  return <Navigate to="/repairs#tool-maintenance" replace />;
}
