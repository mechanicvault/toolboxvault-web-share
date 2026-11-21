import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function AdminOverviewOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.panel.showHero")} settings={s} name="showHero" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showSparkline")} settings={s} name="showSparkline" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showPaying")} settings={s} name="showPaying" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showRevenue")} settings={s} name="showRevenue" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showFree")} settings={s} name="showFree" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showDownloadsTile")} settings={s} name="showDownloadsTile" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showToolsTile")} settings={s} name="showToolsTile" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showAiTile")} settings={s} name="showAiTile" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.panel.showAttention")} settings={s} name="showAttention" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

