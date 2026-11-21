import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function WishlistOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.wishlist.wantedLine")}
          settings={s}
          name="showWanted"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.wishlist.highLine")}
          settings={s}
          name="showHigh"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.latestLine")}
          settings={s}
          name="showLatest"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="wantedRows"
        dflt={3}
        min={0}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Flyers (2026-11-06): which connected dealers/agents show
 *  in the widget — one checkbox per flyer source; unchecking
 *  stores the source's key in hiddenSources (absence of the
 *  key = everything shows, the settings discipline). */
