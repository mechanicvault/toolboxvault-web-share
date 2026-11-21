import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function DownloadsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.downloads.stats")}
          settings={s}
          name="showStats"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.downloads.weekly")}
          settings={s}
          name="showWeekly"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.downloads.tiles")}
        settings={s}
        name="tilesToShow"
        dflt={8}
        min={4}
        max={12}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** 3D Print Files (REBUILT, dashboard-flare lane 2026-11-09):
 *  the follow-up's switches carry over (count line, ratings,
 *  Upload button) and the two showcase strips + the My
 *  Uploads button get theirs; one count row sizes both
 *  strips. The old rowsToShow retires with the row list it
 *  sized; stored bundles carrying it are inert. */
