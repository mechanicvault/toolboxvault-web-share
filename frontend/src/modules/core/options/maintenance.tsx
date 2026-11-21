import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function MaintenanceOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.maintenance.dueLine")}
          settings={s}
          name="showDue"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.outLine")}
          settings={s}
          name="showOut"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.comingUp")}
          settings={s}
          name="comingUp"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.openClaimsLine")}
          settings={s}
          name="showClaimsLine"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.backorderedLine")}
          settings={s}
          name="showBackordered"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.claimsList")}
          settings={s}
          name="claimsList"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.claimButtons")}
          settings={s}
          name="showClaimButtons"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
      <CountRow
        label={t("home.opt.claims.recentCount")}
        settings={s}
        name="claimCount"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Reports (Wave 4 batch A): how many saved reports ride as
 *  rows before the list scrolls (2 is today's count). At full
 *  width the rows are links that open that report. */
