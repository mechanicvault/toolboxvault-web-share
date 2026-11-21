import { Fragment, useEffect, useState } from "react";
import { useT } from "../../../i18n/LocaleContext";
import { api as fetchApi } from "../../../lib/api";
import { WidgetOptionsApi, optBool, OptionsGroup, CheckRow } from "./shared";

export interface AdminPlanOption {
  plan_key: string;
  name: string;
}

/** Site Stats options (polish lane, owner 2026-11-07): EVERY
 *  row line is its own toggle — the admin lane's grouped
 *  switches (members-by-tier as one, free-vs-paying as one…)
 *  are gone. A line that was never toggled still follows its
 *  old group switch when one is saved, so existing admin
 *  layouts keep their choices; the per-line default each
 *  CheckRow is handed IS that fallback. The paying-by-plan
 *  lines are one toggle per plan per billing period — the
 *  plan list is the admin payload's own (the FlyersOptions
 *  pattern: the section reads the data it configures). */
export function AdminSiteStatsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const [plans, setPlans] = useState<AdminPlanOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchApi<{ site: { paying_by_plan: AdminPlanOption[] } }>(
      "/admin/home-widgets",
    )
      .then((data) => {
        if (!cancelled) setPlans(data.site.paying_by_plan ?? []);
      })
      .catch(() => {
        if (!cancelled) setPlans([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const tiersDflt = optBool(s, "showTiers", true);
  const plansDflt = optBool(s, "showPlans", true);
  const toolsDflt = optBool(s, "showTools", true);
  const newDflt = optBool(s, "showNewPaid", true);
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showMembers")} settings={s} name="showMembers" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierGod")} settings={s} name="showTierGod" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierModAdmin")} settings={s} name="showTierModAdmin" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierModerator")} settings={s} name="showTierModerator" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierMember")} settings={s} name="showTierMember" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeMechanic")} settings={s} name="showTypeMechanic" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeShop")} settings={s} name="showTypeShop" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeInsurance")} settings={s} name="showTypeInsurance" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeAgent")} settings={s} name="showTypeAgent" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showPaying")} settings={s} name="showPaying" dflt={plansDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showFree")} settings={s} name="showFree" dflt={plansDflt} setSetting={api.setSetting} />
      {plans.map((plan) => (
        <Fragment key={plan.plan_key}>
          <CheckRow
            label={`${plan.name} — ${t("home.opt.admin.monthlyPaying")}`}
            settings={s}
            name={`payPlan:${plan.plan_key}:monthly`}
            dflt
            setSetting={api.setSetting}
          />
          <CheckRow
            label={`${plan.name} — ${t("home.opt.admin.annualPaying")}`}
            settings={s}
            name={`payPlan:${plan.plan_key}:annual`}
            dflt
            setSetting={api.setSetting}
          />
        </Fragment>
      ))}
      <CheckRow label={t("home.opt.admin.showMrr")} settings={s} name="showMrr" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showToolsTotal")} settings={s} name="showToolsTotal" dflt={toolsDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showToolsToday")} settings={s} name="showToolsToday" dflt={toolsDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewMembers")} settings={s} name="showNewMembers" dflt={newDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewPaidToday")} settings={s} name="showNewPaidToday" dflt={newDflt} setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

/** Account & Plan (Sweep B1, finding 01-F5): the widget's loader
 *  already honours a show* switch for every stat, note line, and
 *  button it renders (they gate the custom-box aspects too) — the
 *  predefined widget simply had no registered panel, so its Edit
 *  options held only the width toggle. These rows write the exact
 *  names/defaults the loader reads. */
