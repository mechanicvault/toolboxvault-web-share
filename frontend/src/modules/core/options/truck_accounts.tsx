import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function TruckOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.truck.quickEntry")}
          settings={s}
          name="quickEntry"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.accountsBeforeScroll")}
        settings={s}
        name="rowsVisible"
        dflt={3}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Dealer truck widget (sheet row 29): how many customer rows
 *  show, and whether the received-this-week line rides. */
