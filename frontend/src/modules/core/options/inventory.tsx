import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function InventoryOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.inventory.addButton")}
          settings={s}
          name="addButton"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.valueLine")}
          settings={s}
          name="showValue"
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
        label={t("home.opt.inventory.recentCount")}
        settings={s}
        name="recentCount"
        dflt={5}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Borrowing (Wave 2): the lent / borrowed lists, the overdue
 *  names, the requests line, and how many rows show before a
 *  list scrolls inside the box (the owner's default: 3). */
