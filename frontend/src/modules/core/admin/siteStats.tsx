import type {DictKey} from "../../../i18n/dictionaries";
import {useT} from "../../../i18n/LocaleContext";
import {
  useAdminWidgets,
  Settings,
  optLine,
  StatRow,
  AdminShell,
  Rows,
} from "./shared";

const TIER_ROWS: { rung: string; labelKey: DictKey; opt: string }[] = [
  { rung: "god", labelKey: "home.admin.tierGod", opt: "showTierGod" },
  {
    rung: "moderator_admin",
    labelKey: "home.admin.tierModAdmin",
    opt: "showTierModAdmin",
  },
  { rung: "moderator", labelKey: "home.admin.tierModerator", opt: "showTierModerator" },
  { rung: "normal", labelKey: "home.admin.tierMember", opt: "showTierMember" },
];

const TYPE_ROWS: { key: string; labelKey: DictKey; opt: string }[] = [
  { key: "mechanic", labelKey: "home.admin.typeMechanic", opt: "showTypeMechanic" },
  { key: "shop", labelKey: "home.admin.typeShop", opt: "showTypeShop" },
  { key: "insurance", labelKey: "home.admin.typeInsurance", opt: "showTypeInsurance" },
  { key: "agent", labelKey: "home.admin.typeAgent", opt: "showTypeAgent" },
];

function deltaText(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "";
  if (delta > 0) return ` (+${delta})`;
  if (delta < 0) return ` (${delta})`;
  return " (±0)";
}

function withDelta(value: number, delta: number | null | undefined) {
  return (
    <>
      {value}
      <span className="tv-admin-note">{deltaText(delta)}</span>
    </>
  );
}

export function AdminSiteStatsWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.site;
  return (
    <AdminShell
      titleKey="home.widget.adminSiteStats"
      icon="adminStats"
      tone="teal"
      door="/admin"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <>
          <Rows>
            {optLine(settings, "showMembers", "showTiers") && (
              <StatRow
                label={t("home.admin.members")}
                value={data.users_total}
                editing={editing}
              />
            )}
            {TIER_ROWS.map(({ rung, labelKey, opt }) =>
              optLine(settings, opt, "showTiers") ? (
                <StatRow
                  key={rung}
                  label={t(labelKey)}
                  value={withDelta(
                    data.users_by_tier[rung] ?? 0,
                    data.tier_deltas?.[rung],
                  )}
                  editing={editing}
                />
              ) : null,
            )}
            {TYPE_ROWS.map(({ key, labelKey, opt }) =>
              optLine(settings, opt) ? (
                <StatRow
                  key={key}
                  label={t(labelKey)}
                  value={withDelta(
                    data.users_by_type[key] ?? 0,
                    data.type_deltas?.[key],
                  )}
                  editing={editing}
                />
              ) : null,
            )}
            {optLine(settings, "showPaying", "showPlans") && (
              <StatRow
                label={t("home.admin.paying")}
                value={withDelta(data.paying_users, data.paying_delta)}
                editing={editing}
              />
            )}
            {optLine(settings, "showFree", "showPlans") && (
              <StatRow label={t("home.admin.free")} value={data.free_users} editing={editing} />
            )}
            {data.paying_by_plan.map((plan) => {
              const deltas = data.plan_deltas?.[plan.plan_key];
              return [
                optLine(settings, `payPlan:${plan.plan_key}:monthly`) && (
                  <StatRow
                    key={`${plan.plan_key}-monthly`}
                    label={`${plan.name} — ${t("home.admin.monthlyWord")}`}
                    value={withDelta(plan.monthly, deltas?.monthly)}
                    editing={editing}
                  />
                ),
                optLine(settings, `payPlan:${plan.plan_key}:annual`) && (
                  <StatRow
                    key={`${plan.plan_key}-annual`}
                    label={`${plan.name} — ${t("home.admin.annualWord")}`}
                    value={withDelta(plan.annual, deltas?.annual)}
                    editing={editing}
                  />
                ),
              ];
            })}
            {optLine(settings, "showMrr") && (
              <StatRow label={t("home.admin.mrr")} value={`$${data.mrr}`} editing={editing} />
            )}
            {optLine(settings, "showToolsTotal", "showTools") && (
              <StatRow
                label={t("home.admin.toolsTotal")}
                value={data.tools_total}
                editing={editing}
              />
            )}
            {optLine(settings, "showToolsToday", "showTools") && (
              <StatRow
                label={t("home.admin.toolsToday")}
                value={data.tools_logged}
                editing={editing}
              />
            )}
            {optLine(settings, "showNewMembers", "showNewPaid") && (
              <StatRow
                label={t("home.admin.newMembersToday")}
                value={data.new_users}
                editing={editing}
              />
            )}
            {optLine(settings, "showNewPaidToday", "showNewPaid") && (
              <StatRow
                label={t("home.admin.newPaidToday")}
                value={data.new_paid}
                editing={editing}
              />
            )}
          </Rows>
          {data.baseline_day === null ? (
            <p className="tv-muted">{t("home.admin.noBaseline")}</p>
          ) : (
            <p className="tv-muted">
              {t("home.admin.comparedTo")} {data.baseline_day}
            </p>
          )}
        </>
      )}
    </AdminShell>
  );
}

/* -- The three admin PANEL widgets (owner, 2026-11-15): the
 * sample panels Ryan picked — Admin overview, Site
 * scoreboard, System health — each its own widget with its
 * own name and options, all reading ONE aggregate endpoint
 * (GET /api/admin/panel, require_user_manager) through a
 * shared cached loader. Every number is a real read (the
 * backend module names the source per number); the health
 * widget shows only checks the site can actually run on
 * itself, and there is no uptime figure anywhere — the site
 * does not measure its own uptime, so the summary counts the
 * checks themselves. */

