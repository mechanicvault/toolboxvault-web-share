import { useT } from "../../../i18n/LocaleContext";
import { formatDate } from "../../../lib/format";
import { optBool } from "../widgetOptions";
import { useAdminWidgets, Settings, StatRow, AdminShell, Rows } from "./shared";

export function AdminTicketsWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.tickets;
  return (
    <AdminShell
      titleKey="home.widget.adminTickets"
      icon="adminTickets"
      tone="info"
      door="/admin/support"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <Rows>
          {optBool(settings, "showOpen", true) && (
            <StatRow label={t("home.admin.open")} value={data.open} editing={editing} />
          )}
          {optBool(settings, "showClosed", true) && (
            <StatRow label={t("home.admin.closed")} value={data.closed} editing={editing} />
          )}
          {optBool(settings, "showUnanswered", true) && (
            <StatRow
              label={t("home.admin.unanswered")}
              value={data.unanswered}
              editing={editing}
            />
          )}
          {optBool(settings, "showLatest", true) && data.latest.length > 0 && (
            <div className="tv-admin-subhead">{t("home.admin.latestOpen")}</div>
          )}
          {optBool(settings, "showLatest", true) &&
            data.latest.map((row, i) => (
              <StatRow
                key={`latest-${i}`}
                label={row.subject}
                value={formatDate(row.updated_at)}
                href={row.href}
                editing={editing}
              />
            ))}
        </Rows>
      )}
    </AdminShell>
  );
}

