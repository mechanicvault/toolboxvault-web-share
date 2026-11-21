import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, CountRow } from "./shared";

export function ReportsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <CountRow
      label={t("home.opt.rowsBeforeScroll")}
      settings={s}
      name="rowsVisible"
      dflt={2}
      min={2}
      max={5}
      setSetting={api.setSetting}
    />
  );
}

/** Dealers (REBUILT, dashboard-flare lane 2026-11-09): the
 *  widget is the user's dealer tiles now — the count line
 *  gets a switch and the strip a size. The Wave 4 agent-stat
 *  switches (showPreferred / showProfile) retire with the
 *  lines they governed; a stored bundle carrying them is
 *  simply inert. */
