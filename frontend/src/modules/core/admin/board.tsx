import { useT } from "../../../i18n/LocaleContext";
import { optBool } from "../widgetOptions";
import { useAdminWidgets, Settings, StatRow, AdminShell, Rows } from "./shared";

export function AdminBoardWidget({
  board,
  editing = false,
  settings = {},
}: {
  board: "bug" | "feature";
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = board === "bug" ? payload?.bug_reports : payload?.feature_requests;
  const boardPath = board === "bug" ? "/help#bugs" : "/help#features";
  return (
    <AdminShell
      titleKey={
        board === "bug"
          ? "home.widget.adminBugReports"
          : "home.widget.adminFeatureRequests"
      }
      icon={board === "bug" ? "adminBug" : "adminFeature"}
      tone={board === "bug" ? "danger" : "warning"}
      door={boardPath}
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <Rows>
          {optBool(settings, "showTotal", true) && (
            <StatRow label={t("home.admin.total")} value={data.total} editing={editing} />
          )}
          {optBool(settings, "showOpen", true) && (
            <StatRow label={t("home.admin.open")} value={data.open} editing={editing} />
          )}
          {optBool(settings, "showNewWeek", true) && (
            <StatRow
              label={t("home.admin.newThisWeek")}
              value={data.new_week}
              editing={editing}
            />
          )}
          {optBool(settings, "showDone", true) && (
            <StatRow label={t("home.admin.done")} value={data.done} editing={editing} />
          )}
          {optBool(settings, "showHeld", true) && (
            <StatRow label={t("home.admin.held")} value={data.held} editing={editing} />
          )}
          {optBool(settings, "showTop", true) && data.top && (
            <StatRow
              label={t("home.admin.topPost")}
              value={
                <>
                  {data.top.title}{" "}
                  <span className="tv-admin-note">▲ {data.top.votes}</span>
                </>
              }
              href={data.top.href}
              editing={editing}
            />
          )}
        </Rows>
      )}
    </AdminShell>
  );
}

