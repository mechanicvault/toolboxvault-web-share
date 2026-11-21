import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function DealersOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.dealers.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.dealers.tiles")}
        settings={s}
        name="tilesToShow"
        dflt={8}
        min={4}
        max={16}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Dealers near you (widget wave 2, 2026-11-10): the search
 *  radius the widget reads with (50 is the widget's default —
 *  the Find an Agent page's own presets are the choice set)
 *  and how many (agent, dealer) rows ride. Picking a default
 *  clears its key, like every store field. */
