import { useT } from "../../../i18n/LocaleContext";
import { WidgetOptionsApi, OptionsGroup, CheckRow } from "./shared";

export function AccountPlanOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const rows: { label: string; name: string }[] = [
    { label: t("home.opt.accountPlan.showPlan"), name: "showPlan" },
    { label: t("home.opt.accountPlan.showAccount"), name: "showAccount" },
    { label: t("home.opt.accountPlan.showItems"), name: "showItems" },
    { label: t("home.opt.accountPlan.showRenewal"), name: "showRenewal" },
    { label: t("home.opt.accountPlan.showSource"), name: "showSource" },
    { label: t("home.opt.accountPlan.showManage"), name: "showManage" },
    { label: t("home.opt.accountPlan.showAccountBtn"), name: "showAccountBtn" },
  ];
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      {rows.map((r) => (
        <CheckRow
          key={r.name}
          label={r.label}
          settings={s}
          name={r.name}
          dflt
          setSetting={api.setSetting}
        />
      ))}
    </OptionsGroup>
  );
}


/** The three admin PANEL widgets (owner, 2026-11-15): every
 * tile, row and check is its own toggle, all default ON — the
 * same keys the AdminWidgets panel components read. */
