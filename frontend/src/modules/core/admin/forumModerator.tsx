import { useT } from "../../../i18n/LocaleContext";
import { optBool } from "../widgetOptions";
import { useAdminWidgets, Settings, StatRow, AdminShell, Rows } from "./shared";

export function AdminForumModeratorWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.forum_moderator;
  return (
    <AdminShell
      titleKey="home.widget.adminForumModerator"
      icon="adminForum"
      tone="violet"
      door="/moderation"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <>
          <Rows>
            {optBool(settings, "showFlags", true) && (
              <StatRow
                label={t("home.admin.flaggedNow")}
                value={data.open_flags}
                editing={editing}
              />
            )}
            {optBool(settings, "showHeld", true) && (
              <StatRow
                label={t("home.admin.heldNow")}
                value={data.held}
                editing={editing}
              />
            )}
            {optBool(settings, "showNewPosts", true) && (
              <StatRow
                label={t("home.admin.newPostsToday")}
                value={data.new_posts_today}
                editing={editing}
              />
            )}
            {optBool(settings, "showFlags", true) &&
              data.flagged.map((row, i) => (
                <StatRow
                  key={`flag-${i}`}
                  label={row.title || row.excerpt || "—"}
                  value={row.reason || "⚑"}
                  href={row.href}
                  editing={editing}
                />
              ))}
            {optBool(settings, "showTop", true) &&
              data.top_threads.length > 0 && (
                <>
                  <div className="tv-admin-subhead">{t("home.admin.topThreads")}</div>
                  {data.top_threads.map((row, i) => (
                    <StatRow
                      key={`top-${i}`}
                      label={row.title}
                      value={`${row.replies} ${t("home.admin.replies")}`}
                      href={row.href}
                      editing={editing}
                    />
                  ))}
                </>
              )}
          </Rows>
          {data.open_flags === 0 && data.held === 0 && (
            <p className="tv-muted">{t("home.admin.nothingWaiting")}</p>
          )}
        </>
      )}
    </AdminShell>
  );
}

