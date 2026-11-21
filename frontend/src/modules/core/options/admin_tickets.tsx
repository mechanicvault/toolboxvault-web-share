import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function AdminTicketsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showOpen")} settings={s} name="showOpen" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showClosed")} settings={s} name="showClosed" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showUnanswered")} settings={s} name="showUnanswered" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showLatest")} settings={s} name="showLatest" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

