import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { getCategories } from "../../modules/forum/api";
import type { ForumCategory } from "../../modules/forum/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Community Forum panel (Rail Steel conversion, Phase 2c).
 *
 * Category links are the forum's real routes
 * (/forum/category/:id) from the board's own read, GET
 * /forum/categories (signed-in face — the panel only renders
 * signed-in), each carrying its thread_count chip; totals are
 * summed from the same payload. There is no global new-thread
 * route — the composer lives on each category page — so no
 * new-thread link is invented (MAPPING §3 deviation, recorded in
 * the INDEX).
 */

const CATEGORY_CAP = 10;

export function ForumPanel() {
  const [categories, setCategories] = useState<ForumCategory[] | null>(null);

  useEffect(() => {
    let live = true;
    getCategories(true)
      .then((rows) => {
        if (live) setCategories(rows.filter((c) => c.is_active));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const shown = (categories ?? []).slice(0, CATEGORY_CAP);
  const threadTotal = (categories ?? []).reduce((a, c) => a + c.thread_count, 0);
  const postTotal = (categories ?? []).reduce((a, c) => a + c.post_count, 0);

  return (
    <>
      <p className="tv-sp-kicker">Community</p>
      <h2 className="tv-sp-title">Community Forum</h2>
      <PanelUtility />
      <p className="tv-sp-group">Rooms</p>
      <div className="tv-sp-list">
        <NavLink
          to="/forum"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>All rooms</span>
        </NavLink>
        {shown.map((category) => (
          <NavLink
            key={category.id}
            to={`/forum/category/${category.id}`}
            className={({ isActive }) =>
              `tv-sp-item${isActive ? " is-active" : ""}`
            }
          >
            <span>{category.name}</span>
            <span className="tv-sp-count">
              {category.thread_count.toLocaleString("en-US")}
            </span>
          </NavLink>
        ))}
      </div>
      {categories !== null && categories.length > shown.length && (
        <p className="tv-sp-hint">
          +{categories.length - shown.length} more rooms — the full board is
          on the page.
        </p>
      )}
      {categories !== null && (
        <ul className="tv-sp-stats">
          <li>
            <span>Rooms</span>
            <strong>{categories.length.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Threads</span>
            <strong>{threadTotal.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Posts</span>
            <strong>{postTotal.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
    </>
  );
}
