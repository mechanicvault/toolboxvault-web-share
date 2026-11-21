import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { api } from "../../lib/api";
import type { PeerOverview } from "../../modules/peer/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Shared Tools panel (Rail Steel conversion, Phase 2c).
 *
 * Peer sharing is one page whose sections (search / invites /
 * sharing with me / your sharing) are local state over a single
 * read — GET /core/sharing/peer, the exact call SharedToolsPage
 * makes. The panel summarizes that payload: accepted grants in
 * each direction and the pending-invite count (MAPPING §3's
 * "pending-invite count if cheap" — it rides the same read, so
 * it is). A pending invite raises the note; accepting happens on
 * the page.
 */
export function SharedToolsPanel() {
  const [overview, setOverview] = useState<PeerOverview | null>(null);

  useEffect(() => {
    let live = true;
    api<PeerOverview>("/core/sharing/peer")
      .then((o) => {
        if (live) setOverview(o);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const sharingWith = (overview?.sharing_with ?? []).filter(
    (g) => g.status === "accepted",
  ).length;
  const sharedWithMe = (overview?.shared_with_me ?? []).filter(
    (g) => g.status === "accepted",
  ).length;
  const pending = overview?.pending_for_me.length ?? 0;

  return (
    <>
      <p className="tv-sp-kicker">Sharing</p>
      <h2 className="tv-sp-title">Shared tools</h2>
      <PanelUtility />
      <p className="tv-sp-group">Crew lists</p>
      <div className="tv-sp-list">
        <NavLink
          to="/shared-tools"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Shared tools</span>
          {overview && pending > 0 && (
            <span className="tv-sp-count">{pending.toLocaleString("en-US")}</span>
          )}
        </NavLink>
      </div>
      {overview && (
        <ul className="tv-sp-stats">
          <li>
            <span>You share with</span>
            <strong>{sharingWith.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Shared with you</span>
            <strong>{sharedWithMe.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Invites waiting</span>
            <strong>{pending.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {overview && pending > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Invites for you</p>
          <p>
            {pending} member{pending === 1 ? " wants" : "s want"} to share
            their tool list with you — answer from the Invites section on
            the page.
          </p>
        </div>
      )}
    </>
  );
}
