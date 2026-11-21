import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function PartsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.parts.shelfLine")}
          settings={s}
          name="showShelf"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={2}
        min={2}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Tools For Sale (Wave 4 batch B, parked): how many
 *  listings ride (3 is today's widget) and whether each
 *  listing's price sits beside its title — a pure extra,
 *  so it defaults off (today's titles-only board glance). */
