import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function DisasterClaimsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.disasterClaims.showButtons")}
          settings={s}
          name="showButtons"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.disasterClaims.recentCount")}
        settings={s}
        name="recentCount"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Truck accounts (Wave 2): the quick-entry buttons (the
 *  owner's named write action — on by default; the account
 *  page's own door and rules decide every post) and how many
 *  account rows show before the list scrolls. */
