import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function FeedbackOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.feedback.countLine")}
          settings={s}
          name="showCounts"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.feedback.rowsPerBoard")}
        settings={s}
        name="rowsPerBoard"
        dflt={3}
        min={0}
        max={3}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Shared tools (Wave 4 batch B): the two lines each get a
 *  switch (both on = today). The sharer-name rows are the
 *  widget's new shape and carry no switch of their own —
 *  the design names none. */
