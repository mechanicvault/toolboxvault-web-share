import { Navigate } from "react-router-dom";

/**
 * The retired standalone route (owner, sheet row 137,
 * 2026-11-18): the whole Disaster Claims section moved into
 * the Inventory page's DISASTER CLAIM tab. Old bookmarks,
 * emailed links and in-app deep links land there; the
 * section's own tab rides along as ?dcsec= (#open / #closed
 * / #history). Claim DETAIL routes (/disaster-claims/:id)
 * are untouched and keep rendering as today.
 */
export function DisasterClaimsRedirect() {
  const hash = window.location.hash;
  const target =
    hash === "#open"
      ? "/inventory?dcsec=open#disaster-claim"
      : hash === "#closed" || hash === "#history"
        ? "/inventory?dcsec=closed#disaster-claim"
        : "/inventory#disaster-claim";
  return <Navigate to={target} replace />;
}
