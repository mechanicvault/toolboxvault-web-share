import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { getMaintenanceOverview } from "../../modules/maintenance/api";
import type { MaintenanceOverview } from "../../modules/maintenance/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Repairs & maintenance panel (Rail Steel conversion,
 * Phase 2c).
 *
 * The page's due filter (All / Due soon / Overdue) is local
 * component state — no URL carries it — so the panel links only
 * the page itself and derives its stats from the page's own
 * read, GET /maintenance/overview: schedule counts by computed
 * due_status plus the out-of-service board length. (The lighter
 * /maintenance/stats endpoint carries only due + out-of-service
 * totals; the overview is the one call that also splits overdue
 * from due-soon, and it is the call the page itself makes.)
 */
export function MaintenancePanel() {
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null);

  useEffect(() => {
    let live = true;
    getMaintenanceOverview()
      .then((o) => {
        if (live) setOverview(o);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const overdue = overview
    ? overview.schedules.filter((s) => s.due_status === "overdue").length
    : 0;
  const dueSoon = overview
    ? overview.schedules.filter((s) => s.due_status === "due_soon").length
    : 0;

  return (
    <>
      <p className="tv-sp-kicker">Maintenance</p>
      <h2 className="tv-sp-title">Repairs &amp; maintenance</h2>
      <PanelUtility />
      <p className="tv-sp-group">Boards</p>
      <div className="tv-sp-list">
        <NavLink
          to="/repairs#tool-maintenance"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Due &amp; repairs</span>
          {overview && overdue > 0 && (
            <span className="tv-sp-count">{overdue.toLocaleString("en-US")}</span>
          )}
        </NavLink>
      </div>
      {overview && (
        <ul className="tv-sp-stats">
          <li>
            <span>Overdue</span>
            <strong>{overdue.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Due soon</span>
            <strong>{dueSoon.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Out of service</span>
            <strong>{overview.out_of_service.length.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Schedules</span>
            <strong>{overview.schedules.length.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {overview && overdue > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Overdue work</p>
          <p>
            {overdue} schedule{overdue === 1 ? " is" : "s are"} past due —
            log them done from the board, or open the item to reschedule.
          </p>
        </div>
      )}
    </>
  );
}
