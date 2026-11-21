import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, CountRow } from "./shared";

export function HealthChecksDueOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <CountRow
      label={t("home.opt.health.rows")}
      settings={s}
      name="rowsToShow"
      dflt={4}
      min={2}
      max={6}
      setSetting={api.setSetting}
    />
  );
}

/** Feedback (Wave 4 batch B): the newest titles from each
 *  board ride as rows under the counts line — the owner's
 *  named shape, on by default at 3 per board; 0 is the off
 *  switch, restoring today's counts-only widget exactly.
 *  The counts line itself gets a switch too. */
