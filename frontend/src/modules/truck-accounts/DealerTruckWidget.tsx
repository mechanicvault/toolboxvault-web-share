/**
 * The dealer's OWN Truck Accounts widget (sheet row 29,
 * 2026-11-15). Ryan's words: a dealer's truck accounts "is
 * different than everyone elses. I get to see everyone that
 * has a truck account with me" — so this widget is built from
 * the dealer's side of the tab: what he is OWED, who owes it,
 * who is late, and what came in this week. Dealer-group seats
 * only (registered in core's homeRegistry under
 * "dealer_truck_accounts"); a dealer-only seat is not offered
 * the customer-side truck widget at all.
 *
 * Body anatomy follows the widget standard: a counts line,
 * three stat tiles, then every customer as a ruled row —
 * name with the company quiet underneath, next due date, the
 * standing pill in its OWN column, and the balance. Rows open
 * the account's own page. Copy is keyed EN+ES like every
 * surface.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Panel, Spinner, buttonClasses } from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { formatDate } from "../../lib/format";
import { formatMoney } from "../../lib/money";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import { getDealerDashboard } from "./api";
import type { TruckDashboard } from "./types";
import "./dealerTruckWidget.css";

function settingNum(
  settings: Record<string, BlockSettingValue> | undefined,
  name: string,
  dflt: number,
): number {
  const v = settings?.[name];
  return typeof v === "number" ? v : dflt;
}

function settingBool(
  settings: Record<string, BlockSettingValue> | undefined,
  name: string,
  dflt: boolean,
): boolean {
  const v = settings?.[name];
  return typeof v === "boolean" ? v : dflt;
}

export default function DealerTruckWidget({
  settings,
}: {
  settings?: Record<string, BlockSettingValue>;
}) {
  const t = useT();
  const [data, setData] = useState<TruckDashboard | null | undefined>(
    undefined,
  );
  useEffect(() => {
    getDealerDashboard()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const head = (
    <div className="tv-widget-head">
      <span className="tv-stat-icon" data-tone="success" aria-hidden="true">
        <ArtIcon name="truck" size={24} />
      </span>
      <h3 className="tv-widget-title">
        <Link to="/dealers" className="tv-widget-title-link">
          {t("home.widget.dealerTruck.title")}
        </Link>
      </h3>
    </div>
  );
  if (data === undefined) {
    return (
      <Panel className="tv-home-widget">
        {head}
        <p className="tv-dtruck-empty">
          <Spinner size="sm" /> {t("shell.loading")}
        </p>
      </Panel>
    );
  }
  if (data === null) {
    return (
      <Panel className="tv-home-widget">
        {head}
        <p className="tv-dtruck-empty">{t("truck.widget.loadFailed")}</p>
      </Panel>
    );
  }

  const rowsVisible = settingNum(settings, "rowsVisible", 5);
  const showReceived = settingBool(settings, "showReceived", true);
  const rows = data.accounts.slice(0, rowsVisible);
  const overdueCount = data.accounts.filter(
    (a) => Number(a.amount_past_due) > 0,
  ).length;

  return (
    <Panel className="tv-home-widget">
      {head}
      <p className="tv-dtruck-counts">
        <strong>{data.open_accounts}</strong>{" "}
        {t("truck.widget.openAccounts")} ·{" "}
        <strong>{formatMoney(data.total_outstanding, null, true)}</strong>{" "}
        {t("truck.widget.owedToYou")}
      </p>
      <div className="tv-dtruck-tiles">
        <div className="tv-dtruck-tile">
          <span className="tv-dtruck-tile-label">
            {t("truck.widget.tileOwed")}
          </span>
          <span className="tv-dtruck-tile-value">
            {formatMoney(data.total_outstanding, null, true)}
          </span>
        </div>
        <div className="tv-dtruck-tile">
          <span className="tv-dtruck-tile-label">
            {t("truck.widget.tileDueWeek")}
          </span>
          <span className="tv-dtruck-tile-value">
            {formatMoney(data.due_total, null, true)}
          </span>
        </div>
        <div
          className="tv-dtruck-tile"
          data-warn={overdueCount > 0 ? "true" : undefined}
        >
          <span className="tv-dtruck-tile-label">
            {t("truck.widget.tileOverdue")}
          </span>
          <span className="tv-dtruck-tile-value">
            {formatMoney(data.overdue_total, null, true)}
          </span>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="tv-dtruck-empty">{t("truck.widget.empty")}</p>
      ) : (
        <div className="tv-dtruck-rows">
          {rows.map((row) => {
            const pastDue = Number(row.amount_past_due) > 0;
            return (
              <Link
                key={row.account_id}
                className="tv-dtruck-row"
                to={`/truck-accounts/${row.account_id}`}
              >
                <span className="tv-dtruck-name">
                  <span className="tv-dtruck-name-main">
                    {row.customer_name}
                  </span>
                  {row.company_name && (
                    <span className="tv-dtruck-name-sub">
                      {row.company_name}
                    </span>
                  )}
                </span>
                <span className="tv-dtruck-due">
                  {row.next_due_date
                    ? formatDate(row.next_due_date)
                    : "—"}
                </span>
                <span className="tv-dtruck-pill">
                  {pastDue ? (
                    <Badge tone="danger">
                      {t("truck.widget.pillOverdue")}
                    </Badge>
                  ) : row.missed_payments > 0 ? (
                    <Badge tone="warning">
                      {t("truck.widget.pillMissed").replace(
                        "{count}",
                        String(row.missed_payments),
                      )}
                    </Badge>
                  ) : row.status === "invited" ? (
                    <Badge tone="neutral">
                      {t("truck.widget.pillInvited")}
                    </Badge>
                  ) : null}
                </span>
                <span className="tv-dtruck-balance">
                  {formatMoney(row.balance, null, true)}
                </span>
              </Link>
            );
          })}
        </div>
      )}
      <div className="tv-dtruck-foot">
        {showReceived ? (
          <span className="tv-dtruck-received">
            {t("truck.widget.receivedWeek")}{" "}
            <strong>
              {formatMoney(data.received_this_week, null, true)}
            </strong>
          </span>
        ) : (
          <span />
        )}
        <Link to="/dealers" className={buttonClasses("primary", "sm")}>
          {t("truck.widget.openPage")}
        </Link>
      </div>
    </Panel>
  );
}
