import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function AdminForumModeratorOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showFlags")} settings={s} name="showFlags" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showHeld")} settings={s} name="showHeld" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewPosts")} settings={s} name="showNewPosts" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showTopThreads")} settings={s} name="showTop" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

