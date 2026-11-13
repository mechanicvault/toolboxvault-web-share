import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { activeLocale } from "../../lib/format";
import { useAuth } from "../../modules/core/AuthContext";
import {
  getDealerStats,
  listCompanies,
  listPreferred,
  listPrivateAgents,
  warrantyCounts,
} from "../../modules/dealers/api";
import type { DealerPortalStats, WarrantyCounts } from "../../modules/dealers/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Dealer directory panel (Rail Steel conversion, Phase 2c).
 *
 * Links are the dealer's real routes: the directory (/dealers)
 * and Find an Agent (/dealers/find-agent — a registry route,
 * reachable signed-out too). There is NO dealer dashboard route:
 * the dashboard is a Home block (CorePage) and the warranty queue
 * is a section of the Dealers page itself, so neither gets a
 * lookalike link here — the warranty numbers ride the stats list
 * instead (MAPPING §3's "Dashboard / Route / Warranty requests"
 * map onto those surfaces; recorded in the INDEX deviations).
 *
 * Stats come only from calls the module already makes:
 * listCompanies / listPrivateAgents / listPreferred (the Dealers
 * page's own refresh) for everyone, and — dealer-group users
 * only, mirroring the page's own gating (WarrantyRequestsPanel
 * takes dealerGroup from account_types) — getDealerStats +
 * warrantyCounts (the DealerDashboard's own calls). Dealer-only
 * rows and the profile/route settings link render only for
 * tool_dealer accounts, exactly like the surfaces they summarize.
 */
export function DealersPanel() {
  const t = useT();
  const { user } = useAuth();
  const isDealer = (user?.account_types ?? []).includes("tool_dealer");
  const [counts, setCounts] = useState<{
    directory: number;
    mine: number;
    agents: number;
    preferred: number;
  } | null>(null);
  const [portal, setPortal] = useState<DealerPortalStats | null>(null);
  const [warranty, setWarranty] = useState<WarrantyCounts | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([listCompanies(), listPrivateAgents(), listPreferred()])
      .then(([companies, agents, preferred]) => {
        if (!live) return;
        setCounts({
          directory: companies.filter((c) => c.is_directory).length,
          mine: companies.filter((c) => !c.is_directory).length,
          agents: agents.filter((a) => !a.archived).length,
          preferred: preferred.length,
        });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!isDealer) return;
    let live = true;
    getDealerStats()
      .then((s) => {
        if (live) setPortal(s);
      })
      .catch(() => undefined);
    warrantyCounts()
      .then((c) => {
        if (live) setWarranty(c);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [isDealer]);

  const item = (to: string, label: string, end = false) => (
    <NavLink
      key={to + label}
      to={to}
      end={end}
      className={({ isActive }) =>
        `tv-sp-item${isActive ? " is-active" : ""}`
      }
    >
      <span>{label}</span>
    </NavLink>
  );

  return (
    <>
      <p className="tv-sp-kicker">{t("panel.dealers.kicker")}</p>
      <h2 className="tv-sp-title">{t("nav.dealers")}</h2>
      <PanelUtility />
      <p className="tv-sp-group">{t("panel.dealers.groupDirectory")}</p>
      <div className="tv-sp-list">
        {item("/dealers", t("panel.dealers.directory"), true)}
        {item("/dealers/find-agent", t("panel.dealers.findAgent"))}
      </div>
      {isDealer && (
        <>
          <p className="tv-sp-group">{t("panel.dealers.groupPortal")}</p>
          <div className="tv-sp-list">
            {item("/settings/dealer-profile", t("panel.dealers.profileRoute"))}
            {item("/truck-accounts", t("nav.truck-accounts"))}
          </div>
        </>
      )}
      {counts && (
        <>
          <p className="tv-sp-group">{t("panel.dealers.groupYours")}</p>
          <ul className="tv-sp-stats">
            <li>
              <span>{t("panel.dealers.directoryCompanies")}</span>
              <strong>{counts.directory.toLocaleString(activeLocale())}</strong>
            </li>
            <li>
              <span>{t("panel.dealers.myCompanies")}</span>
              <strong>{counts.mine.toLocaleString(activeLocale())}</strong>
            </li>
            <li>
              <span>{t("panel.dealers.myAgents")}</span>
              <strong>{counts.agents.toLocaleString(activeLocale())}</strong>
            </li>
            <li>
              <span>{t("panel.dealers.preferredAgents")}</span>
              <strong>{counts.preferred.toLocaleString(activeLocale())}</strong>
            </li>
          </ul>
        </>
      )}
      {isDealer && (portal || warranty) && (
        <>
          <p className="tv-sp-group">{t("panel.dealers.groupAgentSide")}</p>
          <ul className="tv-sp-stats">
            {portal && (
              <li>
                <span>{t("panel.dealers.preferredBy")}</span>
                <strong>{portal.preferred_by_count.toLocaleString(activeLocale())}</strong>
              </li>
            )}
            {portal && (
              <li>
                <span>{t("panel.dealers.companiesRepresented")}</span>
                <strong>
                  {portal.companies_represented_count.toLocaleString(activeLocale())}
                </strong>
              </li>
            )}
            {warranty && (
              <li>
                <span>{t("panel.dealers.warrantyWaiting")}</span>
                <strong>{warranty.incoming_unclaimed.toLocaleString(activeLocale())}</strong>
              </li>
            )}
            {warranty && (
              <li>
                <span>{t("panel.dealers.warrantyInHand")}</span>
                <strong>{warranty.claimed_open.toLocaleString(activeLocale())}</strong>
              </li>
            )}
          </ul>
        </>
      )}
      {isDealer && warranty && warranty.incoming_unclaimed > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">{t("panel.dealers.noteTitle")}</p>
          <p>
            {t(
              warranty.incoming_unclaimed === 1
                ? "panel.dealers.noteOne"
                : "panel.dealers.noteMany",
            ).replace("{count}", String(warranty.incoming_unclaimed))}
          </p>
        </div>
      )}
    </>
  );
}
