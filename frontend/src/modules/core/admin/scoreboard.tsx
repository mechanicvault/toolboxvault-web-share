import { Link } from "react-router-dom";
import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { optBool } from "../widgetOptions";
import { Settings, AdminShell } from "./shared";
import { useAdminPanel, fmtNum, ChangeChip } from "./panelShared";

const SCORE_ROW_KEYS: Record<string, DictKey> = {
  new_users: "home.panel.row.new_users",
  new_paid: "home.panel.row.new_paid",
  cancellations: "home.panel.row.cancellations",
  tools_logged: "home.panel.row.tools_logged",
  downloads: "home.panel.row.downloads",
  prints_uploaded: "home.panel.row.prints_uploaded",
  forum_posts: "home.panel.row.forum_posts",
  support_tickets: "home.panel.row.support_tickets",
  bug_reports: "home.panel.row.bug_reports",
  ai_credits: "home.panel.row.ai_credits",
};

export function AdminScoreboardWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { panel, failed } = useAdminPanel();
  const rows = (panel?.scoreboard ?? []).filter((row) =>
    optBool(settings, `row_${row.key}`, true),
  );
  const exportCsv = () => {
    const head = [
      t("home.panel.colMetric"),
      t("home.panel.today"),
      t("home.panel.days7"),
      t("home.panel.days30"),
      t("home.panel.colChange"),
    ];
    const lines = (panel?.scoreboard ?? []).map((row) =>
      [
        t(SCORE_ROW_KEYS[row.key]),
        row.today,
        row.last_7_days,
        row.last_30_days,
        row.change_pct === null ? "" : `${row.change_pct}%`,
      ].join(","),
    );
    const blob = new Blob([[head.join(","), ...lines].join("\n")], {
      type: "text/csv",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `site-scoreboard-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <AdminShell
      titleKey="home.widget.adminScoreboard"
      icon="adminShield"
      tone="violet"
      door="/admin"
      editing={editing}
      failed={failed}
      loading={!panel && !failed}
    >
      {panel && (
        <>
          <div className="tv-panel-table" role="table">
            <div className="tv-panel-trow tv-panel-thead" role="row">
              <span>{t("home.panel.colMetric")}</span>
              <span>{t("home.panel.today")}</span>
              <span>{t("home.panel.days7")}</span>
              <span>{t("home.panel.days30")}</span>
              <span>{t("home.panel.colChange")}</span>
            </div>
            {rows.map((row) => (
              <div className="tv-panel-trow" role="row" key={row.key}>
                <span className="tv-panel-tname">
                  {t(SCORE_ROW_KEYS[row.key])}
                </span>
                <span>{fmtNum(row.today)}</span>
                <span>{fmtNum(row.last_7_days)}</span>
                <span>{fmtNum(row.last_30_days)}</span>
                <span>
                  <ChangeChip
                    pct={row.change_pct}
                    goodWhen={row.good_when}
                    current={row.last_30_days}
                  />
                </span>
              </div>
            ))}
          </div>
          <p className="tv-panel-note">{t("home.panel.changeNote")}</p>
          <div className="tv-panel-actions">
            <button
              type="button"
              className="tv-panel-btn"
              onClick={exportCsv}
            >
              {t("home.panel.exportCsv")}
            </button>
            <Link to="/admin" className="tv-panel-btn tv-panel-btn--primary">
              {t("home.panel.adminReports")}
            </Link>
          </div>
        </>
      )}
    </AdminShell>
  );
}

