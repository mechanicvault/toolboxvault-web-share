import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function AdminBoardOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showTotal")} settings={s} name="showTotal" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showOpen")} settings={s} name="showOpen" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewWeek")} settings={s} name="showNewWeek" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showDone")} settings={s} name="showDone" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showHeld")} settings={s} name="showHeld" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showTop")} settings={s} name="showTop" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

