import { useEffect, useState } from "react";

import { Checkbox } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { listSources as listFlyerSources } from "../../flyers/api";
import { sourceTitle, type FlyerSource } from "../../flyers/types";
import { WidgetOptionsApi, OptionsGroup } from "./shared";

export function FlyersOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const [sources, setSources] = useState<FlyerSource[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listFlyerSources()
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const raw = api.block.settings.hiddenSources;
  const hidden = new Set(Array.isArray(raw) ? raw : []);
  const toggle = (key: string, show: boolean) => {
    const next = new Set(hidden);
    if (show) next.delete(key);
    else next.add(key);
    api.setSetting(
      "hiddenSources",
      next.size > 0 ? Array.from(next) : undefined,
    );
  };
  return (
    <OptionsGroup label={t("flyers.optSources")}>
      {(sources ?? []).map((source) => (
        <Checkbox
          key={source.key}
          label={sourceTitle(source)}
          checked={!hidden.has(source.key)}
          onChange={(e) => toggle(source.key, e.target.checked)}
        />
      ))}
    </OptionsGroup>
  );
}

/** Admin widgets (admin lane, 2026-11-07; polish lane,
 *  2026-11-07): every stat ROW in every admin widget is its
 *  own toggle, all default ON — the seat hides what they
 *  don't watch, line by line; the admin lane's grouped Site
 *  Stats switches were retired by the polish lane (a saved
 *  group choice still reads as the per-line default until
 *  the line itself is toggled — see AdminSiteStatsOptions).
 *  The keys here are the same keys AdminWidgets reads. */
