import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { formatMoney } from "../../lib/money";
import { listAccounts } from "../../modules/truck-accounts/api";
import type { TruckAccount } from "../../modules/truck-accounts/types";
import { useT } from "../../i18n/LocaleContext";
import { PanelUtility } from "./PanelUtility";

/**
 * The Truck Accounts panel (Rail Steel conversion, Phase 2c).
 *
 * One list route (/truck-accounts) plus per-account detail pages
 * (parameterized — never panel links). The panel summarizes the
 * list page's own read, GET /truck-accounts/accounts: counts by
 * the caller's side of the tab (my_role) and by status, and the
 * total outstanding balance summed from the rows' own balance
 * strings (money is decimal-as-string; the sum is formatted
 * through the one money formatter). An invite addressed to the
 * signed-in user (status invited, my_role customer) raises the
 * note — accepting happens on the account's own page.
 */
export function TruckAccountsPanel() {
  const t = useT();
  const [accounts, setAccounts] = useState<TruckAccount[] | null>(null);

  useEffect(() => {
    let live = true;
    listAccounts()
      .then((rows) => {
        if (live) setAccounts(rows);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const rows = accounts ?? [];
  const active = rows.filter((a) => a.status === "active");
  const invitesForMe = rows.filter(
    (a) => a.status === "invited" && a.my_role === "customer",
  );
  const invitesSent = rows.filter(
    (a) => a.status === "invited" && a.my_role === "dealer",
  );
  const asDealer = rows.filter((a) => a.my_role === "dealer");
  const asCustomer = rows.filter((a) => a.my_role === "customer");
  const outstanding = active.reduce(
    (acc, a) => acc + (Number(a.balance) || 0),
    0,
  );

  return (
    <>
      <p className="tv-sp-kicker">{t("truck.panel.kicker")}</p>
      <h2 className="tv-sp-title">{t("nav.truck-accounts")}</h2>
      <PanelUtility />
      <p className="tv-sp-group">{t("truck.panel.tabsGroup")}</p>
      <div className="tv-sp-list">
        <NavLink
          to="/truck-accounts"
          end
          className={({ isActive }) =>
            `tv-sp-item${isActive ? " is-active" : ""}`
          }
        >
          <span>{t("truck.panel.allAccounts")}</span>
          {accounts !== null && rows.length > 0 && (
            <span className="tv-sp-count">{rows.length.toLocaleString("en-US")}</span>
          )}
        </NavLink>
      </div>
      {accounts !== null && rows.length > 0 && (
        <ul className="tv-sp-stats">
          <li>
            <span>{t("truck.panel.activeAccounts")}</span>
            <strong>{active.length.toLocaleString("en-US")}</strong>
          </li>
          {asDealer.length > 0 && (
            <li>
              <span>{t("truck.panel.youAsDealer")}</span>
              <strong>{asDealer.length.toLocaleString("en-US")}</strong>
            </li>
          )}
          {asCustomer.length > 0 && (
            <li>
              <span>{t("truck.panel.youAsCustomer")}</span>
              <strong>{asCustomer.length.toLocaleString("en-US")}</strong>
            </li>
          )}
          <li>
            <span>{t("truck.panel.outstanding")}</span>
            <strong>{formatMoney(String(outstanding), null, true)}</strong>
          </li>
        </ul>
      )}
      {invitesForMe.length > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">{t("truck.panel.inviteWaitingTitle")}</p>
          <p>
            {t("truck.panel.inviteWaitingBody").replace(
              "{count}",
              String(invitesForMe.length),
            )}
          </p>
        </div>
      )}
      {accounts !== null && invitesSent.length > 0 && (
        <div className="tv-sp-note">
          <p className="tv-sp-note-title">{t("truck.panel.invitesSentTitle")}</p>
          <p>
            {t("truck.panel.invitesSentBody").replace(
              "{count}",
              String(invitesSent.length),
            )}
          </p>
        </div>
      )}
    </>
  );
}
