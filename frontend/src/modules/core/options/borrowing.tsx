import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function BorrowingOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.borrowing.lentList")}
          settings={s}
          name="lentList"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.borrowedList")}
          settings={s}
          name="borrowedList"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.overdueNames")}
          settings={s}
          name="overdueNames"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.requestsLine")}
          settings={s}
          name="requestsLine"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={3}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Disaster Claims (claims separation, 2026-11-05): the
 *  claims widget's options for the insurance section — recent
 *  rows + the Open / History buttons. */
