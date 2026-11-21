import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export const SCOREBOARD_ROW_OPTS: { name: string; labelKey: DictKey }[] = [
  { name: "row_new_users", labelKey: "home.panel.row.new_users" },
  { name: "row_new_paid", labelKey: "home.panel.row.new_paid" },
  { name: "row_cancellations", labelKey: "home.panel.row.cancellations" },
  { name: "row_tools_logged", labelKey: "home.panel.row.tools_logged" },
  { name: "row_downloads", labelKey: "home.panel.row.downloads" },
  { name: "row_prints_uploaded", labelKey: "home.panel.row.prints_uploaded" },
  { name: "row_forum_posts", labelKey: "home.panel.row.forum_posts" },
  { name: "row_support_tickets", labelKey: "home.panel.row.support_tickets" },
  { name: "row_bug_reports", labelKey: "home.panel.row.bug_reports" },
  { name: "row_ai_credits", labelKey: "home.panel.row.ai_credits" },
];

export function AdminScoreboardOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      {SCOREBOARD_ROW_OPTS.map((row) => (
        <CheckRow key={row.name} label={t(row.labelKey)} settings={s} name={row.name} dflt setSetting={api.setSetting} />
      ))}
    </OptionsGroup>
  );
}

