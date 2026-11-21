import { Navigate } from "react-router-dom";

/**
 * The retired standalone route (owner, sheet row 138,
 * 2026-11-18): the whole Borrowing page moved into the
 * Shared Tools page's BORROWING tab (Side List: Lent out /
 * Address book / History). Old bookmarks, emailed links and
 * notification click-throughs land there — the section
 * rides as ?bwsec=, and the ?checkout= / ?borrower=
 * landing params ride along untouched.
 */
export function BorrowingRedirect() {
  const params = new URLSearchParams(window.location.search);
  const hash = window.location.hash;
  if (hash === "#address-book") params.set("bwsec", "address-book");
  else if (hash === "#history") params.set("bwsec", "history");
  const query = params.toString();
  return (
    <Navigate
      to={`/shared-tools${query ? `?${query}` : ""}#borrowing`}
      replace
    />
  );
}
