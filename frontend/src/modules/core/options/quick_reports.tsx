import { useEffect, useState } from "react";

import { Checkbox } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { listTemplates } from "../../reports/api";
import type { ReportTemplateView } from "../../reports/types";
import { WidgetOptionsApi, OptionsGroup, CheckRow, CountRow } from "./shared";

export function QuickReportsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const [templates, setTemplates] = useState<ReportTemplateView[] | null>(
    null,
  );
  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((data) => {
        if (!cancelled) setTemplates(data.templates);
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const raw = s.hiddenReports;
  const hidden = new Set(Array.isArray(raw) ? raw : []);
  const toggle = (id: string, show: boolean) => {
    const next = new Set(hidden);
    if (show) next.delete(id);
    else next.add(id);
    api.setSetting(
      "hiddenReports",
      next.size > 0 ? Array.from(next) : undefined,
    );
  };
  const quick = (templates ?? []).filter((row) => row.area === "quick");
  return (
    <>
      <OptionsGroup label={t("home.opt.qr.pickLabel")}>
        {quick.map((template) => (
          <Checkbox
            key={template.id}
            label={template.name}
            checked={!hidden.has(template.id)}
            onChange={(e) => toggle(template.id, e.target.checked)}
          />
        ))}
      </OptionsGroup>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.qr.generateButton")}
          settings={s}
          name="showGenerate"
          dflt={false}
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.qr.rowsToShow")}
        settings={s}
        name="rowsToShow"
        dflt={5}
        min={1}
        max={10}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Tool Expansion (Wave 4 batch B): how many suggestions
 *  ride (2 is today's widget) and the known-addons count
 *  line's switch. */
