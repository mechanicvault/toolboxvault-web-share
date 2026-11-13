import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { getBoard, getMine } from "../../modules/feedback/api";
import { PanelUtility } from "./PanelUtility";

/**
 * The Feedback panel (Rail Steel conversion, Phase 2c).
 *
 * Links are the module's real routes: the feedback home
 * (/feedback), the two boards (/feedback/bugs,
 * /feedback/features) and the roadmap the feedback home itself
 * links. Counts come from the boards' own reads — getBoard for
 * each board (signed-in face, the full visible list the board
 * page renders) and getMine("") for the user's own post count
 * across both boards. Board rows exclude held/removed posts the
 * same way the API's board payload does; nothing is re-derived.
 */
export function FeedbackPanel() {
  const [counts, setCounts] = useState<{
    bugs: number;
    features: number;
    mine: number;
  } | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([getBoard("bug", true), getBoard("feature", true), getMine("")])
      .then(([bugs, features, mine]) => {
        if (!live) return;
        setCounts({
          bugs: bugs.length,
          features: features.length,
          mine: mine.length,
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const item = (to: string, label: string, count?: number, end = false) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      className={({ isActive }) => `tv-sp-item${isActive ? " is-active" : ""}`}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span className="tv-sp-count">{count.toLocaleString("en-US")}</span>
      )}
    </NavLink>
  );

  return (
    <>
      <p className="tv-sp-kicker">Feedback</p>
      <h2 className="tv-sp-title">Feedback</h2>
      <PanelUtility />
      <p className="tv-sp-group">Boards</p>
      <div className="tv-sp-list">
        {item("/feedback", "Feedback home", undefined, true)}
        {item("/feedback/bugs", "Bug Reports", counts?.bugs)}
        {item("/feedback/features", "Feature Requests", counts?.features)}
        {item("/roadmap", "What's coming")}
      </div>
      {counts && (
        <ul className="tv-sp-stats">
          <li>
            <span>Your posts</span>
            <strong>{counts.mine.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
    </>
  );
}
