import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export const HEALTH_CHECK_OPTS: { name: string; labelKey: DictKey }[] = [
  { name: "check_database", labelKey: "home.panel.health.database" },
  { name: "check_storage", labelKey: "home.panel.health.storage" },
  { name: "check_backup", labelKey: "home.panel.health.backup" },
  { name: "check_email", labelKey: "home.panel.health.email" },
  { name: "check_stripe", labelKey: "home.panel.health.stripe" },
  { name: "check_ai", labelKey: "home.panel.health.ai" },
  { name: "check_jobs", labelKey: "home.panel.health.jobs" },
];

export function AdminHealthOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.panel.showSummary")} settings={s} name="showSummary" dflt setSetting={api.setSetting} />
      {HEALTH_CHECK_OPTS.map((row) => (
        <CheckRow key={row.name} label={t(row.labelKey)} settings={s} name={row.name} dflt setSetting={api.setSetting} />
      ))}
    </OptionsGroup>
  );
}

