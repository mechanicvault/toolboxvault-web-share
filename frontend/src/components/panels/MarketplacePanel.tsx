import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { activeLocale } from "../../lib/format";
import { useAuth } from "../../modules/core/AuthContext";
import {
  getPublicReputation,
  listMine,
} from "../../modules/marketplace/api";
import {
  reputationBadge,
  type ReputationSummary,
} from "../../modules/marketplace/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Tools For Sale (Marketplace) panel (Rail Steel conversion,
 * Phase 2a): Board / My listings / New listing links, and the
 * signed-in user's OWN reputation summary — read through the
 * module's existing reputation consumer, GET
 * /marketplace/reputation/{userId} (the same aggregate,
 * reputation.summary_for server-side, that the public profile
 * renders), plus the active-listing count from listMine (the My
 * Listings page's own call). No new endpoints; a user with no
 * deals yet gets the honest "New seller" line, never an
 * invented rating.
 */
export function MarketplacePanel() {
  const t = useT();
  const { user } = useAuth();
  const [summary, setSummary] = useState<ReputationSummary | null>(null);
  const [activeListings, setActiveListings] = useState<number | null>(null);

  useEffect(() => {
    if (!user) return;
    let live = true;
    getPublicReputation(user.id)
      .then((rep) => {
        if (live) setSummary(rep.summary);
      })
      .catch(() => undefined);
    listMine()
      .then((rows) => {
        if (live) {
          setActiveListings(rows.filter((r) => r.status === "active").length);
        }
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [user]);

  return (
    <>
      <p className="tv-sp-kicker">{t("panel.marketplace.kicker")}</p>
      <h2 className="tv-sp-title">{t("nav.marketplace")}</h2>
      <PanelUtility />
      <p className="tv-sp-group">{t("panel.marketplace.board")}</p>
      <div className="tv-sp-list">
        <NavLink
          to="/marketplace"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>{t("panel.marketplace.board")}</span>
        </NavLink>
        <NavLink
          to="/marketplace/mine"
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>{t("marketplace.mine.myListings")}</span>
          {activeListings !== null && (
            <span className="tv-sp-count">
              {activeListings.toLocaleString(activeLocale())}
            </span>
          )}
        </NavLink>
        <NavLink
          to="/marketplace/new"
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>{t("panel.marketplace.newListing")}</span>
        </NavLink>
      </div>
      {summary && (
        <>
          <p className="tv-sp-group">{t("panel.marketplace.reputation")}</p>
          <ul className="tv-sp-stats">
            <li>
              <span>{t("panel.marketplace.sellerRating")}</span>
              <strong>
              {summary.count > 0 && summary.average !== null
                ? reputationBadge(summary)
                : t("panel.marketplace.newSeller")}
            </strong>
            </li>
            <li>
              <span>{t("panel.marketplace.completedDeals")}</span>
              <strong>{summary.completed_deals.toLocaleString(activeLocale())}</strong>
            </li>
          </ul>
        </>
      )}
      {summary && summary.count === 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">{t("panel.marketplace.newSeller")}</p>
          <p>{t("panel.marketplace.noRatings")}</p>
        </div>
      )}
    </>
  );
}
