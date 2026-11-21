import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function DealerTruckOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.dealerTruck.showReceived")}
          settings={s}
          name="showReceived"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.accountsBeforeScroll")}
        settings={s}
        name="rowsVisible"
        dflt={5}
        min={2}
        max={10}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Forum (Wave 3): which favorite the expanded (full-width)
 *  widget features. The choices are the member's own favorites,
 *  fetched once when the popover opens (the design's flagged
 *  extra read — the same list the widget itself reads). "Most
 *  recent activity" is the default and stores nothing; picking
 *  a favorite stores its kind:id key. A stored pick whose
 *  target later becomes invisible is never an error: the
 *  widget falls back to the next favorite, then the empty
 *  state, on its own. */
