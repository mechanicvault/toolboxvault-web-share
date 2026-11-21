import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, CountRow, ChoicesRow } from "./shared";

export function DealersNearYouOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <ChoicesRow
        label={t("home.opt.near.radius")}
        settings={s}
        name="radiusMiles"
        dflt={50}
        choices={[10, 25, 50, 100]}
        setSetting={api.setSetting}
      />
      <CountRow
        label={t("home.opt.near.rows")}
        settings={s}
        name="rowsToShow"
        dflt={4}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Health checks due (widget wave 2, 2026-11-10): how many
 *  flagged items ride as rows (4 is the widget's default —
 *  the rest wait on the Health Check page itself, one tap
 *  away). Picking the default clears the key, like every
 *  store field. */
