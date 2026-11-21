import { useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../../../i18n/LocaleContext";
import { formatDate } from "../../../lib/format";
import { optBool } from "../widgetOptions";
import { Settings, AdminShell } from "./shared";
import { useAdminPanel, fmtNum, ChangeChip, PanelWindow } from "./panelShared";

export function AdminOverviewWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { panel, failed } = useAdminPanel();
  const [window, setWindow] = useState<PanelWindow>("last_7_days");
  const data = panel?.overview;
  const tiles = data?.tiles[window];
  const changes =
    window === "today" ? null : data?.tile_changes[window];
  const memberPct = (n: number) =>
    data && data.users_total > 0
      ? `${Math.round((n / data.users_total) * 100)}% ${t("home.panel.ofMembers")}`
      : "";
  const windowLabel =
    window === "today"
      ? t("home.panel.today")
      : window === "last_7_days"
        ? t("home.panel.last7")
        : t("home.panel.last30");
  return (
    <AdminShell
      titleKey="home.widget.adminOverview"
      icon="adminShield"
      tone="info"
      door="/admin"
      editing={editing}
      failed={failed}
      loading={!panel && !failed}
    >
      {data && tiles && (
        <>
          {optBool(settings, "showHero", true) && (
            <div className="tv-panel-hero">
              <div className="tv-panel-hero-main">
                <span className="tv-panel-hero-label">
                  {t("home.panel.totalUsers")}
                </span>
                <span className="tv-panel-hero-value">
                  {fmtNum(data.users_total)}
                </span>
                <span className="tv-panel-hero-sub">
                  {t("home.panel.newIn30").replace(
                    "{count}",
                    fmtNum(data.new_last_30_days),
                  )}
                </span>
              </div>
              <div className="tv-panel-hero-side">
                <span className="tv-panel-chip" data-tone="good">
                  +{fmtNum(data.new_last_7_days)} {t("home.panel.thisWeek")}
                </span>
              </div>
            </div>
          )}
          {optBool(settings, "showSparkline", true) &&
            data.signups_series_30d.length > 1 && (
              <SignupsChart
                series={data.signups_series_30d}
                startIso={data.signups_series_start}
              />
            )}
          <div className="tv-panel-tabs" role="tablist">
            {(["today", "last_7_days", "last_30_days"] as PanelWindow[]).map(
              (w) => (
                <button
                  key={w}
                  type="button"
                  role="tab"
                  aria-selected={window === w}
                  className="tv-panel-tab"
                  data-active={window === w}
                  onClick={() => setWindow(w)}
                >
                  {w === "today"
                    ? t("home.panel.today")
                    : w === "last_7_days"
                      ? t("home.panel.days7")
                      : t("home.panel.days30")}
                </button>
              ),
            )}
          </div>
          <div className="tv-panel-tiles">
            {optBool(settings, "showPaying", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.payingMembers")}
                </span>
                <span className="tv-panel-tile-value">
                  {fmtNum(data.paying_users)}
                </span>
                <span className="tv-panel-tile-sub">
                  {memberPct(data.paying_users)}
                </span>
              </div>
            )}
            {optBool(settings, "showRevenue", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.monthlyRevenue")}
                </span>
                <span className="tv-panel-tile-value">
                  ${fmtNum(Math.round(Number(data.mrr)))}
                </span>
                <span className="tv-panel-tile-sub">
                  {t("home.panel.recurring")}
                </span>
              </div>
            )}
            {optBool(settings, "showFree", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.freeMembers")}
                </span>
                <span className="tv-panel-tile-value">
                  {fmtNum(data.free_users)}
                </span>
                <span className="tv-panel-tile-sub">
                  {memberPct(data.free_users)}
                </span>
              </div>
            )}
            {optBool(settings, "showDownloadsTile", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.downloads")} · {windowLabel}
                </span>
                <span className="tv-panel-tile-value">
                  {fmtNum(tiles.downloads)}
                </span>
                {changes ? (
                  <ChangeChip
                    pct={changes.downloads}
                    goodWhen="up"
                    current={tiles.downloads}
                  />
                ) : (
                  <span className="tv-panel-tile-sub">
                    {t("home.panel.soFarToday")}
                  </span>
                )}
              </div>
            )}
            {optBool(settings, "showToolsTile", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.toolsLogged")} · {windowLabel}
                </span>
                <span className="tv-panel-tile-value">
                  {fmtNum(tiles.tools_logged)}
                </span>
                {changes ? (
                  <ChangeChip
                    pct={changes.tools_logged}
                    goodWhen="up"
                    current={tiles.tools_logged}
                  />
                ) : (
                  <span className="tv-panel-tile-sub">
                    {t("home.panel.soFarToday")}
                  </span>
                )}
              </div>
            )}
            {optBool(settings, "showAiTile", true) && (
              <div className="tv-panel-tile">
                <span className="tv-panel-tile-label">
                  {t("home.panel.aiCost")} · {windowLabel}
                </span>
                <span className="tv-panel-tile-value">
                  {fmtNum(tiles.ai_credits)}
                  <span className="tv-panel-tile-unit">
                    {" "}
                    {t("home.panel.credits")}
                  </span>
                </span>
                {changes ? (
                  <ChangeChip
                    pct={changes.ai_credits}
                    goodWhen="down"
                    current={tiles.ai_credits}
                  />
                ) : (
                  <span className="tv-panel-tile-sub">
                    {t("home.panel.soFarToday")}
                  </span>
                )}
              </div>
            )}
          </div>
          {optBool(settings, "showAttention", true) && (
            <>
              <div className="tv-admin-subhead">
                {t("home.panel.needsAttention")}
              </div>
              <div className="tv-panel-attention">
                <Link to="/admin/support" className="tv-panel-attn">
                  <span className="tv-panel-attn-value">
                    {fmtNum(data.attention.tickets_open)}
                  </span>
                  <span className="tv-panel-attn-label">
                    {t("home.panel.openTickets")}
                  </span>
                  {data.attention.tickets_over_24h > 0 && (
                    <span className="tv-panel-attn-sub" data-warn="true">
                      {t("home.panel.waiting24").replace(
                        "{count}",
                        fmtNum(data.attention.tickets_over_24h),
                      )}
                    </span>
                  )}
                </Link>
                <Link to="/moderation" className="tv-panel-attn">
                  <span className="tv-panel-attn-value">
                    {fmtNum(data.attention.flagged_posts)}
                  </span>
                  <span className="tv-panel-attn-label">
                    {t("home.panel.flaggedPosts")}
                  </span>
                </Link>
                <Link to="/moderation" className="tv-panel-attn">
                  <span className="tv-panel-attn-value">
                    {fmtNum(data.attention.held_posts)}
                  </span>
                  <span className="tv-panel-attn-label">
                    {t("home.panel.heldPosts")}
                  </span>
                </Link>
                <Link to="/help#bugs" className="tv-panel-attn">
                  <span className="tv-panel-attn-value">
                    {fmtNum(data.attention.bug_reports_open)}
                  </span>
                  <span className="tv-panel-attn-label">
                    {t("home.panel.openBugs")}
                  </span>
                  {data.attention.bug_reports_high > 0 && (
                    <span className="tv-panel-attn-sub" data-warn="true">
                      {t("home.panel.highPriority").replace(
                        "{count}",
                        fmtNum(data.attention.bug_reports_high),
                      )}
                    </span>
                  )}
                </Link>
              </div>
            </>
          )}
        </>
      )}
    </AdminShell>
  );
}

/**
 * Sheet row 50 (owner, 2026-11-15): the signups graph sits in
 * the top main area of the overview, stretched across a good
 * portion of the widget's width, showing the past month.
 * Moving the mouse over it reads out the EXACT date and the
 * signup count for the point under the mouse (a guide line +
 * dot mark the point); away from the mouse it rests on the
 * latest day. Dates come from the payload's series start —
 * index i is that date plus i days, never a client guess.
 */
function SignupsChart({
  series,
  startIso,
}: {
  series: number[];
  startIso: string;
}) {
  const t = useT();
  const [hover, setHover] = useState<number | null>(null);
  const W = 600;
  const H = 150;
  const PAD = 8;
  const max = Math.max(...series, 1);
  const last = series.length - 1;
  const x = (i: number) => PAD + (i / last) * (W - PAD * 2);
  const y = (v: number) => H - 12 - (v / max) * (H - 34);
  const points = series
    .map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const dateFor = (i: number): string => {
    const [yy, mm, dd] = startIso.split("-").map(Number);
    const d = new Date(Date.UTC(yy, (mm || 1) - 1, (dd || 1) + i));
    return formatDate(d.toISOString().slice(0, 10));
  };
  const shown = hover ?? last;
  const count = series[shown];
  const readout = `${dateFor(shown)} · ${t(
    count === 1 ? "home.panel.chartSignupOne" : "home.panel.chartSignupMany",
  ).replace("{count}", fmtNum(count))}`;
  return (
    <div className="tv-panel-chart">
      <div className="tv-panel-chart-head">
        <span className="tv-panel-chart-label">{t("home.panel.signups30")}</span>
        <span className="tv-panel-chart-readout" data-live={hover !== null}>
          {readout}
        </span>
      </div>
      <svg
        className="tv-panel-chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t("home.panel.signups30")}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const frac = (e.clientX - rect.left) / rect.width;
          const i = Math.round(frac * last);
          setHover(Math.max(0, Math.min(last, i)));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <polygon
          points={`${PAD},${H - 4} ${points} ${W - PAD},${H - 4}`}
          fill="var(--accent)"
          opacity="0.16"
        />
        <polyline
          points={points}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {hover !== null && (
          <>
            <line
              x1={x(hover)}
              y1={6}
              x2={x(hover)}
              y2={H - 6}
              stroke="var(--text-muted)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle
              cx={x(hover)}
              cy={y(series[hover])}
              r="4.5"
              fill="var(--accent)"
              stroke="var(--surface)"
              strokeWidth="2"
            />
          </>
        )}
      </svg>
      <div className="tv-panel-chart-ends">
        <span>{dateFor(0)}</span>
        <span>{dateFor(last)}</span>
      </div>
    </div>
  );
}

