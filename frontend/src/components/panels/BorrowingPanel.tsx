import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { getBorrowingOverview } from "../../modules/borrowing/api";
import type { BorrowingCounts } from "../../modules/borrowing/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Borrowing panel (Rail Steel conversion, Phase 2c — the
 * build the task brief calls Phase 2b).
 *
 * Borrowing is ONE page whose sections (Requests for me / My
 * requests / Lent out / Borrowed by me / History / the Borrowers
 * address book) are stacked panels driven by local state — no
 * route or query carries a section, so the panel invents no
 * section deep-links (the Phase 2a honesty standard). What it
 * carries is the page's own summary call, GET /borrowing/overview
 * (the same single read the page renders from): its counts block
 * as the stats list, plus an overdue note when the ledger says
 * something is late.
 */
export function BorrowingPanel() {
  const [counts, setCounts] = useState<BorrowingCounts | null>(null);

  useEffect(() => {
    let live = true;
    getBorrowingOverview()
      .then((o) => {
        if (live) setCounts(o.counts);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <p className="tv-sp-kicker">Borrowing</p>
      <h2 className="tv-sp-title">Borrowing</h2>
      <PanelUtility />
      <p className="tv-sp-group">Ledger</p>
      <div className="tv-sp-list">
        <NavLink
          to="/borrowing"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Checked out &amp; requests</span>
          {counts && counts.pending_requests > 0 && (
            <span className="tv-sp-count">
              {counts.pending_requests.toLocaleString("en-US")}
            </span>
          )}
        </NavLink>
      </div>
      {counts && (
        <ul className="tv-sp-stats">
          <li>
            <span>Requests waiting</span>
            <strong>{counts.pending_requests.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Lent out</span>
            <strong>{counts.checked_out.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Borrowed by me</span>
            <strong>{counts.borrowed.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Overdue</span>
            <strong>{counts.overdue.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {counts && counts.overdue > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Overdue</p>
          <p>
            {counts.overdue} lend{counts.overdue === 1 ? " is" : "s are"}{" "}
            past due — open the ledger to nudge the borrower.
          </p>
        </div>
      )}
    </>
  );
}
