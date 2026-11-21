import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function ExpansionOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.expansion.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.expansion.rowsToShow")}
        settings={s}
        name="rowsToShow"
        dflt={2}
        min={2}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** My Parts (Wave 4 batch B, parked): the parts ride as
 *  rows — 2 visible before the rest scroll is today's
 *  count of titles — and the shelf count line's switch. */
