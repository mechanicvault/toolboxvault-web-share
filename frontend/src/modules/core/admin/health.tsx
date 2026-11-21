import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { optBool } from "../widgetOptions";
import { Settings, AdminShell } from "./shared";
import { PanelCheck, useAdminPanel } from "./panelShared";

const HEALTH_NAME_KEYS: Record<string, DictKey> = {
  database: "home.panel.health.database",
  storage: "home.panel.health.storage",
  backup: "home.panel.health.backup",
  email: "home.panel.health.email",
  stripe: "home.panel.health.stripe",
  ai: "home.panel.health.ai",
  jobs: "home.panel.health.jobs",
};

const HEALTH_STATUS_KEYS: Record<PanelCheck["status"], DictKey> = {
  ok: "home.panel.status.ok",
  watch: "home.panel.status.watch",
  check: "home.panel.status.check",
  off: "home.panel.status.off",
  unknown: "home.panel.status.unknown",
};

export function AdminHealthWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { panel, failed } = useAdminPanel();
  const health = panel?.health;
  const checks = (health?.checks ?? []).filter((c) =>
    optBool(settings, `check_${c.key}`, true),
  );
  const firstIssue = health?.checks.find((c) => c.status !== "ok");
  const ring =
    health && health.total > 0 ? health.ok_count / health.total : 0;
  const R = 25;
  const CIRC = 2 * Math.PI * R;
  return (
    <AdminShell
      titleKey="home.widget.adminHealth"
      icon="adminShield"
      tone="success"
      door="/admin"
      editing={editing}
      failed={failed}
      loading={!panel && !failed}
    >
      {health && (
        <>
          {optBool(settings, "showSummary", true) && (
            <div className="tv-panel-health-head">
              <span className="tv-panel-ring">
                <svg viewBox="0 0 60 60" width="60" height="60" aria-hidden="true">
                  <circle
                    cx="30"
                    cy="30"
                    r={R}
                    fill="none"
                    stroke="var(--edge)"
                    strokeWidth="5"
                  />
                  <circle
                    cx="30"
                    cy="30"
                    r={R}
                    fill="none"
                    stroke={firstIssue ? "var(--accent)" : "var(--success)"}
                    strokeWidth="5"
                    strokeLinecap="round"
                    strokeDasharray={`${(ring * CIRC).toFixed(1)} ${CIRC.toFixed(1)}`}
                    transform="rotate(-90 30 30)"
                  />
                </svg>
                <span className="tv-panel-ring-text">
                  {health.ok_count}/{health.total}
                </span>
              </span>
              <div className="tv-panel-health-words">
                <span className="tv-panel-health-title">
                  {firstIssue
                    ? t("home.panel.healthCheckTitle")
                    : t("home.panel.healthAllRunning")}
                </span>
                <span className="tv-panel-health-sub">
                  {firstIssue
                    ? `${t(HEALTH_NAME_KEYS[firstIssue.key])} — ${firstIssue.detail}`
                    : t("home.panel.healthAllSub")}
                </span>
              </div>
            </div>
          )}
          <div className="tv-panel-checks">
            {checks.map((check) => (
              <div className="tv-panel-check" key={check.key}>
                <span
                  className="tv-panel-dot"
                  data-status={check.status}
                  aria-hidden="true"
                />
                <span className="tv-panel-check-main">
                  <span className="tv-panel-check-name">
                    {t(HEALTH_NAME_KEYS[check.key])}
                  </span>
                  <span className="tv-panel-check-detail">{check.detail}</span>
                </span>
                <span className="tv-panel-check-value">{check.value}</span>
                <span className="tv-panel-pill" data-status={check.status}>
                  {t(HEALTH_STATUS_KEYS[check.status])}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </AdminShell>
  );
}
