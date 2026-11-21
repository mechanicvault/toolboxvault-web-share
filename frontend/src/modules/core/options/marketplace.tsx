import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function MarketplaceOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.marketplace.prices")}
          settings={s}
          name="showPrices"
          dflt={false}
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.marketplace.listingCount")}
        settings={s}
        name="listingCount"
        dflt={3}
        min={3}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Messages (Wave 4 batch B, parked): the two count lines
 *  each get a switch, and the latest-conversation names —
 *  the design's flagged extra read — get theirs: the read
 *  only happens while the names are switched on. */
