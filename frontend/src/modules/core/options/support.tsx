import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function SupportOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.support.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.support.rowsToShow")}
        settings={s}
        name="rowsToShow"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Downloads (REBUILT, dashboard-flare lane 2026-11-09):
 *  the stats grid and the top-downloads strip each get a
 *  switch; one count row sizes the strip. The follow-up's
 *  list switches (showCounts / showDocuments /
 *  showWallpapers / rowsToShow) retire with the lists they
 *  governed; stored bundles carrying them are inert. */
