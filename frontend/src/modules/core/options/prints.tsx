import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function PrintsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.prints.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.ratings")}
          settings={s}
          name="showRatings"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.newStrip")}
          settings={s}
          name="showNew"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.topStrip")}
          settings={s}
          name="showTop"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.uploadButton")}
          settings={s}
          name="showUpload"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.mineButton")}
          settings={s}
          name="showMine"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.prints.tiles")}
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

/** Reports (was Quick Reports; renamed + rebuilt by the
 *  owner's 2026-11-14 order): WHICH of the user's quick
 *  reports the widget lists — one checkbox per report, the
 *  Flyers options' hidden-set pattern (unchecking stores the
 *  id in hiddenReports; absence of the key = everything
 *  shows; checking it again is how a removed report comes
 *  back) — plus the optional Generate report button and the
 *  standing rows count. */
