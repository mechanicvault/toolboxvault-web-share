import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { listParts } from "../../modules/parts/api";
import { PanelUtility } from "./PanelUtility";

/**
 * The Community Parts panel (Rail Steel conversion, Phase 2a)
 * for /parts/community — registered under the longer prefix so
 * the pool page gets its own panel while every other /parts*
 * route keeps the My Parts panel.
 *
 * Links: the pool, the owner's shelf, add-a-part. The publish
 * state note is derived from the owner's own shelf read
 * (listParts — the same payload the My Parts page renders):
 * each part carries its resolved is_public flag, so the count of
 * listed parts is a fact, not a new endpoint.
 */
export function CommunityPanel() {
  const [shelf, setShelf] = useState<{ total: number; listed: number } | null>(
    null,
  );

  useEffect(() => {
    let live = true;
    listParts({})
      .then((parts) => {
        if (!live) return;
        setShelf({
          total: parts.length,
          listed: parts.filter((p) => p.is_public).length,
        });
      })
      .catch(() => {
        if (live) setShelf(null);
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <p className="tv-sp-kicker">Community</p>
      <h2 className="tv-sp-title">Community Parts</h2>
      <PanelUtility />
      <p className="tv-sp-group">Pool</p>
      <div className="tv-sp-list">
        <NavLink
          to="/parts/community"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Community Parts</span>
        </NavLink>
        <NavLink
          to="/parts"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
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
      </div>
      {shelf && (
        <ul className="tv-sp-stats">
          <li>
            <span>Your parts listed</span>
            <strong>{shelf.listed.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Your shelf total</span>
            <strong>{shelf.total.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {shelf && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Your shelf in the pool</p>
          <p>
            {shelf.listed > 0
              ? `${shelf.listed} of your ${shelf.total} part${shelf.total === 1 ? "" : "s"} ${shelf.listed === 1 ? "is" : "are"} listed publicly — manage visibility from My Parts.`
              : "Nothing of yours is listed yet — publish a part from My Parts and it shows up here for every member."}
          </p>
        </div>
      )}
    </>
  );
}
