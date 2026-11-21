import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { listWishlist } from "../../modules/wishlist/api";
import type { WishlistItem } from "../../modules/wishlist/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Wishlist panel (Rail Steel conversion, Phase 2c).
 *
 * The wishlist is one page (search + the wanted/purchased list
 * are local state) — the panel links the page and summarizes the
 * page's own read, GET /wishlist/items: wanted vs purchased
 * counts and the high-priority slice of the wanted list, all
 * counted off the rows' own status/priority fields.
 */
export function WishlistPanel() {
  const [items, setItems] = useState<WishlistItem[] | null>(null);

  useEffect(() => {
    let live = true;
    listWishlist()
      .then((rows) => {
        if (live) setItems(rows);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const wanted = (items ?? []).filter((i) => i.status === "wanted");
  const purchased = (items ?? []).filter((i) => i.status === "purchased");
  const highPriority = wanted.filter((i) => i.priority === "high");

  return (
    <>
      <p className="tv-sp-kicker">Wishlist</p>
      <h2 className="tv-sp-title">Wishlist</h2>
      <PanelUtility />
      <p className="tv-sp-group">Want list</p>
      <div className="tv-sp-list">
        <NavLink
          to="/wishlist"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>Wishlist</span>
          {items !== null && wanted.length > 0 && (
            <span className="tv-sp-count">{wanted.length.toLocaleString("en-US")}</span>
          )}
        </NavLink>
      </div>
      {items !== null && (
        <ul className="tv-sp-stats">
          <li>
            <span>Wanted</span>
            <strong>{wanted.length.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>High priority</span>
            <strong>{highPriority.length.toLocaleString("en-US")}</strong>
          </li>
          <li>
            <span>Purchased</span>
            <strong>{purchased.length.toLocaleString("en-US")}</strong>
          </li>
        </ul>
      )}
      {items !== null && items.length === 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">Nothing wanted yet</p>
          <p>
            Add the tools you&apos;re saving for — when you buy one, it
            converts straight into your inventory.
          </p>
        </div>
      )}
    </>
  );
}
