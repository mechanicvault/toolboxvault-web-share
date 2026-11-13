import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { getPartsStats, listLocations } from "../../modules/parts/api";
import type { PartLocation, PartsStats } from "../../modules/parts/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The My Parts panel (Rail Steel conversion, Phase 2a): shelf
 * links, the location tree's TOP LEVEL from the same
 * /parts/locations call the page's Locations panel uses (each
 * item's chip is the node's own rollup part_count), and the
 * stock stats from /parts/stats — the module's own summary call
 * (parts_count / total_units, the pair Home's "My parts" stat
 * reads).
 *
 * Location items link /parts?location_id=<id>: the parts list
 * filters by subtree through listParts({location_id}) — the
 * page now seeds its location selection from that param (the
 * same URL-seeding pattern ToolListPage uses), so the link
 * lands on the shelf already filtered to the subtree.
 */

const LOCATION_CAP = 10;

export function PartsPanel() {
  const location = useLocation();
  // The location items carry their state in the query string,
  // which NavLink cannot see — compute it from the URL exactly
  // like InventoryPanel does, so a deep-linked shelf highlights
  // the location it is filtered to.
  const activeLocationId =
    location.pathname === "/parts"
      ? new URLSearchParams(location.search).get("location_id")
      : null;
  const [roots, setRoots] = useState<PartLocation[]>([]);
  const [locationTotal, setLocationTotal] = useState(0);
  const [stats, setStats] = useState<PartsStats | null>(null);

  useEffect(() => {
    let live = true;
    listLocations()
      .then((rows) => {
        if (!live) return;
        const tops = rows
          .filter((l) => l.parent_id === null)
          .sort((a, b) => a.name.localeCompare(b.name));
        setRoots(tops.slice(0, LOCATION_CAP));
        setLocationTotal(tops.length);
      })
      .catch(() => undefined);
    getPartsStats()
      .then((s) => {
        if (live) setStats(s);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <p className="tv-sp-kicker">My Parts</p>
      <h2 className="tv-sp-title">My Parts</h2>
      <PanelUtility />
      <p className="tv-sp-group">Shelf</p>
      <div className="tv-sp-list">
        <NavLink
          to="/parts"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive && !activeLocationId ? " is-active" : ""}`
          }
        >
          <span>My Parts</span>
        </NavLink>
        <NavLink
          to="/parts/new"
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Add part</span>
        </NavLink>
        <NavLink
          to="/parts/community"
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Community Parts</span>
        </NavLink>
      </div>
      {roots.length > 0 && (
        <>
          <p className="tv-sp-group">Locations</p>
          <div className="tv-sp-list">
            {roots.map((loc) => (
              <NavLink
                key={loc.id}
                to={`/parts?location_id=${loc.id}`}
                className={`tv-sp-item${activeLocationId === loc.id ? " is-active" : ""}`}
                aria-current={activeLocationId === loc.id ? "page" : undefined}
              >
                <span>{loc.name}</span>
                <span className="tv-sp-count">
                  {loc.part_count.toLocaleString("en-US")}
                </span>
              </NavLink>
            ))}
          </div>
          {locationTotal > roots.length && (
            <p className="tv-sp-hint">
              +{locationTotal - roots.length} more top-level locations —
              the full tree is on the page.
            </p>
          )}
        </>
      )}
      {stats && (
        <ul className="tv-sp-stats">
          <li>
            <span>Parts on shelf</span>
            <strong>{stats.parts_count.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Total units</span>
            <strong>{stats.total_units.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Locations</span>
            <strong>{locationTotal.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {stats && stats.parts_count === 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Empty shelf</p>
          <p>
            No spares filed yet — add the parts you&apos;re keeping for
            later and they&apos;ll count here, never against your plan.
          </p>
        </div>
      )}
    </>
  );
}
